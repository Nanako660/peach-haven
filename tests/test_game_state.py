from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path

from server.game_proto import (
    Frame,
    encode_bytes_field,
    encode_frame,
    encode_login_ack,
    encode_role_bag,
    encode_startup_hero_ntf,
    encode_string_field,
    encode_varint_field,
    extract_role_base,
    decode_role_bag,
)
from server.game_state import (
    apply_item_delta,
    get_operation,
    merge_role_state,
    normalize_role_state,
    operation_key,
    record_operation,
)
from server.game_tcp import GameTcpServer
from server.storage import Storage


def _fixture_frame(frame: Frame) -> dict[str, object]:
    return {
        "msg_id": frame.msg_id,
        "seq": frame.seq,
        "flag": frame.flag,
        "body_b64": base64.b64encode(frame.body).decode("ascii"),
    }


def _write_fixture(path: Path, sdk_user_id: int) -> None:
    role_base = (
        encode_varint_field(1, 123456789)
        + encode_string_field(2, "State Role")
        + encode_varint_field(7, 1000)
        + encode_varint_field(8, 20)
        + encode_bytes_field(9, encode_varint_field(1, 1))
    )
    hero_body = encode_startup_hero_ntf(
        {"10001": {"id": 10001, "level": 1, "stage": 1, "star": 1}},
        {"1": [10001, 0, 0]},
        1,
    )
    frames = [
        Frame(encode_login_ack(client_id=1), 4, 0, 0),
        Frame(encode_varint_field(1, 100) + encode_bytes_field(4, role_base) + encode_bytes_field(5, b""), 25, 0, 0),
        Frame(encode_bytes_field(1, encode_varint_field(1, 1)), 26, 0, 0),
        Frame(hero_body, 27, 0, 0),
        Frame(b"", 28, 0, 0),
    ]
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "server_id": 4,
                "sdk_user_id": sdk_user_id,
                "login_open_id": "1",
                "login_user_id": "",
                "game_uid": "123456789",
                "fixture_name": "state-test",
                "messages": [_fixture_frame(frame) for frame in frames],
            }
        ),
        encoding="utf-8",
    )


async def _read_frame(reader: asyncio.StreamReader) -> Frame:
    header = await reader.readexactly(10)
    body_length = int.from_bytes(header[:2], "big")
    body = await reader.readexactly(body_length)
    from server.game_proto import decode_frame

    return decode_frame(header + body)


class GameStateModelTests(unittest.TestCase):
    def test_legacy_state_migrates_to_schema_and_field_merge_is_narrow(self) -> None:
        role_base = (
            encode_varint_field(1, 123)
            + encode_string_field(2, "Role")
            + encode_varint_field(7, 100)
            + encode_varint_field(8, 9)
            + encode_bytes_field(9, encode_varint_field(1, 3))
        )
        state = normalize_role_state(
            {"coin": 250, "guide": {"guide_first_battle": "1"}},
            role_base,
        )
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["role_base"]["nickname"], "Role")
        self.assertEqual(state["role_base"]["coin"], 250)
        self.assertEqual(state["role_base"]["level"], 3)
        self.assertEqual(state["story"]["guide"]["guide_first_battle"], "1")

        merged = merge_role_state(
            state,
            {
                "role_base": {"diamond": 20},
                "heroes": {"10001": {"id": 10001, "level": 2}},
            },
        )
        self.assertEqual(merged["role_base"]["coin"], 250)
        self.assertEqual(merged["role_base"]["diamond"], 20)
        self.assertEqual(merged["heroes"]["10001"]["level"], 2)
        self.assertEqual(merged["story"]["guide"]["guide_first_battle"], "1")

    def test_bag_delta_and_wire_round_trip_define_add_update_delete(self) -> None:
        state = normalize_role_state({}, encode_varint_field(1, 123))
        apply_item_delta(
            state,
            [{"id": 10, "config_id": 4001, "quantity": 3, "quality": 2}],
        )
        apply_item_delta(state, [{"id": 10, "quantity": 5}])
        self.assertEqual(state["role_bag"]["items"]["10"]["quantity"], 5)
        apply_item_delta(state, [{"id": 10, "quantity": 0}])
        self.assertNotIn("10", state["role_bag"]["items"])

        state["role_bag"]["items"]["11"] = {
            "id": 11,
            "config_id": 4002,
            "quantity": 2,
            "timestamp": 7,
        }
        wire = encode_role_bag(state["role_bag"])
        decoded = decode_role_bag(wire)
        self.assertEqual(decoded["items"]["11"]["config_id"], 4002)
        self.assertEqual(decoded["items"]["11"]["quantity"], 2)

    def test_operation_receipt_is_persistent_and_bounded_by_namespace(self) -> None:
        state = normalize_role_state({}, encode_varint_field(1, 123))
        key = operation_key("gacha", b"same-request")
        state = record_operation(state, "gacha", key, {"hero_id": 10002})
        self.assertEqual(get_operation(state, "gacha", key)["result"]["hero_id"], 10002)
        self.assertIsNone(get_operation(state, "battle", key))

    def test_startup_hero_body_seeds_persisted_heroes_and_lineup(self) -> None:
        role_base = encode_varint_field(1, 123)
        hero_body = encode_startup_hero_ntf(
            {"10001": {"id": 10001, "level": 2}},
            {"1": [10001, 0, 0]},
            1,
        )
        state = normalize_role_state({}, role_base, hero_body=hero_body)
        self.assertEqual(state["heroes"]["10001"]["level"], 2)
        self.assertEqual(state["lineups"]["by_id"]["1"], [10001, 0, 0])
        self.assertEqual(state["lineups"]["normal"], [10001, 0, 0])


class GameStateIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_gacha_and_level_up_repeated_bodies_do_not_duplicate_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("state-idempotency", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _write_fixture(fixture_dir / "role.json", int(user["id"]))
            service = GameTcpServer(
                storage=storage,
                host="127.0.0.1",
                port=0,
                server_id=4,
                fixture_dir=fixture_dir,
            )
            await service.start()
            assert service._server is not None
            port = service._server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                token = storage.issue_token(int(user["id"]), "state-idempotency-device")
                login = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login, 3, 1, 0)))
                await writer.drain()
                for _ in range(5):
                    await asyncio.wait_for(_read_frame(reader), 1)

                gacha = encode_varint_field(1, 2) + encode_varint_field(2, 1)
                for seq in (2, 3):
                    writer.write(encode_frame(Frame(gacha, 31, seq, 0)))
                    await writer.drain()
                    self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 32)
                    self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 118)
                    self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 398)

                level_up = encode_varint_field(1, 10002) + encode_varint_field(2, 1)
                for seq in (4, 5):
                    writer.write(encode_frame(Frame(level_up, 93, seq, 0)))
                    await writer.drain()
                    self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 94)
                    self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 76)
                    self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 118)

                role = storage.get_game_role_by_identity(4, login_open_id="1")
                assert role is not None
                state = storage.get_game_state(int(role["id"]))
                self.assertEqual(state["heroes"]["10002"]["level"], 2)
                self.assertEqual(len(state["gacha"]["history"]), 1)
                self.assertEqual(len(state["operations"]["gacha"]), 1)
                self.assertEqual(len(state["operations"]["hero_level_up"]), 1)
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()
