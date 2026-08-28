"""Import and validate local game TCP startup fixtures.

The tool consumes a JSON frame dump.  A packet capture can be converted to
the same format without putting capture tooling or network access in the game
server process.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from .game_proto import Frame, ProtoError, extract_startup_parts, get_varint


REQUIRED_MESSAGE_IDS = {4, 25, 26, 27, 28}
REPLAY_MESSAGE_IDS = REQUIRED_MESSAGE_IDS | {7}


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtoError(f"cannot read fixture: {path}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
        raise ProtoError("fixture must contain a messages list")
    return validate_fixture(value)


def validate_fixture(value: dict[str, Any]) -> dict[str, Any]:
    messages = [Frame.from_json(item) for item in value["messages"]]
    message_ids = {frame.msg_id for frame in messages}
    missing = REQUIRED_MESSAGE_IDS - message_ids
    if missing:
        raise ProtoError(f"fixture is missing message ids: {sorted(missing)}")
    positions = {msg_id: next(index for index, frame in enumerate(messages) if frame.msg_id == msg_id) for msg_id in REQUIRED_MESSAGE_IDS}
    if [positions[msg_id] for msg_id in (4, 25, 26, 27, 28)] != sorted(
        positions[msg_id] for msg_id in (4, 25, 26, 27, 28)
    ):
        raise ProtoError("fixture login/startup messages are out of order")
    handshake_positions = [index for index, frame in enumerate(messages) if frame.msg_id == 7]
    if handshake_positions and max(handshake_positions) > positions[4]:
        raise ProtoError("fixture handshake message must precede login ack")
    role_base, role_bag = extract_startup_parts(messages)
    # Confirmed by static analysis: RoleBase.Uid is an unsigned integer field.
    role_uid_value = get_varint(role_base, 1)
    if role_uid_value <= 0:
        raise ProtoError("RoleBase.Uid is missing from fixture")
    if role_bag is None:
        raise ProtoError("startup message has no RoleBag field")
    try:
        server_id = int(value.get("server_id", 4))
        sdk_user_id = int(value.get("sdk_user_id", 0))
        version = int(value.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise ProtoError("fixture metadata contains an invalid number") from exc
    login_open_id = str(value.get("login_open_id", ""))
    login_user_id = str(value.get("login_user_id", ""))
    if sdk_user_id <= 0 or (not login_open_id and not login_user_id):
        raise ProtoError("fixture requires positive sdk_user_id and login_open_id or login_user_id")
    return {
        "version": version,
        "server_id": server_id,
        "login_open_id": login_open_id,
        "login_user_id": login_user_id,
        "sdk_user_id": sdk_user_id,
        "game_uid": str(value.get("game_uid") or role_uid_value),
        "fixture_name": str(value.get("fixture_name", "startup")),
        "messages": [frame.to_json() for frame in messages],
        "role_uid": str(role_uid_value),
        "initial_diamond": get_varint(role_base, 8),
    }


def fixture_from_capture(
    path: Path,
    *,
    server_id: int,
    sdk_user_id: int,
    login_open_id: str = "",
    login_user_id: str = "",
    game_uid: str = "",
    fixture_name: str = "capture-startup",
) -> dict[str, Any]:
    """Convert analyzer output into a validated fixture without retaining c2s login data."""
    try:
        capture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtoError(f"cannot read capture: {path}") from exc
    if not isinstance(capture, dict) or not isinstance(capture.get("frames"), list):
        raise ProtoError("capture must contain a frames list")

    source_frames = [
        item
        for item in capture["frames"]
        if isinstance(item, dict) and item.get("direction") == "s2c"
    ]
    ack_index = next(
        (index for index, item in enumerate(source_frames) if int(item.get("msg_id", -1)) == 4),
        None,
    )
    if ack_index is None:
        raise ProtoError("capture has no server login ack")
    start_index = ack_index
    while start_index > 0 and int(source_frames[start_index - 1].get("msg_id", -1)) == 7:
        start_index -= 1

    relevant: list[dict[str, Any]] = []
    finished = False
    for item in source_frames[start_index:]:
        msg_id = int(item.get("msg_id", -1))
        if msg_id not in REPLAY_MESSAGE_IDS:
            continue
        if "body_b64" not in item:
            raise ProtoError(f"capture frame {msg_id} has no body_b64")
        try:
            body = base64.b64decode(str(item["body_b64"]), validate=True)
            frame = Frame(
                body=body,
                msg_id=msg_id,
                seq=int(item.get("seq", 0)),
                flag=int(item.get("flag", 0)),
            )
        except (TypeError, ValueError, base64.binascii.Error) as exc:
            raise ProtoError(f"capture frame {msg_id} is invalid") from exc
        if "body_len" in item and int(item["body_len"]) != len(body):
            raise ProtoError(f"capture frame {msg_id} body length mismatch")
        relevant.append(frame.to_json())
        if msg_id == 28:
            finished = True
            break
    if not finished:
        raise ProtoError("capture has no complete 4/25/26/27/28 startup sequence")

    fixture = {
        "version": 1,
        "server_id": server_id,
        "sdk_user_id": sdk_user_id,
        "login_open_id": str(login_open_id or ""),
        "login_user_id": str(login_user_id or ""),
        "game_uid": str(game_uid or ""),
        "fixture_name": fixture_name,
        "messages": relevant,
    }
    return validate_fixture(fixture)


def install_fixture(source: Path, destination: Path) -> dict[str, Any]:
    fixture = load_fixture(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return fixture


def _main() -> int:
    parser = argparse.ArgumentParser(description="Validate and install a local game TCP fixture")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install")
    install.add_argument("source", type=Path)
    install.add_argument("destination", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("fixture", type=Path)
    capture = subparsers.add_parser("from-capture")
    capture.add_argument("source", type=Path)
    capture.add_argument("destination", type=Path)
    capture.add_argument("--server-id", type=int, default=4)
    capture.add_argument("--sdk-user-id", type=int, required=True)
    capture.add_argument("--login-open-id", default="")
    capture.add_argument("--login-user-id", default="")
    capture.add_argument("--game-uid", default="")
    capture.add_argument("--fixture-name", default="capture-startup")
    args = parser.parse_args()
    try:
        if args.command == "install":
            fixture = install_fixture(args.source, args.destination)
        elif args.command == "validate":
            fixture = load_fixture(args.fixture)
        else:
            fixture = fixture_from_capture(
                args.source,
                server_id=args.server_id,
                sdk_user_id=args.sdk_user_id,
                login_open_id=args.login_open_id,
                login_user_id=args.login_user_id,
                game_uid=args.game_uid,
                fixture_name=args.fixture_name,
            )
            args.destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.destination.with_suffix(args.destination.suffix + ".tmp")
            temporary.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(args.destination)
    except ProtoError as exc:
        parser.error(str(exc))
    print(json.dumps({"status": "ok", "game_uid": fixture["game_uid"], "messages": len(fixture["messages"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
