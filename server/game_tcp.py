"""Standalone asyncio game TCP compatibility server."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from .config import (
    ConfigError,
    DEFAULT_GAME_INIT_CAPTURE,
    DEFAULT_GAMEPLAY_CAPTURE,
    Settings,
    load_settings,
)
from .fixture_tool import load_fixture
from .startup_template import load_startup_template
from .game_proto import (
    Frame,
    ProtoError,
    decode_frame,
    decode_gacha_request,
    decode_hero_level_up_request,
    decode_login_request,
    decode_order_request,
    encode_role_bag,
    encode_startup_hero_ntf,
    decode_risk_bat_win_request,
    decode_string_map_field,
    encode_bytes_field,
    encode_frame,
    encode_login_ack,
    encode_gacha_ack,
    encode_hero_change_ntf,
    encode_gacha_list_ack,
    encode_gacha_open_ntf,
    encode_order_ack,
    encode_risk_bat_settlement,
    encode_risk_bat_win_ack,
    encode_risk_battle_ntf,
    encode_risk_start_ack,
    encode_role_info,
    encode_role_risk_battle,
    encode_role_strength,
    encode_role_strength_ntf,
    encode_string_map_field,
    encode_string_field,
    encode_varint_field,
    encode_win_settlement,
    extract_role_base,
    extract_startup_parts,
    get_bytes,
    get_repeated_varints,
    get_string,
    get_varint,
    patch_bytes,
    patch_role_base_diamond,
    patch_string,
    patch_varint,
)
from .products import resolve_product_by_goods_id
from .game_state import (
    get_operation,
    merge_role_state,
    normalize_role_state,
    operation_key,
    patch_role_base_from_state,
    record_operation,
)
from .storage import Storage


logger = logging.getLogger("game_tcp_server")


REPLAY_REQUEST_RESPONSE_IDS = {
    1: 2,
    23: 24,
    59: 60,
    61: 62,
    166: 167,
    170: 171,
    327: 328,
    349: 350,
    368: 369,
    370: 371,
    374: 375,
    24146: 24147,
}
PLAY_REQUEST_RESPONSE_IDS = {
    29: 30,
    31: 32,
    63: 64,
    93: 94,
    109: 110,
    111: 112,
    141: 142,
    143: 144,
    24152: 24153,
    24183: 24184,
    327: 328,
    329: 330,
    370: 371,
    374: 375,
    24146: 24147,
}
STARTUP_REPLAY_IDS = {7, 4, 25, 26, 27, 28}

# Confirmed by the official TCP capture: CSGuideSaveReq(59) carries one
# segment/step record, while the server exposes cumulative completion flags.
GUIDE_COMPLETION_KEYS = {
    "TutorialForceFirstBattle": "guide_first_battle",
    "TutorialForceBattleFormat": "guide_format_page",
    "TutorialForceHInteractive": "guide_h_interactive",
    "TutorialForceDrawCard": "guide_drawcard",
    "TutorialForceBattleTeam": "guide_battle_team",
    "TutorialForceBattleFour": "guide_battle_four",
    "TutorialForceHPlay": "guide_h_play",
    "TutorialForceBattleFive": "guide_battle_five",
    "TutorialForceFinalBattle": "guide_battle_final",
    "TutorialOptionalHeroGrowth": "herogrowth_10002",
}
GUIDE_TERMINAL_STEPS = {
    "TutorialForceFirstBattle": {"2_TreeRefNode", "5_ToggleLockNode"},
    "TutorialOptionalHeroGrowth": {"4_IfTutorialNotSavedNode"},
}


def _guide_terminal_steps(segment_id: str) -> set[str]:
    if segment_id in GUIDE_TERMINAL_STEPS:
        return GUIDE_TERMINAL_STEPS[segment_id]
    if segment_id.startswith("TutorialForce"):
        return {"3_TreeRefNode"}
    return set()


def _apply_guide_save(guide: dict[str, str], record: dict[str, str]) -> tuple[dict[str, str], str | None]:
    """Convert one official guide step record into persistent server state."""
    result = {str(key): str(value) for key, value in guide.items()}
    for key, value in record.items():
        if value:
            result[str(key)] = str(value)
    for key in ("guide_session_id", "segment_id", "step_id", "step_status"):
        value = str(record.get(key, ""))
        if value:
            result[key] = value

    segment_id = str(record.get("segment_id", ""))
    step_id = str(record.get("step_id", ""))
    status = str(record.get("step_status", ""))
    completion_key = GUIDE_COMPLETION_KEYS.get(segment_id)
    if completion_key and status == "1" and step_id in _guide_terminal_steps(segment_id):
        result[completion_key] = "1"
        return result, completion_key
    return result, None


def _token_fingerprint(token: str) -> str:
    if not token:
        return "-"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


async def _read_frame(reader: asyncio.StreamReader) -> Frame:
    header = await reader.readexactly(10)
    body_length = int.from_bytes(header[0:2], "big")
    body = await reader.readexactly(body_length)
    return decode_frame(header + body)


class GameTcpServer:
    def __init__(
        self,
        *,
        storage: Storage | None = None,
        settings: Settings | None = None,
        host: str | None = None,
        port: int | None = None,
        server_id: int | None = None,
        fixture_dir: Path | None = None,
          startup_template: Path | None = None,
        response_capture: Path | None = None,
        gameplay_capture: Path | None = None,
        poll_interval: float | None = None,
        trace: bool | None = None,
    ) -> None:
        resolved_settings = settings or load_settings()
        self.storage = storage or Storage(
            database_path=resolved_settings.storage.database_path,
            token_ttl_seconds=resolved_settings.storage.token_ttl_seconds,
        )
        self.host = resolved_settings.game.tcp_host if host is None else host
        self.port = resolved_settings.game.tcp_port if port is None else port
        self.server_id = resolved_settings.game.server_id if server_id is None else server_id
        self.fixture_dir = fixture_dir or resolved_settings.game.fixture_dir
        self.startup_template = startup_template
        self.response_capture = response_capture
        self.gameplay_capture = gameplay_capture
        if settings is not None:
            if self.startup_template is None:
                self.startup_template = resolved_settings.game.startup_template
            if self.response_capture is None:
                self.response_capture = resolved_settings.game.init_capture
            if self.gameplay_capture is None:
                self.gameplay_capture = resolved_settings.game.gameplay_capture
        self.poll_interval = resolved_settings.game.poll_interval if poll_interval is None else poll_interval
        self.trace = resolved_settings.game.trace if trace is None else trace
        self.notify_url = resolved_settings.game.notify_url
        self.sessions: dict[int, asyncio.StreamWriter] = {}
        self._server: asyncio.AbstractServer | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._capture_records_cache: list[tuple[str, Frame]] | None = None
        self._response_templates_cache: dict[tuple[int, bytes], Frame] | None = None
        self._response_by_request_id_cache: dict[int, list[Frame]] | None = None
        self._gameplay_records_cache: list[tuple[str, Frame]] | None = None

    def _fixtures(self) -> list[dict[str, Any]]:
        if not self.fixture_dir.exists():
            return []
        fixtures: list[dict[str, Any]] = []
        for path in sorted(self.fixture_dir.glob("*.json")):
            try:
                fixture = load_fixture(path)
            except ProtoError as exc:
                logger.warning("fixture rejected path=%s reason=%s", path, exc)
                continue
            fixture["fixture_path"] = str(path)
            fixtures.append(fixture)
        return fixtures

    def _fixture_for_login(self, request: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
        if not self.fixture_dir.exists():
            return None, "fixture_dir_missing", "none"
        fixtures = [item for item in self._fixtures() if item["server_id"] == self.server_id]
        if not fixtures:
            return None, "fixture_empty", "none"

        open_id = str(request.get("open_id") or "")
        user_id = str(request.get("user_id") or "")
        if open_id:
            for fixture in fixtures:
                if fixture.get("login_open_id", "") == open_id:
                    configured_user_id = str(fixture.get("login_user_id", "") or "")
                    if user_id and user_id != configured_user_id:
                        return None, "identity_mismatch", "open_id"
                    return fixture, "", "open_id"
        if user_id:
            for fixture in fixtures:
                if fixture.get("login_user_id", "") == user_id:
                    configured_open_id = str(fixture.get("login_open_id", "") or "")
                    if open_id and open_id != configured_open_id:
                        return None, "identity_mismatch", "user_id"
                    return fixture, "", "user_id"
        return None, "fixture_missing", "open_id" if open_id else "user_id"

    @staticmethod
    def _fixture_frames(fixture: dict[str, Any]) -> list[Frame]:
        return [Frame.from_json(item) for item in fixture["messages"]]

    def _startup_template_frames(self) -> list[Frame]:
        if self.startup_template is None:
            raise ProtoError("startup template is not configured")
        return load_startup_template(self.startup_template)

    def _capture_records(self) -> list[tuple[str, Frame]]:
        if self._capture_records_cache is not None:
            return self._capture_records_cache
        self._capture_records_cache = []
        if self.response_capture is None or not self.response_capture.exists():
            return self._capture_records_cache
        try:
            value = json.loads(self.response_capture.read_text(encoding="utf-8"))
            source_frames = value.get("frames") if isinstance(value, dict) else None
            if not isinstance(source_frames, list):
                raise ProtoError("capture must contain a frames list")
            for item in source_frames:
                if not isinstance(item, dict) or item.get("direction") not in {"c2s", "s2c"}:
                    continue
                if "body_b64" not in item:
                    continue
                frame = Frame.from_json(
                    {
                        "msg_id": item.get("msg_id"),
                        "seq": item.get("seq", 0),
                        "flag": item.get("flag", 0),
                        "body_b64": item.get("body_b64", ""),
                    }
                )
                if "body_len" in item and int(item["body_len"]) != len(frame.body):
                    raise ProtoError(f"capture frame {frame.msg_id} body length mismatch")
                self._capture_records_cache.append((str(item["direction"]), frame))
        except (OSError, TypeError, ValueError, json.JSONDecodeError, ProtoError) as exc:
            logger.warning("game init capture rejected path=%s reason=%s", self.response_capture, exc)
            self._capture_records_cache = []
        return self._capture_records_cache

    def _gameplay_records(self) -> list[tuple[str, Frame]]:
        if self._gameplay_records_cache is not None:
            return self._gameplay_records_cache
        self._gameplay_records_cache = []
        if self.gameplay_capture is None or not self.gameplay_capture.exists():
            return self._gameplay_records_cache
        try:
            value = json.loads(self.gameplay_capture.read_text(encoding="utf-8"))
            source_frames = value.get("frames") if isinstance(value, dict) else None
            if not isinstance(source_frames, list):
                raise ProtoError("gameplay capture must contain a frames list")
            for item in source_frames:
                if not isinstance(item, dict) or item.get("direction") not in {"c2s", "s2c"}:
                    continue
                if "body_b64" not in item:
                    continue
                frame = Frame.from_json(
                    {
                        "msg_id": item.get("msg_id"),
                        "seq": item.get("seq", 0),
                        "flag": item.get("flag", 0),
                        "body_b64": item.get("body_b64", ""),
                    }
                )
                if "body_len" in item and int(item["body_len"]) != len(frame.body):
                    raise ProtoError(f"gameplay frame {frame.msg_id} body length mismatch")
                self._gameplay_records_cache.append((str(item["direction"]), frame))
        except (OSError, TypeError, ValueError, json.JSONDecodeError, ProtoError) as exc:
            logger.warning("gameplay capture rejected path=%s reason=%s", self.gameplay_capture, exc)
            self._gameplay_records_cache = []
        return self._gameplay_records_cache

    def _gameplay_event(self, request: Frame) -> list[Frame]:
        """Return the captured server pushes belonging to one gameplay request."""
        records = self._gameplay_records()
        request_index = next(
            (
                index
                for index, (direction, frame) in enumerate(records)
                if direction == "c2s"
                and frame.msg_id == request.msg_id
                and frame.body == request.body
            ),
            None,
        )
        if request_index is None:
            def same_business_request(candidate: Frame) -> bool:
                if candidate.msg_id in {141, 143}:
                    return get_varint(candidate.body, 1) == get_varint(request.body, 1)
                if candidate.msg_id == 31:
                    return (
                        get_varint(candidate.body, 1) == get_varint(request.body, 1)
                        and get_varint(candidate.body, 2) == get_varint(request.body, 2)
                    )
                if candidate.msg_id == 93:
                    return get_varint(candidate.body, 1) == get_varint(request.body, 1)
                return False

            request_index = next(
                (
                    index
                    for index, (direction, frame) in enumerate(records)
                    if direction == "c2s"
                    and frame.msg_id == request.msg_id
                    and same_business_request(frame)
                ),
                None,
            )
        if request_index is None:
            return []

        expected_response = PLAY_REQUEST_RESPONSE_IDS.get(request.msg_id)
        if expected_response is None:
            return []

        # The capture is a live session, so transport heartbeats and clock
        # requests can be interleaved with a business request.  They must not
        # terminate the window before its business ACK arrives.
        ignored_responses = {2, 60}
        known_response_ids = set(REPLAY_REQUEST_RESPONSE_IDS.values()) | set(PLAY_REQUEST_RESPONSE_IDS.values())
        keep_tail_after_ack = request.msg_id == 141
        result: list[Frame] = []
        saw_expected_response = False
        for direction, frame in records[request_index + 1 :]:
            if direction == "s2c":
                if frame.msg_id in ignored_responses or (
                    frame.msg_id in known_response_ids and frame.msg_id != expected_response
                ):
                    continue
                if request.msg_id == 63 and frame.msg_id != expected_response:
                    continue
                result.append(frame)
                if frame.msg_id == expected_response:
                    saw_expected_response = True
                    if not keep_tail_after_ack:
                        break
                continue

            if not saw_expected_response:
                continue
            if keep_tail_after_ack and saw_expected_response and frame.msg_id == 1:
                continue
            break

        return result if saw_expected_response else []

    @staticmethod
    def _patch_gameplay_frame(frame: Frame, role: Any, state: dict[str, Any]) -> Frame:
        body = frame.body
        if frame.msg_id == 76:
            # Keep the captured full RoleBase shape, but bind it to the local role.
            body = patch_varint(body, 1, int(state.get("coin", 0))) if get_varint(body, 1) else body
            body = patch_varint(body, 2, int(state.get("diamond", role["diamond"])))
            role_base = get_bytes(body, 3)
            if role_base is not None:
                try:
                    game_uid = int(role["game_uid"])
                except (TypeError, ValueError):
                    game_uid = get_varint(role_base, 1)
                role_base = patch_varint(role_base, 1, game_uid)
                role_base = patch_role_base_diamond(role_base, int(state.get("diamond", role["diamond"])))
                body = patch_bytes(body, 3, role_base)
        elif frame.msg_id == 149:
            risk = get_bytes(body, 1)
            if risk is not None:
                level_id = int(state.get("risk", {}).get("current_level", 0))
                if level_id:
                    risk = patch_varint(risk, 1, level_id)
                body = patch_bytes(body, 1, risk)
        return Frame(body, frame.msg_id, frame.seq, frame.flag)

    def _capture_startup_frames(self, fixture_frames: list[Frame]) -> list[Frame]:
        """Merge captured server pushes with the fixture's patched startup frames."""
        records = self._capture_records()
        if not records:
            return [frame for frame in fixture_frames if frame.msg_id in {25, 26, 27, 28}]

        ack_index = next(
            (index for index, (direction, frame) in enumerate(records) if direction == "s2c" and frame.msg_id == 4),
            None,
        )
        if ack_index is None:
            return [frame for frame in fixture_frames if frame.msg_id in {25, 26, 27, 28}]

        fixture_by_id: dict[int, list[Frame]] = {}
        for frame in fixture_frames:
            fixture_by_id.setdefault(frame.msg_id, []).append(frame)
        result: list[Frame] = []
        for direction, frame in records[ack_index + 1 :]:
            if direction == "c2s":
                break
            if frame.msg_id in {7, 4}:
                continue
            if frame.msg_id in {25, 26, 27, 28}:
                candidates = fixture_by_id.get(frame.msg_id, [])
                if candidates:
                    result.append(candidates.pop(0))
                continue
            result.append(frame)
        if not any(frame.msg_id == 28 for frame in result):
            return [frame for frame in fixture_frames if frame.msg_id in {25, 26, 27, 28}]
        return result

    def _response_templates(self) -> tuple[dict[tuple[int, bytes], Frame], dict[int, list[Frame]]]:
        if self._response_templates_cache is not None and self._response_by_request_id_cache is not None:
            return self._response_templates_cache, self._response_by_request_id_cache
        templates: dict[tuple[int, bytes], Frame] = {}
        by_request_id: dict[int, list[Frame]] = {}
        pending: dict[int, list[Frame]] = {}
        for direction, frame in self._capture_records():
            if direction == "c2s":
                if frame.msg_id in REPLAY_REQUEST_RESPONSE_IDS:
                    pending.setdefault(frame.msg_id, []).append(frame)
                continue
            request_id = next(
                (candidate for candidate, response_id in REPLAY_REQUEST_RESPONSE_IDS.items() if response_id == frame.msg_id),
                None,
            )
            if request_id is None or not pending.get(request_id):
                continue
            request = pending[request_id].pop(0)
            response = Frame(frame.body, frame.msg_id, frame.seq, frame.flag)
            templates[(request.msg_id, request.body)] = response
            by_request_id.setdefault(request.msg_id, []).append(response)
        self._response_templates_cache = templates
        self._response_by_request_id_cache = by_request_id
        return templates, by_request_id

    @staticmethod
    def _patch_nested_uid(body: bytes, outer_field: int, inner_field: int, game_uid: str) -> bytes:
        try:
            uid = int(game_uid)
        except (TypeError, ValueError):
            return body
        nested = get_bytes(body, outer_field)
        if nested is None:
            return body
        return patch_bytes(body, outer_field, patch_varint(nested, inner_field, uid))

    def _response_for_request(self, frame: Frame, role: Any) -> Frame | None:
        response_id = REPLAY_REQUEST_RESPONSE_IDS.get(frame.msg_id)
        if response_id is None:
            return None
        templates, by_request_id = self._response_templates()
        template = templates.get((frame.msg_id, frame.body))
        if template is None and frame.msg_id == 166:
            request_index = get_varint(frame.body, 1)
            template = next(
                (item for item in by_request_id.get(frame.msg_id, []) if get_varint(item.body, 2) == request_index),
                None,
            )
        if template is None and frame.msg_id == 327:
            request_key = get_string(frame.body, 1)
            template = next(
                (item for item in by_request_id.get(frame.msg_id, []) if get_string(item.body, 2) == request_key),
                None,
            )
        if template is None:
            candidates = by_request_id.get(frame.msg_id, [])
            template = candidates[0] if candidates else None

        if template is None:
            # Keep basic ACK-only messages usable when an optional capture is absent.
            if frame.msg_id == 327:
                body = encode_string_field(2, get_string(frame.body, 1))
            elif frame.msg_id == 166:
                body = encode_varint_field(2, get_varint(frame.body, 1))
            elif frame.msg_id == 24146:
                body = encode_bytes_field(2, b"")
            else:
                body = b""
            return Frame(body, response_id, frame.seq, frame.flag)

        body = template.body
        game_uid = str(role["game_uid"])
        if frame.msg_id == 23:
            body = self._patch_nested_uid(body, 2, 1, game_uid)
        elif frame.msg_id == 166:
            body = self._patch_nested_uid(body, 5, 3, game_uid)
        return Frame(body, response_id, frame.seq, frame.flag)

    async def _send(self, writer: asyncio.StreamWriter, frame: Frame) -> None:
        if self.trace:
            peer = writer.get_extra_info("peername")
            digest = hashlib.sha256(frame.body).hexdigest()[:12]
            logger.info(
                "game frame direction=out peer=%s msg_id=%s seq=%s flag=%s body_len=%s body_sha256=%s",
                peer,
                frame.msg_id,
                frame.seq,
                frame.flag,
                len(frame.body),
                digest,
            )
        writer.write(encode_frame(frame))
        await writer.drain()

    async def _reject_login(
        self,
        writer: asyncio.StreamWriter,
        frame: Frame,
        request: dict[str, Any],
        *,
        reason: str,
        match_key: str = "none",
        sdk_user_id: int = 0,
        fixture_path: str = "",
    ) -> None:
        await self._send(writer, Frame(encode_login_ack(error=1001), 4, frame.seq, 0))
        logger.warning(
            "game login rejected server_id=%s select_zone=%s open_id=%s user_id=%s account=%s "
            "auth_type=%s sdk_user_id=%s fixture_match_key=%s fixture_path=%s failure_reason=%s token_fp=%s",
            self.server_id,
            request.get("select_zone", 0),
            request.get("open_id", ""),
            request.get("user_id", ""),
            request.get("account", ""),
            request.get("auth_type", ""),
            sdk_user_id,
            match_key,
            fixture_path,
            reason,
            _token_fingerprint(str(request.get("auth_token") or "")),
        )

    async def _send_startup(self, writer: asyncio.StreamWriter, role: Any) -> None:
        try:
            fixture = json.loads(role["startup_json"])
            frames = self._fixture_frames({"messages": fixture})
        except (TypeError, json.JSONDecodeError, KeyError, ProtoError) as exc:
            raise ProtoError("stored role startup fixture is invalid") from exc
        state = self._role_state(role)
        persisted_role_base = self._patch_local_role_base(role, state)
        persisted_role_bag = bytes(role["role_bag_blob"] or b"")
        bag_state = dict(state.get("role_bag") or {})
        structured_bag = encode_role_bag(bag_state)
        if bag_state.get("wire_dirty") or structured_bag:
            persisted_role_bag = structured_bag
        hero_state = dict(state.get("heroes") or {})
        lineups = dict(state.get("lineups") or {})
        by_id = dict(lineups.get("by_id") or {})
        active_id = int(lineups.get("active_id", 0) or 0)
        equipment_state = dict(state.get("equipment") or {})
        equipment_wire = b""
        if equipment_state.get("wire_b64"):
            try:
                equipment_wire = base64.b64decode(str(equipment_state["wire_b64"]), validate=True)
            except (ValueError, base64.binascii.Error):
                equipment_wire = b""
        guide = {str(key): str(value) for key, value in dict(state.get("guide") or {}).items()}
        guide_body = encode_string_map_field(1, guide) if guide else b""
        guide_sent = False
        risk_state = dict(state.get("risk_battle") or {})
        risk_body = encode_role_risk_battle(risk_state)
        strength_state = dict(state.get("strength_state") or {})
        strength_body = encode_role_strength(
            int(strength_state.get("current", 100) or 0),
            int(strength_state.get("max", 100) or 100),
        )
        if self.startup_template is not None and Path(self.startup_template).exists():
            startup_frames = self._startup_template_frames()
        else:
            startup_frames = self._capture_startup_frames(frames)
        for frame in startup_frames:
            body = frame.body
            if frame.msg_id == 25 and get_bytes(body, 4) is not None:
                body = patch_bytes(body, 4, persisted_role_base)
            if frame.msg_id == 25 and persisted_role_bag and get_bytes(body, 5) is not None:
                body = patch_bytes(body, 5, persisted_role_bag)
            if frame.msg_id == 25 and guide_body and not guide_sent:
                body = patch_bytes(body, 123, guide_body)
                guide_sent = get_bytes(body, 123) == guide_body
            if frame.msg_id == 25 and get_bytes(body, 6) is not None:
                body = patch_bytes(body, 6, risk_body)
            if frame.msg_id == 25 and get_bytes(body, 125) is not None:
                body = patch_bytes(body, 125, strength_body)
            if frame.msg_id == 27:
                try:
                    replay_body = get_bytes(body, 2)
                except ProtoError:
                    replay_body = None
                body = encode_startup_hero_ntf(
                    hero_state,
                    by_id,
                    active_id,
                    replay_body=replay_body,
                )
            if frame.msg_id == 26 and equipment_wire:
                body = equipment_wire
            await self._send(writer, Frame(body=body, msg_id=frame.msg_id, seq=frame.seq, flag=frame.flag))

    async def _handle_change_nickname(
        self,
        frame: Frame,
        writer: asyncio.StreamWriter,
        role_id: int,
    ) -> None:
        nickname = get_string(frame.body, 1)
        if not nickname.strip():
            await self._send(
                writer,
                Frame(encode_varint_field(1, 105), 22, frame.seq, frame.flag),
            )
            logger.info(
                "game nickname rejected role_id=%s msg_id=%s reason=empty_nickname",
                role_id,
                frame.msg_id,
            )
            return

        role = self.storage.get_game_role(role_id)
        if role is None:
            await self._send(
                writer,
                Frame(encode_varint_field(1, 3), 22, frame.seq, frame.flag),
            )
            logger.warning(
                "game nickname rejected role_id=%s msg_id=%s reason=role_missing",
                role_id,
                frame.msg_id,
            )
            return

        state = merge_role_state(self._role_state(role), {"role_base": {"nickname": nickname}})
        role_base = self._patch_local_role_base(role, state)
        updated_role = self.storage.merge_game_state(
            role_id,
            {"role_base": {"nickname": nickname}},
            role_base_blob=role_base,
        )
        state = self._role_state(updated_role)
        if not await self._send_gameplay_event(frame, writer, updated_role, state, response_id=22, role_id=role_id):
            await self._send(writer, Frame(b"", 22, frame.seq, frame.flag))
        logger.info(
            "game nickname updated role_id=%s nickname=%s role_version=%s",
            role_id,
            nickname,
            updated_role["role_version"],
        )

    def _role_state(self, role: Any) -> dict[str, Any]:
        try:
            raw_state = json.loads(str(role["game_state_json"] or "{}"))
        except (KeyError, TypeError, json.JSONDecodeError):
            raw_state = {}
        hero_body = None
        try:
            startup = json.loads(str(role["startup_json"] or "[]"))
            startup_frames = self._fixture_frames({"messages": startup})
            hero_frame = next((item for item in startup_frames if item.msg_id == 27), None)
            equipment_frame = next((item for item in startup_frames if item.msg_id == 26), None)
            hero_body = hero_frame.body if hero_frame is not None else None
            equipment_body = equipment_frame.body if equipment_frame is not None else None
        except (KeyError, TypeError, json.JSONDecodeError, ProtoError):
            hero_body = None
            equipment_body = None
        return normalize_role_state(
            raw_state,
            bytes(role["role_base_blob"] or b""),
            bytes(role["role_bag_blob"] or b""),
            hero_body=hero_body,
            equipment_body=equipment_body,
        )

    def _patch_local_role_base(self, role: Any, state: dict[str, Any]) -> bytes:
        return patch_role_base_from_state(
            bytes(role["role_base_blob"] or b""),
            state,
            uid=int(role["game_uid"]) if str(role["game_uid"]).isdigit() else None,
        )

    def _persist_captured_role_base(
        self,
        role_id: int,
        role: Any,
        frame: Frame,
        state: dict[str, Any],
    ) -> Any:
        role_base = get_bytes(frame.body, 3)
        if role_base is None:
            return role
        try:
            game_uid = int(role["game_uid"])
        except (TypeError, ValueError):
            game_uid = get_varint(role_base, 1)
        role_base = patch_varint(role_base, 1, game_uid)
        role_base = patch_varint(role_base, 7, int(state.get("coin", 0)))
        role_base = patch_role_base_diamond(role_base, int(state.get("diamond", role["diamond"])))
        exp = get_bytes(role_base, 9)
        if exp is not None:
            state["level"] = get_varint(exp, 1)
        return self.storage.update_game_role_progress(
            role_id,
            state=state,
            role_base_blob=role_base,
            diamond=int(state.get("diamond", role["diamond"])),
        )

    async def _send_gameplay_event(
        self,
        request: Frame,
        writer: asyncio.StreamWriter,
        role: Any,
        state: dict[str, Any],
        *,
        response_id: int,
        role_id: int | None = None,
    ) -> bool:
        event = self._gameplay_event(request)
        if not event:
            return False
        sent_response = False
        for captured in event:
            patched = self._patch_gameplay_frame(captured, role, state)
            if patched.msg_id == 76 and role_id is not None:
                role = self._persist_captured_role_base(role_id, role, patched, state)
            await self._send(writer, Frame(patched.body, patched.msg_id, request.seq, request.flag))
            sent_response = sent_response or patched.msg_id == response_id
        return sent_response

    async def _handle_gacha_list(self, frame: Frame, writer: asyncio.StreamWriter) -> None:
        event = self._gameplay_event(frame)
        if event:
            for captured in event:
                await self._send(writer, Frame(captured.body, captured.msg_id, frame.seq, frame.flag))
        else:
            await self._send(writer, Frame(encode_gacha_list_ack(), 30, frame.seq, frame.flag))
        logger.info("game gacha list accepted request_id=29 response_id=30")

    async def _handle_lineup(self, frame: Frame, writer: asyncio.StreamWriter, role_id: int) -> None:
        role = self.storage.get_game_role(role_id)
        if role is None:
            return
        state = self._role_state(role)
        lineup = get_bytes(frame.body, 2)
        lineup_values = get_repeated_varints(lineup or b"", 1)
        lineup_id = get_varint(frame.body, 1)
        lineups = dict(state.get("lineups") or {})
        by_id = dict(lineups.get("by_id") or {})
        if lineup_id:
            by_id[str(lineup_id)] = lineup_values
        patch: dict[str, Any] = {"lineups": {"by_id": by_id}}
        if frame.msg_id == 109:
            patch["lineups"]["normal"] = lineup_values
            patch["lineup"] = lineup_values
        else:
            patch["lineups"]["battle"] = lineup_values
        state = merge_role_state(state, patch)
        role = self.storage.merge_game_state(role_id, patch)
        state = self._role_state(role)
        response_id = 110 if frame.msg_id == 109 else 112
        if not await self._send_gameplay_event(frame, writer, role, state, response_id=response_id, role_id=role_id):
            await self._send(writer, Frame(b"", response_id, frame.seq, frame.flag))
        logger.info(
            "game lineup accepted role_id=%s request_id=%s response_id=%s lineup=%s",
            role_id,
            frame.msg_id,
            response_id,
            state.get("lineup", []),
        )

    async def _handle_gacha(self, frame: Frame, writer: asyncio.StreamWriter, role_id: int) -> None:
        request = decode_gacha_request(frame.body)
        role = self.storage.get_game_role(role_id)
        if role is None:
            return
        state = self._role_state(role)
        if int(request["gacha_id"]) != 2 or int(request["gacha_num"]) != 1:
            await self._send(writer, Frame(encode_gacha_ack(config_id=0, error=1002), 32, frame.seq, frame.flag))
            return

        op_key = operation_key("gacha", frame.body)
        receipt = get_operation(state, "gacha", op_key)
        if receipt is not None:
            result = dict(receipt.get("result") or {})
            hero_id = int(result.get("hero_id", 0) or 0)
            hero_level = int(result.get("hero_level", 1) or 1)
            await self._send(writer, Frame(encode_gacha_ack(config_id=hero_id), 32, frame.seq, frame.flag))
            await self._send(writer, Frame(encode_hero_change_ntf(hero_id, hero_level), 118, frame.seq, frame.flag))
            await self._send(writer, Frame(encode_gacha_open_ntf((3, 4, 7)), 398, frame.seq, frame.flag))
            logger.info("game gacha replayed idempotent role_id=%s operation=%s", role_id, op_key)
            return

        heroes = dict(state.get("heroes") or {})
        hero_id = 10002
        hero = dict(heroes.get(str(hero_id)) or {})
        hero.setdefault("id", hero_id)
        hero["level"] = max(1, int(hero.get("level", 1)))
        heroes[str(hero_id)] = hero
        gacha = dict(state.get("gacha") or {})
        history = list(gacha.get("history") or [])
        history.append({"pool_id": int(request["gacha_id"]), "quantity": int(request["gacha_num"]), "hero_id": hero_id})
        encyclopedia = dict(gacha.get("encyclopedia") or {})
        duplicate = str(hero_id) in encyclopedia
        encyclopedia[str(hero_id)] = True
        gacha["history"] = history
        gacha["encyclopedia"] = encyclopedia
        if duplicate:
            gacha["duplicate_count"] = int(gacha.get("duplicate_count", 0) or 0) + 1
        result = {"hero_id": hero_id, "hero_level": hero["level"], "duplicate": duplicate}
        state = record_operation(state, "gacha", op_key, result)
        patch = {
            "heroes": {str(hero_id): hero},
            "gacha": {
                "history": history,
                "encyclopedia": encyclopedia,
                "duplicate_count": int(gacha.get("duplicate_count", 0) or 0),
            },
            "operations": {"gacha": {op_key: state["operations"]["gacha"][op_key]}},
        }
        role = self.storage.merge_game_state(role_id, patch)
        state = self._role_state(role)
        if not await self._send_gameplay_event(frame, writer, role, state, response_id=32, role_id=role_id):
            await self._send(writer, Frame(encode_gacha_ack(config_id=hero_id), 32, frame.seq, frame.flag))
            await self._send(
                writer,
                Frame(encode_hero_change_ntf(hero_id, hero["level"]), 118, frame.seq, frame.flag),
            )
            await self._send(writer, Frame(encode_gacha_open_ntf((3, 4, 7)), 398, frame.seq, frame.flag))
        logger.info(
            "game gacha accepted role_id=%s gacha_id=%s quantity=%s hero_id=%s",
            role_id,
            request["gacha_id"],
            request["gacha_num"],
            hero_id,
        )

    async def _handle_hero_level_up(self, frame: Frame, writer: asyncio.StreamWriter, role_id: int) -> None:
        request = decode_hero_level_up_request(frame.body)
        role = self.storage.get_game_role(role_id)
        if role is None:
            return
        state = self._role_state(role)
        op_key = operation_key("hero_level_up", frame.body)
        receipt = get_operation(state, "hero_level_up", op_key)
        if receipt is not None:
            result = dict(receipt.get("result") or {})
            hero_id = int(result.get("hero_id", request["hero_id"]) or request["hero_id"])
            level = int(result.get("level", 1) or 1)
            await self._send(writer, Frame(b"", 94, frame.seq, frame.flag))
            await self._send(
                writer,
                Frame(
                    encode_role_info(
                        self._patch_local_role_base(role, state),
                        int(state.get("diamond", role["diamond"])),
                        int(state.get("coin", 0)),
                    ),
                    76,
                    frame.seq,
                    frame.flag,
                ),
            )
            await self._send(writer, Frame(encode_hero_change_ntf(hero_id, level), 118, frame.seq, frame.flag))
            logger.info("game hero level up replayed idempotent role_id=%s operation=%s", role_id, op_key)
            return
        heroes = dict(state.get("heroes") or {})
        hero_key = str(request["hero_id"])
        hero = dict(heroes.get(hero_key) or {"id": int(request["hero_id"]), "level": 1})
        hero["level"] = int(hero.get("level", 1)) + max(0, int(request["level_num"]))
        heroes[hero_key] = hero
        result = {"hero_id": int(request["hero_id"]), "level": hero["level"]}
        state = record_operation(state, "hero_level_up", op_key, result)
        patch = {
            "heroes": {hero_key: hero},
            "operations": {"hero_level_up": {op_key: state["operations"]["hero_level_up"][op_key]}},
        }
        role = self.storage.merge_game_state(role_id, patch)
        state = self._role_state(role)
        if not await self._send_gameplay_event(frame, writer, role, state, response_id=94, role_id=role_id):
            await self._send(writer, Frame(b"", 94, frame.seq, frame.flag))
            await self._send(
                writer,
                Frame(
                    encode_role_info(
                        self._patch_local_role_base(role, state),
                        int(state.get("diamond", role["diamond"])),
                        int(state.get("coin", 0)),
                    ),
                    76,
                    frame.seq,
                    frame.flag,
                ),
            )
            await self._send(writer, Frame(encode_hero_change_ntf(int(request["hero_id"]), hero["level"]), 118, frame.seq, frame.flag))
        logger.info(
            "game hero level up accepted role_id=%s hero_id=%s level_num=%s level=%s",
            role_id,
            request["hero_id"],
            request["level_num"],
            hero["level"],
        )

    async def _handle_risk_win(self, frame: Frame, writer: asyncio.StreamWriter, role_id: int) -> None:
        request = decode_risk_bat_win_request(frame.body)
        role = self.storage.get_game_role(role_id)
        if role is None:
            return
        state = self._role_state(role)
        op_key = operation_key("battle", frame.body)
        receipt = get_operation(state, "battle", op_key)
        if receipt is not None:
            result = dict(receipt.get("result") or {})
            settlement = encode_risk_bat_settlement(
                is_win=bool(result.get("is_win")),
                win_settlement=encode_win_settlement(
                    base_exp=int(result.get("base_exp", 0) or 0),
                    hero_exp=int(result.get("hero_exp", 0) or 0),
                    coin=int(result.get("coin_reward", 0) or 0),
                    diamond=int(result.get("diamond_reward", 0) or 0),
                    strength=int(result.get("strength", state.get("strength", 0)) or 0),
                ) if result.get("is_win") else None,
            )
            await self._send(writer, Frame(encode_risk_bat_win_ack(settlement=settlement), 144, frame.seq, frame.flag))
            logger.info("game risk win replayed idempotent role_id=%s operation=%s", role_id, op_key)
            return
        risk = dict(state.get("risk") or {})
        completed = dict(risk.get("completed") or {})
        level_id = int(request["level_id"])
        first_completion = str(level_id) not in completed
        rewards = {
            1001001: (300, 0, 39, 4),
            1001002: (320, 10, 38, -6),
            1001003: (340, 10, 55, 4),
            1001004: (360, 10, 33, -6),
            1001005: (380, 10, 57, 4),
            1001006: (400, 10, 200, -6),
        }
        coin_reward, diamond_reward, hero_exp, strength_delta = rewards.get(level_id, (0, 0, 0, 0))
        if first_completion and request["is_win"] and not request["is_quit"]:
            next_coin = int(state.get("coin", 0)) + coin_reward
            next_diamond = int(state.get("diamond", role["diamond"])) + diamond_reward
            next_strength = max(0, int(state.get("strength", 100)) + strength_delta)
            completed[str(level_id)] = {"star": int(request["star"]), "hero_exp": hero_exp}
            risk["current_level"] = level_id
            risk["completed"] = completed
            risk.setdefault("stars", {})[str(level_id)] = int(request["star"])
            state = merge_role_state(
                state,
                {
                    "coin": next_coin,
                    "diamond": next_diamond,
                    "strength": next_strength,
                    "risk": risk,
                },
            )
            result = {
                "level_id": level_id,
                "is_win": bool(request["is_win"]),
                "is_quit": bool(request["is_quit"]),
                "star": int(request["star"]),
                "base_exp": 0,
                "hero_exp": hero_exp,
                "coin_reward": coin_reward,
                "diamond_reward": diamond_reward,
                "strength": next_strength,
            }
            state = record_operation(state, "battle", op_key, result)
            role_base = self._patch_local_role_base(role, state)
            role = self.storage.merge_game_state(
                role_id,
                {
                    "coin": next_coin,
                    "diamond": next_diamond,
                    "strength": next_strength,
                    "risk": risk,
                    "operations": {"battle": {op_key: state["operations"]["battle"][op_key]}},
                },
                role_base_blob=role_base,
                diamond=next_diamond,
            )
        else:
            result = {
                "level_id": level_id,
                "is_win": bool(request["is_win"]),
                "is_quit": bool(request["is_quit"]),
                "star": int(request["star"]),
                "base_exp": 0,
                "hero_exp": 0,
                "coin_reward": 0,
                "diamond_reward": 0,
                "strength": int(state.get("strength", 0) or 0),
            }
            state = record_operation(state, "battle", op_key, result)
            role = self.storage.merge_game_state(
                role_id,
                {"risk": risk, "operations": {"battle": {op_key: state["operations"]["battle"][op_key]}}},
            )
        state = self._role_state(role)

        sent = await self._send_gameplay_event(frame, writer, role, state, response_id=144, role_id=role_id)
        if not sent:
            if first_completion and request["is_win"] and not request["is_quit"]:
                await self._send(
                    writer,
                    Frame(
                        encode_role_info(
                            self._patch_local_role_base(role, state),
                            int(state.get("diamond", role["diamond"])),
                            int(state.get("coin", 0)),
                        ),
                        76,
                        frame.seq,
                        frame.flag,
                    ),
                )
                await self._send(
                    writer,
                    Frame(encode_risk_battle_ntf(level_id, level_id), 149, frame.seq, frame.flag),
                )
            settlement = encode_risk_bat_settlement(
                is_win=bool(request["is_win"]),
                win_settlement=encode_win_settlement(
                    base_exp=0,
                    hero_exp=hero_exp if first_completion else 0,
                    coin=coin_reward if first_completion else 0,
                    diamond=diamond_reward if first_completion else 0,
                    strength=int(state.get("strength", 0) or 0),
                ) if request["is_win"] else None,
            )
            await self._send(
                writer,
                Frame(encode_risk_bat_win_ack(settlement=settlement), 144, frame.seq, frame.flag),
            )
        logger.info(
            "game risk win accepted role_id=%s level_id=%s win=%s star=%s first_completion=%s",
            role_id,
            level_id,
            request["is_win"],
            request["star"],
            first_completion,
        )

    async def _handle_guide_save(
        self,
        frame: Frame,
        writer: asyncio.StreamWriter,
        role_id: int,
    ) -> None:
        role = self.storage.get_game_role(role_id)
        if role is None:
            return
        state = self._role_state(role)
        record = decode_string_map_field(frame.body, 1)
        guide, completion_key = _apply_guide_save(dict(state.get("guide") or {}), record)
        role = self.storage.merge_game_state(role_id, {"story": {"guide": guide}})
        state = self._role_state(role)
        response = next(
            (item for item in self._gameplay_event(frame) if item.msg_id == 60),
            None,
        )
        await self._send(
            writer,
            Frame(response.body if response is not None else b"", 60, frame.seq, frame.flag),
        )
        logger.info(
            "game guide saved role_id=%s segment_id=%s step_id=%s step_status=%s "
            "completion_key=%s entries=%s role_version=%s",
            role_id,
            record.get("segment_id", ""),
            record.get("step_id", ""),
            record.get("step_status", ""),
            completion_key or "-",
            len(guide),
            role["role_version"],
        )

    async def _handle_guide_get(
        self,
        frame: Frame,
        writer: asyncio.StreamWriter,
        role_id: int,
    ) -> None:
        role = self.storage.get_game_role(role_id)
        if role is None:
            return
        state = self._role_state(role)
        guide = {str(key): str(value) for key, value in dict(state.get("guide") or {}).items()}
        requested_key = get_string(frame.body, 1)
        if requested_key:
            guide = {requested_key: guide[requested_key]} if requested_key in guide else {}
        # SCGuideGetAck.Guide is a map field numbered 2. Encode each map
        # entry directly under field 2; wrapping a field-1 map in bytes makes
        # the protobuf valid on the wire but unreadable by the APK parser.
        body = encode_string_map_field(2, guide)
        await self._send(writer, Frame(body, 62, frame.seq, frame.flag))
        logger.info(
            "game guide loaded role_id=%s requested_key=%s entries=%s",
            role_id,
            requested_key,
            len(guide),
        )

    async def _handle_simple_gameplay_request(
        self,
        frame: Frame,
        writer: asyncio.StreamWriter,
        role_id: int,
        response_id: int,
    ) -> None:
        role = self.storage.get_game_role(role_id)
        if role is None:
            return
        state = self._role_state(role)
        patch: dict[str, Any] | None = None
        if frame.msg_id == 329:
            style = get_varint(frame.body, 1)
            profile_id = get_varint(frame.body, 2)
            preferences = dict(state.get("preferences") or {})
            preferences[str(style)] = profile_id
            patch = {"preferences": preferences}
        elif frame.msg_id == 370:
            key = f"{get_varint(frame.body, 1)}:{get_varint(frame.body, 2)}"
            read_data = dict(state.get("read_data") or {})
            read_data[key] = True
            patch = {"story": {"read": read_data}}
        elif frame.msg_id == 374:
            conditions = dict(state.get("conditions") or {})
            conditions[frame.body.hex()] = True
            patch = {"story": {"conditions": conditions}}
        elif frame.msg_id == 327:
            key = get_string(frame.body, 1)
            transmit = dict(state.get("transmit") or {})
            transmit[key] = get_string(frame.body, 3)
            patch = {"story": {"transmit": transmit}}
        if patch:
            role = self.storage.merge_game_state(role_id, patch)
            state = self._role_state(role)
        event = self._gameplay_event(frame)
        if event:
            for captured in event:
                await self._send(writer, Frame(captured.body, captured.msg_id, frame.seq, frame.flag))
        else:
            fallback = encode_string_field(2, get_string(frame.body, 1)) if frame.msg_id == 327 else b""
            await self._send(writer, Frame(fallback, response_id, frame.seq, frame.flag))

    async def _handle_login(self, frame: Frame, writer: asyncio.StreamWriter) -> int | None:
        request = decode_login_request(frame.body)
        if self.trace:
            digest = hashlib.sha256(frame.body).hexdigest()[:12]
            logger.info(
                "game frame direction=in peer=%s msg_id=%s seq=%s flag=%s body_len=%s body_sha256=%s",
                writer.get_extra_info("peername"),
                frame.msg_id,
                frame.seq,
                frame.flag,
                len(frame.body),
                digest,
            )
        logger.info(
            "game login request server_id=%s select_zone=%s open_id=%s user_id=%s account=%s auth_type=%s token_fp=%s",
            self.server_id,
            request.get("select_zone", 0),
            request.get("open_id", ""),
            request.get("user_id", ""),
            request.get("account", ""),
            request.get("auth_type", ""),
            _token_fingerprint(str(request.get("auth_token") or "")),
        )
        if request["select_zone"] and int(request["select_zone"]) != self.server_id:
            await self._reject_login(writer, frame, request, reason="server_mismatch", match_key="server_id")
            return None

        fixture, reason, match_key = self._fixture_for_login(request)
        if fixture is None:
            await self._reject_login(writer, frame, request, reason=reason, match_key=match_key)
            return None

        fixture_sdk_user_id = int(fixture["sdk_user_id"])
        if self.storage.get_user_by_id(fixture_sdk_user_id) is None:
            await self._reject_login(
                writer,
                frame,
                request,
                reason="sdk_user_missing",
                match_key=match_key,
                fixture_path=str(fixture.get("fixture_path", "")),
            )
            return None

        session = self.storage.get_session(str(request.get("auth_token") or ""))
        if session is None:
            await self._reject_login(
                writer,
                frame,
                request,
                reason="token_invalid",
                match_key=match_key,
                fixture_path=str(fixture.get("fixture_path", "")),
            )
            return None
        sdk_user_id = int(session[0]["id"])
        if sdk_user_id != fixture_sdk_user_id:
            await self._reject_login(
                writer,
                frame,
                request,
                reason="identity_mismatch",
                match_key=match_key,
                sdk_user_id=sdk_user_id,
                fixture_path=str(fixture.get("fixture_path", "")),
            )
            return None

        try:
            frames = self._fixture_frames(fixture)
        except (KeyError, TypeError, ProtoError):
            await self._reject_login(
                writer,
                frame,
                request,
                reason="startup_invalid",
                match_key=match_key,
                sdk_user_id=sdk_user_id,
                fixture_path=str(fixture.get("fixture_path", "")),
            )
            return None
        if not any(item.msg_id == 25 for item in frames):
            await self._reject_login(
                writer,
                frame,
                request,
                reason="startup_invalid",
                match_key=match_key,
                sdk_user_id=sdk_user_id,
                fixture_path=str(fixture.get("fixture_path", "")),
            )
            return None
        try:
            role_base, role_bag = extract_startup_parts(frames)
        except ProtoError:
            await self._reject_login(
                writer,
                frame,
                request,
                reason="startup_invalid",
                match_key=match_key,
                sdk_user_id=sdk_user_id,
                fixture_path=str(fixture.get("fixture_path", "")),
            )
            return None
        login_open_id = str(fixture.get("login_open_id", "") or request.get("open_id") or "")
        login_user_id = str(fixture.get("login_user_id", "") or request.get("user_id") or "")
        existing_role = self.storage.get_game_role_by_identity(
            self.server_id,
            login_open_id=login_open_id,
            login_user_id=login_user_id,
        )
        startup_json = json.dumps(fixture["messages"], ensure_ascii=False, separators=(",", ":"))
        if existing_role is not None:
            existing_role_base = bytes(existing_role["role_base_blob"] or b"")
            existing_role_bag = bytes(existing_role["role_bag_blob"] or b"")
            if existing_role_base:
                role_base = existing_role_base
            if existing_role_bag:
                role_bag = existing_role_bag
            if str(existing_role["startup_json"] or ""):
                startup_json = str(existing_role["startup_json"])
        role = self.storage.ensure_game_role(
            sdk_user_id=sdk_user_id,
            server_id=self.server_id,
            login_open_id=login_open_id,
            login_user_id=login_user_id,
            game_uid=str(fixture["game_uid"]),
            fixture_name=str(fixture.get("fixture_name", "startup")),
            startup_json=startup_json,
            role_base_blob=role_base,
            role_bag_blob=role_bag,
            initial_diamond=int(fixture.get("initial_diamond", 0)),
            preserve_existing_state=True,
        )
        # Migrate an empty/legacy JSON state once at login.  The fixture is
        # used only to seed confirmed fields; subsequent startup data comes
        # from this persisted model.
        try:
            raw_state = json.loads(str(role["game_state_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            raw_state = {}
        state = self._role_state(role)
        required_state_sections = {
            "role_base",
            "role_bag",
            "equipment",
            "heroes",
            "lineups",
            "risk_battle",
            "strength_state",
            "tasks",
            "story",
            "gacha",
            "social",
            "operations",
        }
        if (
            not isinstance(raw_state, dict)
            or raw_state.get("schema_version") != 1
            or not required_state_sections.issubset(raw_state)
        ):
            role = self.storage.update_game_state(
                int(role["id"]),
                state,
                increment_version=False,
            )
        handshake = next((item for item in frames if item.msg_id == 7), None)
        if handshake is not None:
            await self._send(
                writer,
                Frame(handshake.body, 7, handshake.seq, handshake.flag),
            )
        login_ack = next((item for item in frames if item.msg_id == 4), None)
        ack_body = login_ack.body if login_ack is not None else encode_login_ack(client_id=int(role["id"]))
        await self._send(writer, Frame(ack_body, 4, frame.seq, login_ack.flag if login_ack else 0))
        await self._send_startup(writer, role)
        self.storage.mark_role_events_delivered(int(role["id"]), int(role["role_version"]))
        self.sessions[int(role["id"])] = writer
        logger.info(
            "game login accepted role_id=%s sdk_user_id=%s server_id=%s game_uid=%s open_id=%s user_id=%s startup_messages=%s",
            role["id"],
            role["sdk_user_id"],
            role["server_id"],
            role["game_uid"],
            role["login_open_id"],
            role["login_user_id"],
            len(self._capture_startup_frames(frames)),
        )
        return int(role["id"])

    async def _handle_replay_request(self, frame: Frame, writer: asyncio.StreamWriter, role_id: int) -> None:
        role = self.storage.get_game_role(role_id)
        if role is None:
            logger.warning("game init request ignored role_missing role_id=%s msg_id=%s", role_id, frame.msg_id)
            return
        response = self._response_for_request(frame, role)
        if response is None:
            logger.warning(
                "game init request unsupported role_id=%s request_id=%s body_len=%s",
                role_id,
                frame.msg_id,
                len(frame.body),
            )
            return
        await self._send(writer, response)
        logger.info(
            "game init response role_id=%s request_id=%s response_id=%s request_body_len=%s response_body_len=%s",
            role_id,
            frame.msg_id,
            response.msg_id,
            len(frame.body),
            len(response.body),
        )

    async def _handle_order(self, frame: Frame, writer: asyncio.StreamWriter, role_id: int) -> None:
        request = decode_order_request(frame.body)
        role = self.storage.get_game_role(role_id)
        if role is None or int(request["server_id"]) != int(role["server_id"]):
            await self._send(writer, Frame(encode_order_ack(0, "", 0, 0, 0, 0, error=1002), 378, frame.seq, 0))
            return
        product = resolve_product_by_goods_id(request["goods_id"])
        if product is None or request["quantity"] != 1:
            await self._send(writer, Frame(encode_order_ack(0, "", request["shop_id"], request["goods_id"], request["quantity"], 0, error=1003), 378, frame.seq, 0))
            return
        owner_key = str(request["owner_key"] or "")
        allowed_owner_keys = {
            str(role["login_open_id"]),
            str(role["login_user_id"]),
            str(role["sdk_user_id"]),
            str(role["game_uid"]),
        }
        allowed_owner_keys.discard("")
        if owner_key and owner_key not in allowed_owner_keys:
            await self._send(writer, Frame(encode_order_ack(0, "", request["shop_id"], request["goods_id"], request["quantity"], 0, error=1004), 378, frame.seq, 0))
            return
        order_no = time.time_ns() % 10**18
        order, _ = self.storage.create_game_order(
            role_id=role_id,
            game_order_no=str(order_no),
            server_id=int(request["server_id"]),
            shop_id=int(request["shop_id"]),
            goods_id=int(request["goods_id"]),
            quantity=int(request["quantity"]),
            order_price=product.price,
            product_id=product.product_id,
            notify_url=self.notify_url,
        )
        await self._send(
            writer,
            Frame(
                encode_order_ack(
                    int(order["game_order_no"]),
                    str(order["notify_url"]),
                    int(order["shop_id"]),
                    int(order["goods_id"]),
                    int(order["quantity"]),
                    int(order["order_price"]),
                ),
                378,
                frame.seq,
                0,
            ),
        )
        logger.info("game order created role_id=%s game_order_id=%s game_order_no=%s", role_id, order["id"], order["game_order_no"])

    async def _event_loop(self) -> None:
        while True:
            for event in self.storage.list_pending_game_events():
                writer = self.sessions.get(int(event["role_id"]))
                if writer is None or writer.is_closing():
                    continue
                try:
                    body = encode_role_info(bytes(event["role_base_blob"]), int(event["diamond"]))
                    await self._send(writer, Frame(body, 76, 0, 0))
                except asyncio.CancelledError:
                    raise
                except (ConnectionError, BrokenPipeError):
                    continue
                except Exception:
                    logger.exception("game event delivery failed event_id=%s", event["id"])
                    continue
                self.storage.mark_game_event_delivered(int(event["id"]))
            await asyncio.sleep(self.poll_interval)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        role_id: int | None = None
        peer = writer.get_extra_info("peername")
        try:
            while True:
                frame = await _read_frame(reader)
                if self.trace and frame.msg_id != 3:
                    digest = hashlib.sha256(frame.body).hexdigest()[:12]
                    logger.info(
                        "game frame direction=in peer=%s msg_id=%s seq=%s flag=%s body_len=%s body_sha256=%s",
                        peer,
                        frame.msg_id,
                        frame.seq,
                        frame.flag,
                        len(frame.body),
                        digest,
                    )
                if frame.msg_id == 3:
                    role_id = await self._handle_login(frame, writer)
                    if role_id is None:
                        break
                elif frame.msg_id == 377:
                    if role_id is None:
                        break
                    await self._handle_order(frame, writer, role_id)
                elif frame.msg_id == 21:
                    if role_id is None:
                        break
                    await self._handle_change_nickname(frame, writer, role_id)
                elif frame.msg_id == 109:
                    if role_id is None:
                        break
                    await self._handle_lineup(frame, writer, role_id)
                elif frame.msg_id == 111:
                    if role_id is None:
                        break
                    await self._handle_lineup(frame, writer, role_id)
                elif frame.msg_id == 29:
                    if role_id is None:
                        break
                    await self._handle_gacha_list(frame, writer)
                elif frame.msg_id == 31:
                    if role_id is None:
                        break
                    await self._handle_gacha(frame, writer, role_id)
                elif frame.msg_id == 63:
                    if role_id is None:
                        break
                    event = self._gameplay_event(frame)
                    if event:
                        for captured in event:
                            await self._send(writer, Frame(captured.body, captured.msg_id, frame.seq, frame.flag))
                    else:
                        await self._send(writer, Frame(encode_varint_field(3, 28800), 64, frame.seq, frame.flag))
                elif frame.msg_id == 93:
                    if role_id is None:
                        break
                    await self._handle_hero_level_up(frame, writer, role_id)
                elif frame.msg_id == 143:
                    if role_id is None:
                        break
                    await self._handle_risk_win(frame, writer, role_id)
                elif frame.msg_id in {24152, 24183}:
                    if role_id is None:
                        break
                    response_id = 24153 if frame.msg_id == 24152 else 24184
                    await self._handle_simple_gameplay_request(frame, writer, role_id, response_id)
                elif frame.msg_id == 329:
                    if role_id is None:
                        break
                    await self._handle_simple_gameplay_request(frame, writer, role_id, 330)
                elif frame.msg_id == 327:
                    if role_id is None:
                        break
                    await self._handle_simple_gameplay_request(frame, writer, role_id, 328)
                elif frame.msg_id in {370, 374}:
                    if role_id is None:
                        break
                    await self._handle_simple_gameplay_request(
                        frame,
                        writer,
                        role_id,
                        371 if frame.msg_id == 370 else 375,
                    )
                elif frame.msg_id == 59:
                    if role_id is None:
                        break
                    await self._handle_guide_save(frame, writer, role_id)
                elif frame.msg_id == 61:
                    if role_id is None:
                        break
                    await self._handle_guide_get(frame, writer, role_id)
                elif frame.msg_id in {141, 153}:
                    if role_id is None:
                        break
                    response_id = 142 if frame.msg_id == 141 else 154
                    level_id = get_varint(frame.body, 1)
                    state_role = self.storage.get_game_role(role_id)
                    event_sent = False
                    if state_role is not None:
                        if frame.msg_id == 141:
                            state = self._role_state(state_role)
                            risk = dict(state.get("risk") or {})
                            sessions = dict(risk.get("active_sessions") or {})
                            sessions[str(level_id)] = {
                                "level_id": level_id,
                                "request_sha256": hashlib.sha256(frame.body).hexdigest(),
                                "started_at": int(time.time()),
                            }
                            risk["active_sessions"] = sessions
                            state_role = self.storage.merge_game_state(role_id, {"risk": risk})
                        event_sent = await self._send_gameplay_event(
                            frame,
                            writer,
                            state_role,
                            self._role_state(state_role),
                            response_id=response_id,
                            role_id=role_id,
                        )
                    if not event_sent:
                        await self._send(writer, Frame(b"", response_id, frame.seq, frame.flag))
                        if frame.msg_id == 141:
                            await self._send(
                                writer,
                                Frame(encode_risk_battle_ntf(level_id), 149, frame.seq, frame.flag),
                            )
                    logger.info(
                        "game risk start accepted role_id=%s request_id=%s response_id=%s "
                        "level_id=%s body_len=%s",
                        role_id,
                        frame.msg_id,
                        response_id,
                        level_id,
                        len(frame.body),
                    )
                elif frame.msg_id in REPLAY_REQUEST_RESPONSE_IDS:
                    if role_id is None:
                        break
                    await self._handle_replay_request(frame, writer, role_id)
                else:
                    logger.info(
                        "game request ignored role_id=%s msg_id=%s body_len=%s",
                        role_id or 0,
                        frame.msg_id,
                        len(frame.body),
                    )
        except asyncio.IncompleteReadError:
            pass
        except (ConnectionError, BrokenPipeError):
            pass
        except ProtoError as exc:
            logger.warning("game connection rejected peer=%s reason=%s", peer, exc)
        except Exception:
            logger.exception("game connection failed peer=%s", peer)
        finally:
            if role_id is not None and self.sessions.get(role_id) is writer:
                self.sessions.pop(role_id, None)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, asyncio.CancelledError):
                pass

    async def start(self) -> None:
        self.storage.initialize()
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self._event_task = asyncio.create_task(self._event_loop())
        addresses = ", ".join(str(sock.getsockname()) for sock in self._server.sockets or [])
        if self.startup_template is not None:
            logger.info(
                "game startup template path=%s frames=%s",
                self.startup_template,
                len(self._startup_template_frames()) if self.startup_template.exists() else 0,
            )
        if not self.fixture_dir.exists():
            logger.warning("fixture inventory count=0 fixture_dir=%s failure_reason=fixture_dir_missing", self.fixture_dir)
        else:
            fixtures = self._fixtures()
            logger.info(
                "fixture inventory count=%s fixture_dir=%s entries=%s",
                len(fixtures),
                self.fixture_dir,
                [
                    {
                        "server_id": item["server_id"],
                        "open_id": item.get("login_open_id", ""),
                        "user_id": item.get("login_user_id", ""),
                        "game_uid": item["game_uid"],
                    }
                    for item in fixtures
                ],
            )
        logger.info(
            "game TCP server started addresses=%s fixture_dir=%s trace=%s",
            addresses,
            self.fixture_dir,
            self.trace,
        )
        logger.info(
            "game init capture path=%s records=%s response_templates=%s",
            self.response_capture or "-",
            len(self._capture_records()),
            len(self._response_templates()[0]),
        )
        logger.info(
            "gameplay capture path=%s records=%s",
            self.gameplay_capture or "-",
            len(self._gameplay_records()),
        )

    async def serve_forever(self) -> None:
        await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._event_task is not None:
            self._event_task.cancel()
            await asyncio.gather(self._event_task, return_exceptions=True)
            self._event_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


def _configure_logging(settings: Settings) -> None:
    settings.logging.data_dir.mkdir(parents=True, exist_ok=True)
    logger.setLevel(getattr(logging, settings.logging.level.upper(), logging.INFO))
    logger.propagate = False
    managed_handlers = [handler for handler in logger.handlers if getattr(handler, "_apk_sdk_managed", False)]
    expected_file = str(settings.logging.data_dir / settings.logging.game_tcp_log)
    has_expected_file = any(getattr(handler, "_apk_sdk_path", "") == expected_file for handler in managed_handlers)
    has_console = any(
        isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
        for handler in managed_handlers
    )
    if not has_expected_file or has_console != settings.logging.console:
        for handler in managed_handlers:
            logger.removeHandler(handler)
            handler.close()
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        file_handler = logging.FileHandler(settings.logging.data_dir / settings.logging.game_tcp_log, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler._apk_sdk_managed = True
        file_handler._apk_sdk_path = expected_file
        logger.addHandler(file_handler)
        if settings.logging.console:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            console_handler._apk_sdk_managed = True
            logger.addHandler(console_handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the standalone local game TCP server")
    parser.add_argument("--config", help="path to a TOML configuration file")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--server-id", type=int)
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--startup-template", type=Path, help="static legacy startup frame template JSON")
    parser.add_argument(
        "--response-capture",
        type=Path,
    )
    parser.add_argument(
        "--gameplay-capture",
        type=Path,
    )
    parser.add_argument("--poll-interval", type=float)
    parser.add_argument("--trace", action="store_true", default=None, help="log frame metadata and body digests")
    args = parser.parse_args()
    overrides: dict[str, Any] = {}
    for argument, config_key in (
        ("host", "game.tcp_host"),
        ("port", "game.tcp_port"),
        ("server_id", "game.server_id"),
        ("fixture_dir", "game.fixture_dir"),
          ("startup_template", "game.startup_template"),
        ("response_capture", "game.init_capture"),
        ("gameplay_capture", "game.gameplay_capture"),
        ("poll_interval", "game.poll_interval"),
        ("trace", "game.trace"),
    ):
        value = getattr(args, argument)
        if value is not None:
            overrides[config_key] = value
    try:
        settings = load_settings(args.config, overrides=overrides)
    except ConfigError as exc:
        parser.error(str(exc))
    _configure_logging(settings)
    service = GameTcpServer(settings=settings)
    try:
        asyncio.run(service.serve_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
