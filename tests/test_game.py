from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import main as main_module
from server.config import load_settings
from server.crypto import decode_json, encode_json
from server.fixture_tool import fixture_from_capture, validate_fixture
from server.game_proto import (
    Frame,
    decode_frame,
    decode_string_map_field,
    encode_bytes_field,
    encode_frame,
    encode_login_ack,
    encode_role_info,
    encode_risk_battle_ntf,
    encode_string_field,
    encode_string_map_field,
    encode_varint_field,
    extract_role_base,
    extract_startup_parts,
    get_bytes,
    get_string,
    get_varint,
    patch_role_base_diamond,
    patch_startup_diamond,
)
from server.game_tcp import GUIDE_COMPLETION_KEYS, GameTcpServer, _apply_guide_save
from server.products import resolve_game_product
from server.storage import Storage


def _test_settings(root: Path, overrides: dict[str, object] | None = None):
    config_path = root / "empty.toml"
    config_path.write_text("", encoding="utf-8")
    values: dict[str, object] = {
        "storage.database": root / "server.sqlite3",
        "logging.data_dir": root / "logs",
    }
    values.update(overrides or {})
    return load_settings(config_path, environ={}, overrides=values)


def _fixture_frame(msg_id: int, body: bytes, seq: int = 0) -> dict[str, object]:
    return Frame(body=body, msg_id=msg_id, seq=seq, flag=0).to_json()


def _make_fixture(
    path: Path,
    *,
    sdk_user_id: int = 1,
    login_open_id: str = "",
    login_user_id: str = "1",
) -> None:
    role_base = (
        encode_varint_field(1, 123456789)
        + encode_string_field(2, "Local Role")
        + encode_varint_field(8, 5)
        + encode_varint_field(9, 1)
        + encode_string_field(200, "unknown-preserved")
    )
    startup = encode_varint_field(1, 100) + encode_bytes_field(4, role_base) + encode_bytes_field(5, b"bag")
    fixture = {
        "version": 1,
        "server_id": 4,
        "sdk_user_id": sdk_user_id,
        "login_open_id": login_open_id,
        "login_user_id": login_user_id,
        "game_uid": "123456789",
        "fixture_name": "test-startup",
        "messages": [
            _fixture_frame(4, encode_login_ack(client_id=1)),
            _fixture_frame(25, startup),
            _fixture_frame(26, b"equip"),
            _fixture_frame(27, b"hero"),
            _fixture_frame(28, b"end"),
        ],
    }
    path.write_text(json.dumps(fixture), encoding="utf-8")


class GameProtocolTests(unittest.TestCase):
    def test_frame_round_trip_and_role_patch_preserves_unknown_fields(self) -> None:
        frame = Frame(b"payload", 76, -7, 65535)
        self.assertEqual(decode_frame(encode_frame(frame)), frame)

        role_base = encode_varint_field(1, 123) + encode_varint_field(8, 5) + encode_string_field(200, "keep")
        patched = patch_role_base_diamond(role_base, 45)
        self.assertEqual(get_varint(patched, 8), 45)
        self.assertEqual(get_varint(patched, 1), 123)
        self.assertEqual(get_bytes(patched, 200), b"keep")

        startup = encode_bytes_field(4, role_base) + encode_bytes_field(5, b"bag")
        patched_startup = patch_startup_diamond(startup, 99)
        self.assertEqual(get_varint(extract_role_base(patched_startup), 8), 99)
        self.assertEqual(get_bytes(patched_startup, 5), b"bag")

    def test_string_map_round_trip_preserves_guide_entries(self) -> None:
        body = encode_string_map_field(
            1,
            {
                "TutorialForceFirstBattle": "done",
                "TutorialOptionalHeroGrowth": "done",
            },
        )
        self.assertEqual(
            decode_string_map_field(body, 1),
            {
                "TutorialForceFirstBattle": "done",
                "TutorialOptionalHeroGrowth": "done",
            },
        )

    def test_official_guide_step_records_build_cumulative_completion_flags(self) -> None:
        terminal_steps = {
            "TutorialForceFirstBattle": "2_TreeRefNode",
            "TutorialForceBattleFormat": "3_TreeRefNode",
            "TutorialForceHInteractive": "3_TreeRefNode",
            "TutorialForceDrawCard": "3_TreeRefNode",
            "TutorialForceBattleTeam": "3_TreeRefNode",
            "TutorialForceBattleFour": "3_TreeRefNode",
            "TutorialForceHPlay": "3_TreeRefNode",
            "TutorialForceBattleFive": "3_TreeRefNode",
            "TutorialForceFinalBattle": "3_TreeRefNode",
            "TutorialOptionalHeroGrowth": "4_IfTutorialNotSavedNode",
        }
        guide: dict[str, str] = {}
        for segment_id, step_id in terminal_steps.items():
            guide, completion_key = _apply_guide_save(
                guide,
                {
                    "guide_session_id": "session-1",
                    "segment_id": segment_id,
                    "step_id": step_id,
                    "step_status": "1",
                },
            )
            self.assertEqual(completion_key, GUIDE_COMPLETION_KEYS[segment_id])
        self.assertEqual(
            {key for key in GUIDE_COMPLETION_KEYS.values()},
            {key for key in guide if key not in {"guide_session_id", "segment_id", "step_id", "step_status"}},
        )

    def test_apply_guide_save_merges_full_client_map(self) -> None:
        guide, completion_key = _apply_guide_save(
            {"guide_first_battle": "1"},
            {
                "guide_format_page": "1",
                "guide_h_interactive": "1",
                "guide_drawcard": "1",
                "guide_battle_team": "1",
                "guide_battle_four": "1",
                "guide_h_play": "1",
                "guide_battle_five": "1",
                "guide_battle_final": "1",
                "herogrowth_10002": "1",
            },
        )
        self.assertIsNone(completion_key)
        self.assertEqual(guide["guide_first_battle"], "1")
        self.assertEqual(guide["guide_battle_final"], "1")
        self.assertEqual(guide["herogrowth_10002"], "1")

    def test_encode_role_risk_battle_keeps_empty_tower_and_star_reward(self) -> None:
        from server.game_proto import encode_role_risk_battle

        body = encode_role_risk_battle(
            {
                "current_level": 1001003,
                "completed": {
                    "1001001": {"star": 3},
                    "1001002": {"star": 2},
                },
            }
        )
        self.assertEqual(get_varint(body, 1), 1001003)
        self.assertEqual(get_varint(get_bytes(body, 3) or b"", 1), 1001001)
        self.assertEqual(get_bytes(body, 6), b"")
        self.assertEqual(get_bytes(body, 7), b"")

    def test_fixture_validation_requires_confirmed_startup_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            _make_fixture(path)
            fixture = validate_fixture(json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(fixture["game_uid"], "123456789")
            self.assertEqual(fixture["initial_diamond"], 5)

    def test_fixture_validation_accepts_open_id_without_user_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            _make_fixture(path, login_open_id="1", login_user_id="")
            fixture = validate_fixture(json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(fixture["login_open_id"], "1")
            self.assertEqual(fixture["login_user_id"], "")

    def test_fixture_validation_accepts_chunked_startup_messages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            role_base = encode_varint_field(1, 123456789) + encode_varint_field(8, 5)
            value = {
                "server_id": 4,
                "sdk_user_id": 1,
                "login_open_id": "1",
                "messages": [
                    _fixture_frame(4, encode_login_ack(client_id=1)),
                    _fixture_frame(25, encode_bytes_field(4, role_base)),
                    _fixture_frame(25, encode_bytes_field(5, b"bag")),
                    _fixture_frame(25, encode_bytes_field(32, b"tasks")),
                    _fixture_frame(26, b"equip"),
                    _fixture_frame(27, b"hero"),
                    _fixture_frame(28, b"end"),
                ],
            }
            path.write_text(json.dumps(value), encoding="utf-8")
            fixture = validate_fixture(value)
            frames = [Frame.from_json(item) for item in fixture["messages"]]
            collected_role, collected_bag = extract_startup_parts(frames)
            self.assertEqual(get_varint(collected_role, 1), 123456789)
            self.assertEqual(collected_bag, b"bag")

    def test_capture_converter_preserves_chunked_startup_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture.json"
            destination = root / "fixtures" / "role.json"
            frames = [
                {"direction": "c2s", "msg_id": 3, "body_len": 1, "body_b64": "AA=="},
                {"direction": "s2c", "msg_id": 7, "seq": 0, "flag": 0, "body_len": len(encode_string_field(1, "pass")), "body_b64": base64.b64encode(encode_string_field(1, "pass")).decode("ascii")},
                {"direction": "s2c", "msg_id": 4, "seq": 7, "flag": 0, "body_len": 0, "body_b64": ""},
                {"direction": "s2c", "msg_id": 25, "seq": 0, "flag": 0, "body_len": 0, "body_b64": ""},
            ]
            role_base = encode_varint_field(1, 123456789) + encode_varint_field(8, 5)
            frames[3]["body_b64"] = base64.b64encode(encode_bytes_field(4, role_base)).decode("ascii")
            frames[3]["body_len"] = len(base64.b64decode(frames[3]["body_b64"]))
            bag_body = encode_bytes_field(5, b"bag")
            frames.extend(
                [
                    {"direction": "s2c", "msg_id": 25, "seq": 0, "flag": 0, "body_len": len(bag_body), "body_b64": base64.b64encode(bag_body).decode("ascii")},
                    {"direction": "s2c", "msg_id": 26, "seq": 0, "flag": 0, "body_len": 0, "body_b64": ""},
                    {"direction": "s2c", "msg_id": 27, "seq": 0, "flag": 0, "body_len": 0, "body_b64": ""},
                    {"direction": "s2c", "msg_id": 28, "seq": 0, "flag": 0, "body_len": 0, "body_b64": ""},
                ]
            )
            capture.write_text(json.dumps({"frames": frames}), encoding="utf-8")
            fixture = fixture_from_capture(
                capture,
                server_id=4,
                sdk_user_id=1,
                login_open_id="1",
            )
            self.assertEqual([item["msg_id"] for item in fixture["messages"]], [7, 4, 25, 25, 26, 27, 28])

    def test_fixture_validation_rejects_missing_role_bag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            _make_fixture(path)
            value = json.loads(path.read_text(encoding="utf-8"))
            startup = value["messages"][1]
            startup_body = base64.b64decode(startup["body_b64"])
            role_base = extract_role_base(startup_body)
            startup["body_b64"] = base64.b64encode(
                encode_varint_field(1, 100) + encode_bytes_field(4, role_base)
            ).decode("ascii")
            with self.assertRaises(ValueError):
                validate_fixture(value)


class GameStorageTests(unittest.TestCase):
    def test_role_open_id_migration_preserves_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "server.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        username TEXT NOT NULL,
                        password_salt TEXT NOT NULL,
                        password_hash TEXT NOT NULL,
                        profile_json TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE game_roles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sdk_user_id INTEGER NOT NULL,
                        server_id INTEGER NOT NULL,
                        login_user_id TEXT NOT NULL,
                        game_uid TEXT NOT NULL,
                        fixture_name TEXT NOT NULL DEFAULT '',
                        startup_json TEXT NOT NULL,
                        role_base_blob BLOB NOT NULL,
                        role_bag_blob BLOB NOT NULL DEFAULT X'',
                        diamond INTEGER NOT NULL DEFAULT 0,
                        role_version INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        UNIQUE(server_id, login_user_id),
                        UNIQUE(server_id, game_uid)
                    );
                    INSERT INTO users VALUES (7, 'legacy', 'salt', 'hash', '{}', 1, 1);
                    INSERT INTO game_roles(
                        sdk_user_id, server_id, login_user_id, game_uid,
                        fixture_name, startup_json, role_base_blob, role_bag_blob,
                        diamond, role_version, created_at, updated_at
                    ) VALUES (7, 4, 'legacy-user', 'legacy-role', 'legacy', '[]', X'0805', X'626167', 12, 3, 1, 1);
                    """
                )
                connection.commit()
            finally:
                connection.close()
            storage = Storage(database)
            storage.initialize()
            connection = sqlite3.connect(database)
            try:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(game_roles)").fetchall()
                }
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                row = connection.execute(
                    "SELECT login_open_id, login_user_id, diamond, role_version FROM game_roles WHERE id = 1"
                ).fetchone()
            finally:
                connection.close()
            self.assertIn("login_open_id", columns)
            self.assertEqual(version, 4)
            self.assertEqual(row, ("", "legacy-user", 12, 3))

    def test_game_payment_is_idempotent_and_creates_outbox_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("game-user", "secret")
            assert user is not None
            role_base = encode_varint_field(1, 123) + encode_varint_field(8, 5)
            role = storage.ensure_game_role(
                sdk_user_id=user["id"],
                server_id=4,
                login_user_id="login-user",
                game_uid="123",
                fixture_name="test",
                startup_json=json.dumps([]),
                role_base_blob=role_base,
                initial_diamond=5,
            )
            product = resolve_game_product("4000001", "60")
            assert product is not None
            game_order, duplicate = storage.create_game_order(
                role_id=role["id"],
                game_order_no="1001",
                server_id=4,
                shop_id=1,
                goods_id=4000001,
                quantity=1,
                order_price=60,
                product_id=product.product_id,
            )
            self.assertFalse(duplicate)
            payment, _ = storage.record_payment_order(
                user["id"],
                "device",
                {"amount": "60", "orderNum": "1001", "extra": '{"orderNo":"1001","userId":"123","serverId":"4"}'},
            )
            first = storage.settle_game_payment(
                game_order_id=game_order["id"], payment_order_id=payment["id"], product=product
            )
            second = storage.settle_game_payment(
                game_order_id=game_order["id"], payment_order_id=payment["id"], product=product
            )
            self.assertEqual(first["state"], "granted")
            self.assertEqual(first["diamond_after"], 45)
            self.assertEqual(second["state"], "already_granted")
            self.assertEqual(storage.get_game_role(role["id"])["diamond"], 45)
            self.assertEqual(len(storage.list_game_diamond_transactions(role["id"])), 1)
            self.assertEqual(len(storage.list_pending_game_events()), 1)


class GameApiTests(unittest.TestCase):
    def test_domain_returns_local_candidates_for_plain_and_encrypted_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = _test_settings(
                Path(directory),
                {"sdk.domain_urls": ["http://10.0.0.2:8080", "http://10.0.0.3:8080/"]},
            )
            with TestClient(main_module.create_app(settings)) as client:
                plain = client.post("/api/domain", json={"platform": "android"})
                encrypted = client.post(
                    "/api/domain",
                    content=encode_json({"token": "domain-token", "data": {"version": "0.11"}}),
                )

        self.assertEqual(plain.status_code, 200)
        plain_payload = plain.json()["data"]
        self.assertEqual(
            plain_payload["domains"],
            ["http://10.0.0.2:8080", "http://10.0.0.3:8080"],
        )
        self.assertEqual(plain_payload["server_list_url"], "http://10.0.0.2:8080/server/list")

        self.assertEqual(encrypted.status_code, 200)
        encrypted_payload = decode_json(encrypted.content)
        self.assertEqual(encrypted_payload["status"], "y")
        self.assertEqual(
            encrypted_payload["data"]["domain"],
            "http://10.0.0.2:8080",
        )

    def test_domain_rejects_invalid_encrypted_request_without_echoing_body(self) -> None:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/api/domain",
                content=b"invalid-ciphertext",
                headers={"content-type": "application/octet-stream"},
            )
        self.assertEqual(response.status_code, 200)
        result = decode_json(response.content)
        self.assertEqual(result["status"], "n")
        self.assertEqual(result["errorCode"], "4000")

    def test_resource_url_returns_original_cdn_without_fetching_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = _test_settings(
                Path(directory),
                {
                    "game.resource_url": "https://pxcdn.jhdwxp.com/ReleaseGame18/Android/1.2.5/",
                    "game.resource_env_type": "prod",
                },
            )
            with TestClient(main_module.create_app(settings)) as client:
                plain = client.post(
                    "/resource/url",
                    json={
                        "platform": "18game",
                        "version": "0.11",
                        "resource_type": "hotfix",
                        "device_id": "device",
                    },
                )
                encrypted = client.post(
                    "/resource/url",
                    content=encode_json(
                        {
                            "token": "resource-token",
                            "data": {"resource_type": "manifest", "version": "0.11"},
                        }
                    ),
                )

        self.assertEqual(plain.status_code, 200)
        plain_result = plain.json()
        self.assertEqual(plain_result["code"], 0)
        self.assertEqual(plain_result["data"]["env_type"], "prod")
        self.assertEqual(plain_result["data"]["resource_type"], "hotfix")
        self.assertEqual(
            plain_result["data"]["url"],
            "https://pxcdn.jhdwxp.com/ReleaseGame18/Android/1.2.5",
        )

        self.assertEqual(encrypted.status_code, 200)
        encrypted_result = decode_json(encrypted.content)
        self.assertEqual(encrypted_result["status"], "y")
        self.assertEqual(encrypted_result["data"]["resource_type"], "manifest")
        self.assertEqual(
            encrypted_result["data"]["url"],
            "https://pxcdn.jhdwxp.com/ReleaseGame18/Android/1.2.5",
        )

    def test_resource_url_defaults_match_captured_release_response(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with TestClient(main_module.app) as client:
                response = client.post(
                    "/resource/url",
                    json={
                        "platform": "18game",
                        "resource_type": "android_cn_release",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "code": 0,
                "data": {
                    "env_type": "prod",
                    "resource_type": "android_cn_release",
                    "url": "/ReleaseGame18/Android/1.2.5",
                },
            },
        )

    def test_resource_url_rejects_invalid_plain_request(self) -> None:
        with TestClient(main_module.app) as client:
            response = client.post(
                "/resource/url",
                content=b"not-json",
                headers={"content-type": "application/json"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], "4000")

    def test_server_list_returns_local_tcp_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = _test_settings(
                Path(directory),
                {
                    "game.server_id": 4,
                    "game.tcp_port": 21001,
                    "game.advertise_host": "10.0.0.2",
                },
            )
            with TestClient(main_module.create_app(settings)) as client:
                response = client.post("/server/list", json={"platform": "android", "version": "0.11"})
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["recommend_servers"], [])
        server = data["my_servers"][0]
        self.assertEqual(server["server_id"], 4)
        self.assertEqual(server["addr"], "10.0.0.2")
        self.assertEqual(server["port"], 21001)
        self.assertEqual(server["server_type"], 3)
        self.assertEqual(server["close_register"], False)
        self.assertEqual(server["is_whitelist"], 0)

    def test_spend_settles_a_registered_game_order_without_g_point_debit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("api-game-user", "secret")
            assert user is not None
            role_base = encode_varint_field(1, 123) + encode_varint_field(8, 5)
            role = storage.ensure_game_role(
                sdk_user_id=user["id"],
                server_id=4,
                login_user_id="login-user",
                game_uid="123",
                fixture_name="test",
                startup_json=json.dumps([]),
                role_base_blob=role_base,
                initial_diamond=5,
            )
            product = resolve_game_product(4000001, 60)
            assert product is not None
            game_order, _ = storage.create_game_order(
                role_id=role["id"],
                game_order_no="2001",
                server_id=4,
                shop_id=1,
                goods_id=4000001,
                quantity=1,
                order_price=60,
                product_id=product.product_id,
            )
            token = storage.issue_token(user["id"], "api-device")
            request = {
                "token": token,
                "deviceId": "api-device",
                "data": {
                    "amount": "60",
                    "orderNum": "2001",
                    "extra": '{"orderNo":"2001","serverId":"4","userId":"123"}',
                },
            }
            with patch.object(main_module, "storage", storage):
                with TestClient(main_module.app) as client:
                    response = client.post("/api/sdk/spend/create2", content=encode_json(request))
            result = decode_json(response.content)
            self.assertEqual(result["status"], "y")
            self.assertEqual(storage.get_game_role(role["id"])["diamond"], 45)
            self.assertEqual(storage.wallet_balance(user["id"]), 0)


class GameTcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_lookup_reports_missing_empty_and_identity_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_service = GameTcpServer(fixture_dir=root / "missing")
            fixture, reason, match_key = missing_service._fixture_for_login(
                {"open_id": "1", "user_id": ""}
            )
            self.assertIsNone(fixture)
            self.assertEqual(reason, "fixture_dir_missing")
            self.assertEqual(match_key, "none")

            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            empty_service = GameTcpServer(fixture_dir=fixture_dir)
            fixture, reason, match_key = empty_service._fixture_for_login(
                {"open_id": "1", "user_id": ""}
            )
            self.assertIsNone(fixture)
            self.assertEqual(reason, "fixture_empty")
            self.assertEqual(match_key, "none")

            _make_fixture(fixture_dir / "role.json", login_open_id="1", login_user_id="legacy-user")
            conflict_service = GameTcpServer(fixture_dir=fixture_dir)
            fixture, reason, match_key = conflict_service._fixture_for_login(
                {"open_id": "1", "user_id": "different-user"}
            )
            self.assertIsNone(fixture)
            self.assertEqual(reason, "identity_mismatch")
            self.assertEqual(match_key, "open_id")

    async def test_login_order_and_online_role_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("tcp-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            fixture_path = fixture_dir / "role.json"
            _make_fixture(
                fixture_path,
                sdk_user_id=user["id"],
                login_open_id="1",
                login_user_id="",
            )
            service = GameTcpServer(
                storage=storage,
                host="127.0.0.1",
                port=0,
                server_id=4,
                fixture_dir=fixture_dir,
                poll_interval=0.02,
            )
            await service.start()
            assert service._server is not None
            port = service._server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                token = storage.issue_token(user["id"], "tcp-device")
                login_body = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 10, 0)))
                await writer.drain()
                response_ids = [await asyncio.wait_for(_read_frame(reader), 1) for _ in range(5)]
                self.assertEqual([frame.msg_id for frame in response_ids], [4, 25, 26, 27, 28])
                self.assertEqual(get_varint(extract_role_base(response_ids[1].body), 8), 5)

                order_body = (
                    encode_varint_field(2, 4)
                    + encode_varint_field(3, 1)
                    + encode_varint_field(4, 4000001)
                    + encode_varint_field(5, 1)
                    + encode_string_field(6, "1")
                )
                writer.write(encode_frame(Frame(order_body, 377, 11, 0)))
                await writer.drain()
                order_ack = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(order_ack.msg_id, 378)
                order_no = str(get_varint(order_ack.body, 2))

                role = storage.get_game_role_by_identity(4, login_open_id="1")
                assert role is not None
                product = resolve_game_product(4000001, 60)
                assert product is not None
                game_order = storage.find_game_order_for_payment(user["id"], order_num=order_no)
                assert game_order is not None
                payment, _ = storage.record_payment_order(
                    user["id"],
                    "tcp-device",
                    {"amount": "60", "orderNum": order_no, "extra": json.dumps({"orderNo": order_no, "serverId": "4", "userId": "123456789"})},
                )
                storage.settle_game_payment(
                    game_order_id=game_order["id"], payment_order_id=payment["id"], product=product
                )
                update = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(update.msg_id, 76)
                self.assertEqual(get_varint(get_bytes(update.body, 3) or b"", 8), 45)
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_change_nickname_ack_persists_across_reconnect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("nickname-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(
                fixture_dir / "role.json",
                sdk_user_id=user["id"],
                login_open_id="1",
                login_user_id="",
            )
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
            token = storage.issue_token(user["id"], "nickname-device")

            async def login() -> tuple[asyncio.StreamReader, asyncio.StreamWriter, list[Frame]]:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                login_body = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 10, 4)))
                await writer.drain()
                startup = [await asyncio.wait_for(_read_frame(reader), 1) for _ in range(5)]
                return reader, writer, startup

            reader, writer, startup = await login()
            try:
                self.assertEqual([frame.msg_id for frame in startup], [4, 25, 26, 27, 28])
                nickname_body = encode_string_field(1, "持国天王") + encode_varint_field(2, 1)
                writer.write(encode_frame(Frame(nickname_body, 21, 11, 7)))
                await writer.drain()
                ack = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(ack.msg_id, 22)
                self.assertEqual(ack.body, b"")
                self.assertEqual(ack.seq, 11)
                self.assertEqual(ack.flag, 7)
                role = storage.get_game_role_by_identity(4, login_open_id="1")
                assert role is not None
                self.assertEqual(get_string(bytes(role["role_base_blob"]), 2), "持国天王")
            finally:
                writer.close()
                await writer.wait_closed()

            reader, writer, startup = await login()
            try:
                self.assertEqual(get_string(extract_role_base(startup[1].body), 2), "持国天王")
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_saved_role_state_and_guide_are_restored_on_reconnect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("restore-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(fixture_dir / "role.json", sdk_user_id=user["id"], login_open_id="1", login_user_id="")
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
            token = storage.issue_token(user["id"], "restore-device")

            async def login() -> tuple[asyncio.StreamReader, asyncio.StreamWriter, list[Frame]]:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                login_body = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 10, 0)))
                await writer.drain()
                startup = [await asyncio.wait_for(_read_frame(reader), 1) for _ in range(5)]
                return reader, writer, startup

            reader, writer, startup = await login()
            try:
                self.assertEqual([frame.msg_id for frame in startup], [4, 25, 26, 27, 28])
                guide_body = encode_string_map_field(
                    1,
                    {
                        "guide_session_id": "session-1",
                        "segment_id": "TutorialForceFirstBattle",
                        "step_id": "2_TreeRefNode",
                        "step_status": "1",
                    },
                )
                writer.write(encode_frame(Frame(guide_body, 59, 11, 0)))
                await writer.drain()
                self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 60)

                optional_guide_body = encode_string_map_field(
                    1,
                    {
                        "guide_session_id": "session-1",
                        "segment_id": "TutorialOptionalHeroGrowth",
                        "step_id": "4_IfTutorialNotSavedNode",
                        "step_status": "1",
                    },
                )
                writer.write(encode_frame(Frame(optional_guide_body, 59, 12, 0)))
                await writer.drain()
                self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 60)

                role = storage.get_game_role_by_identity(4, login_open_id="1")
                assert role is not None
                role_base = (
                    encode_varint_field(1, 123456789)
                    + encode_string_field(2, "Saved Role")
                    + encode_varint_field(7, 2100)
                    + encode_varint_field(8, 50)
                    + encode_bytes_field(9, encode_varint_field(1, 4) + encode_varint_field(3, 100))
                )
                storage.ensure_game_role(
                    sdk_user_id=user["id"],
                    server_id=4,
                    login_open_id="1",
                    login_user_id="",
                    game_uid="123456789",
                    fixture_name="test-startup",
                    startup_json=str(role["startup_json"]),
                    role_base_blob=role_base,
                    role_bag_blob=b"persisted-bag",
                    initial_diamond=0,
                    preserve_existing_state=False,
                )
                state = storage.get_game_state(role["id"])
                state.update({"coin": 2100, "diamond": 50, "level": 4})
                storage.update_game_state(role["id"], state)
            finally:
                writer.close()
                await writer.wait_closed()

            reader, writer, startup = await login()
            try:
                role_base = extract_role_base(startup[1].body)
                self.assertEqual(get_varint(role_base, 7), 2100)
                self.assertEqual(get_varint(role_base, 8), 50)
                self.assertEqual(get_string(role_base, 2), "Saved Role")
                self.assertEqual(get_bytes(startup[1].body, 5), b"persisted-bag")
                self.assertEqual(
                    decode_string_map_field(get_bytes(startup[1].body, 123) or b"", 1),
                    {
                        "guide_session_id": "session-1",
                        "segment_id": "TutorialOptionalHeroGrowth",
                        "step_id": "4_IfTutorialNotSavedNode",
                        "step_status": "1",
                        "guide_first_battle": "1",
                        "herogrowth_10002": "1",
                    },
                )

                writer.write(encode_frame(Frame(b"", 61, 20, 0)))
                await writer.drain()
                guide_ack = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(guide_ack.msg_id, 62)
                self.assertEqual(
                    decode_string_map_field(guide_ack.body, 2),
                    {
                        "guide_session_id": "session-1",
                        "segment_id": "TutorialOptionalHeroGrowth",
                        "step_id": "4_IfTutorialNotSavedNode",
                        "step_status": "1",
                        "guide_first_battle": "1",
                        "herogrowth_10002": "1",
                    },
                )
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_tutorial_battle_start_ack_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("battle-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(
                fixture_dir / "role.json",
                sdk_user_id=user["id"],
                login_open_id="1",
                login_user_id="",
            )
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
                token = storage.issue_token(user["id"], "battle-device")
                login_body = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 10, 0)))
                await writer.drain()
                startup = [await asyncio.wait_for(_read_frame(reader), 1) for _ in range(5)]
                self.assertEqual([frame.msg_id for frame in startup], [4, 25, 26, 27, 28])

                requests = [
                    (111, b"", 112, b"", 21, 6),
                    (141, encode_varint_field(1, 1001), 142, b"", 22, 7),
                    (153, encode_varint_field(1, 1002), 154, b"", 23, 8),
                ]
                for request_id, body, response_id, expected_body, seq, flag in requests:
                    writer.write(encode_frame(Frame(body, request_id, seq, flag)))
                    await writer.drain()
                    response = await asyncio.wait_for(_read_frame(reader), 1)
                    self.assertEqual(response.msg_id, response_id)
                    self.assertEqual(response.body, expected_body)
                    self.assertEqual(response.seq, seq)
                    self.assertEqual(response.flag, flag)
                    self.assertEqual(get_varint(response.body, 2), 0)
                    if request_id == 141:
                        follow_up = await asyncio.wait_for(_read_frame(reader), 1)
                        self.assertEqual(follow_up.msg_id, 149)
                        self.assertEqual(follow_up.seq, seq)
                        self.assertEqual(follow_up.flag, flag)
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_change_nickname_rejects_empty_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("empty-nickname-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(
                fixture_dir / "role.json",
                sdk_user_id=user["id"],
                login_open_id="1",
                login_user_id="",
            )
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
                token = storage.issue_token(user["id"], "empty-nickname-device")
                login_body = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 1, 0)))
                await writer.drain()
                for _ in range(5):
                    await asyncio.wait_for(_read_frame(reader), 1)
                writer.write(encode_frame(Frame(encode_varint_field(2, 1), 21, 2, 0)))
                await writer.drain()
                ack = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(ack.msg_id, 22)
                self.assertEqual(get_varint(ack.body, 1), 105)
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_hero_edit_lineup_returns_success_ack(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("lineup-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(
                fixture_dir / "role.json",
                sdk_user_id=user["id"],
                login_open_id="1",
                login_user_id="",
            )
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
                token = storage.issue_token(user["id"], "lineup-device")
                login_body = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 1, 0)))
                await writer.drain()
                for _ in range(5):
                    await asyncio.wait_for(_read_frame(reader), 1)

                lineup_body = (
                    encode_varint_field(1, 2)
                    + encode_bytes_field(
                        2,
                        encode_varint_field(1, 1001)
                        + encode_varint_field(1, 1002)
                        + encode_varint_field(1, 1003),
                    )
                )
                writer.write(encode_frame(Frame(lineup_body, 109, 12, 5)))
                await writer.drain()
                ack = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(ack.msg_id, 110)
                self.assertEqual(ack.body, b"")
                self.assertEqual(ack.seq, 12)
                self.assertEqual(ack.flag, 5)
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_captured_battle_chain_updates_persistent_role_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("captured-battle-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(
                fixture_dir / "role.json",
                sdk_user_id=user["id"],
                login_open_id="1",
                login_user_id="",
            )
            fixture = json.loads((fixture_dir / "role.json").read_text(encoding="utf-8"))
            startup = base64.b64decode(fixture["messages"][1]["body_b64"])
            role_base = extract_role_base(startup)
            request_start = encode_varint_field(1, 1001001)
            request_win = (
                encode_varint_field(1, 1001001)
                + encode_varint_field(2, 1)
                + encode_varint_field(4, 3)
                + encode_bytes_field(5, b"0133")
            )

            def capture_frame(direction: str, msg_id: int, body: bytes) -> dict[str, object]:
                return {
                    "direction": direction,
                    "msg_id": msg_id,
                    "seq": 0,
                    "flag": 0,
                    "body_len": len(body),
                    "body_b64": base64.b64encode(body).decode("ascii"),
                }

            gameplay_capture = root / "gameplay.json"
            gameplay_capture.write_text(
                json.dumps(
                    {
                        "frames": [
                            capture_frame("c2s", 141, request_start),
                            capture_frame("s2c", 142, b""),
                            capture_frame("s2c", 149, encode_risk_battle_ntf(1001001)),
                            capture_frame("c2s", 143, request_win),
                            capture_frame("s2c", 76, encode_role_info(role_base, 5, 300)),
                            capture_frame("s2c", 149, encode_risk_battle_ntf(1001001, 1001001)),
                            capture_frame("s2c", 144, encode_varint_field(1, 0)),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            service = GameTcpServer(
                storage=storage,
                host="127.0.0.1",
                port=0,
                server_id=4,
                fixture_dir=fixture_dir,
                gameplay_capture=gameplay_capture,
            )
            await service.start()
            assert service._server is not None
            port = service._server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                token = storage.issue_token(user["id"], "captured-battle-device")
                writer.write(
                    encode_frame(
                        Frame(
                            encode_string_field(3, token) + encode_string_field(4, "1"),
                            3,
                            1,
                            0,
                        )
                    )
                )
                await writer.drain()
                for _ in range(5):
                    await asyncio.wait_for(_read_frame(reader), 1)

                writer.write(encode_frame(Frame(request_start, 141, 2, 3)))
                await writer.drain()
                self.assertEqual([await asyncio.wait_for(_read_frame(reader), 1) for _ in range(2)], [
                    Frame(b"", 142, 2, 3),
                    Frame(encode_risk_battle_ntf(1001001), 149, 2, 3),
                ])

                writer.write(encode_frame(Frame(request_win, 143, 4, 5)))
                await writer.drain()
                results = [await asyncio.wait_for(_read_frame(reader), 1) for _ in range(3)]
                self.assertEqual([item.msg_id for item in results], [76, 149, 144])
                role = storage.get_game_role_by_identity(4, login_open_id="1")
                assert role is not None
                self.assertEqual(role["diamond"], 5)
                state = storage.get_game_state(role["id"])
                self.assertEqual(state["coin"], 300)
                self.assertEqual(state["risk"]["completed"]["1001001"]["star"], 3)
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    def test_gameplay_capture_skips_interleaved_transport_frames(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory) / "gameplay.json"

            def capture_frame(direction: str, msg_id: int, body: bytes = b"") -> dict[str, object]:
                return {
                    "direction": direction,
                    "msg_id": msg_id,
                    "seq": 0,
                    "flag": 0,
                    "body_len": len(body),
                    "body_b64": base64.b64encode(body).decode("ascii"),
                }

            start = encode_varint_field(1, 1001001)
            win = (
                encode_varint_field(1, 1001001)
                + encode_varint_field(2, 1)
                + encode_varint_field(4, 3)
            )
            capture.write_text(
                json.dumps(
                    {
                        "frames": [
                            capture_frame("c2s", 109),
                            capture_frame("s2c", 60),
                            capture_frame("c2s", 59),
                            capture_frame("s2c", 118),
                            capture_frame("s2c", 110),
                            capture_frame("c2s", 141, start),
                            capture_frame("s2c", 142),
                            capture_frame("s2c", 149),
                            capture_frame("c2s", 1),
                            capture_frame("s2c", 2),
                            capture_frame("c2s", 143, win),
                            capture_frame("s2c", 60),
                            capture_frame("c2s", 59),
                            capture_frame("s2c", 76),
                            capture_frame("c2s", 63),
                            capture_frame("s2c", 24140),
                            capture_frame("s2c", 144),
                            capture_frame("c2s", 59),
                            capture_frame("s2c", 60),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            service = GameTcpServer(gameplay_capture=capture)
            lineup_event = service._gameplay_event(Frame(b"", 109, 1, 0))
            self.assertEqual([frame.msg_id for frame in lineup_event], [118, 110])

            start_event = service._gameplay_event(Frame(start, 141, 2, 0))
            self.assertEqual([frame.msg_id for frame in start_event], [142, 149])

            win_event = service._gameplay_event(Frame(win, 143, 3, 0))
            self.assertEqual([frame.msg_id for frame in win_event], [76, 24140, 144])

            time_capture = Path(directory) / "time.json"
            time_capture.write_text(
                json.dumps(
                    {
                        "frames": [
                            capture_frame("c2s", 63),
                            capture_frame("s2c", 24140),
                            capture_frame("s2c", 24147),
                            capture_frame("s2c", 64),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            time_event = GameTcpServer(gameplay_capture=time_capture)._gameplay_event(
                Frame(b"", 63, 4, 0)
            )
            self.assertEqual([frame.msg_id for frame in time_event], [64])

    async def test_gacha_and_level_up_fallbacks_persist_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("growth-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(fixture_dir / "role.json", sdk_user_id=user["id"], login_open_id="1", login_user_id="")
            service = GameTcpServer(storage=storage, host="127.0.0.1", port=0, fixture_dir=fixture_dir)
            await service.start()
            assert service._server is not None
            port = service._server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                token = storage.issue_token(user["id"], "growth-device")
                writer.write(encode_frame(Frame(encode_string_field(3, token) + encode_string_field(4, "1"), 3, 1, 0)))
                await writer.drain()
                for _ in range(5):
                    await asyncio.wait_for(_read_frame(reader), 1)

                writer.write(encode_frame(Frame(b"", 29, 2, 0)))
                await writer.drain()
                self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 30)
                writer.write(encode_frame(Frame(encode_varint_field(1, 2) + encode_varint_field(2, 1), 31, 3, 0)))
                await writer.drain()
                self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 32)
                self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 118)
                self.assertEqual((await asyncio.wait_for(_read_frame(reader), 1)).msg_id, 398)
                writer.write(encode_frame(Frame(encode_varint_field(1, 10002) + encode_varint_field(2, 1), 93, 4, 0)))
                await writer.drain()
                first = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(first.msg_id, 94)
                role = storage.get_game_role_by_identity(4, login_open_id="1")
                assert role is not None
                state = storage.get_game_state(role["id"])
                self.assertEqual(state["heroes"]["10002"]["level"], 2)
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_login_replays_captured_initialization_notifications_and_acks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("init-replay-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(
                fixture_dir / "role.json",
                sdk_user_id=user["id"],
                login_open_id="1",
                login_user_id="",
            )
            fixture = json.loads((fixture_dir / "role.json").read_text(encoding="utf-8"))
            startup_body = base64.b64decode(fixture["messages"][1]["body_b64"])
            role_uid = get_varint(extract_role_base(startup_body), 1)

            def capture_frame(direction: str, msg_id: int, body: bytes) -> dict[str, object]:
                return {
                    "direction": direction,
                    "msg_id": msg_id,
                    "seq": 0,
                    "flag": 0,
                    "body_len": len(body),
                    "body_b64": base64.b64encode(body).decode("ascii"),
                }

            capture_frames = [
                capture_frame("s2c", 4, encode_login_ack(client_id=1)),
                capture_frame("s2c", 25, startup_body),
                capture_frame("s2c", 24176, encode_varint_field(1, 3) + encode_varint_field(2, 3)),
                capture_frame("s2c", 26, b"equip"),
                capture_frame("s2c", 27, b"hero"),
                capture_frame("s2c", 376, b"server-data"),
                capture_frame("s2c", 28, b""),
                capture_frame("c2s", 23, b""),
                capture_frame("c2s", 24146, b""),
                capture_frame("c2s", 349, b""),
                capture_frame("c2s", 170, b""),
                capture_frame("c2s", 166, encode_varint_field(1, 1)),
                capture_frame("c2s", 368, b""),
                capture_frame("s2c", 24, encode_bytes_field(2, encode_varint_field(1, role_uid))),
                capture_frame("s2c", 24147, encode_bytes_field(2, b"")),
                capture_frame("s2c", 350, b""),
                capture_frame("s2c", 171, b"mail"),
                capture_frame(
                    "s2c",
                    167,
                    encode_varint_field(2, 1)
                    + encode_bytes_field(5, encode_varint_field(3, role_uid)),
                ),
                capture_frame("s2c", 369, b""),
            ]
            capture = root / "init-capture.json"
            capture.write_text(json.dumps({"frames": capture_frames}), encoding="utf-8")

            service = GameTcpServer(
                storage=storage,
                host="127.0.0.1",
                port=0,
                server_id=4,
                fixture_dir=fixture_dir,
                response_capture=capture,
            )
            await service.start()
            assert service._server is not None
            port = service._server.sockets[0].getsockname()[1]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                token = storage.issue_token(user["id"], "init-device")
                login_body = encode_string_field(3, token) + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 1, 0)))
                await writer.drain()
                startup = [await asyncio.wait_for(_read_frame(reader), 1) for _ in range(7)]
                self.assertEqual(
                    [frame.msg_id for frame in startup],
                    [4, 25, 24176, 26, 27, 376, 28],
                )

                for request_id, request_body, response_id in [
                    (23, b"", 24),
                    (24146, b"", 24147),
                    (349, b"", 350),
                    (170, b"", 171),
                    (166, encode_varint_field(1, 1), 167),
                    (368, b"", 369),
                ]:
                    writer.write(encode_frame(Frame(request_body, request_id, 2, 9)))
                    await writer.drain()
                    response = await asyncio.wait_for(_read_frame(reader), 1)
                    self.assertEqual(response.msg_id, response_id)
                    self.assertEqual(response.seq, 2)
                    self.assertEqual(response.flag, 9)
                    if response_id == 24:
                        self.assertEqual(get_varint(get_bytes(response.body, 2) or b"", 1), role_uid)
                    if response_id == 167:
                        self.assertEqual(
                            get_varint(get_bytes(response.body, 5) or b"", 3),
                            role_uid,
                        )
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_legacy_user_id_fixture_remains_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("legacy-tcp-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(fixture_dir / "legacy.json", sdk_user_id=user["id"], login_user_id="legacy-user")
            service = GameTcpServer(
                storage=storage,
                host="127.0.0.1",
                port=0,
                server_id=4,
                fixture_dir=fixture_dir,
            )
            fixture, reason, match_key = service._fixture_for_login(
                {"open_id": "", "user_id": "legacy-user"}
            )
            self.assertIsNotNone(fixture)
            self.assertEqual(reason, "")
            self.assertEqual(match_key, "user_id")

    async def test_login_rejects_invalid_token_without_creating_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("invalid-token-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(fixture_dir / "role.json", sdk_user_id=user["id"], login_open_id="1", login_user_id="")
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
                login_body = encode_string_field(3, "invalid-token") + encode_string_field(4, "1")
                writer.write(encode_frame(Frame(login_body, 3, 1, 0)))
                await writer.drain()
                response = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(response.msg_id, 4)
                self.assertEqual(get_varint(response.body, 1), 1001)
                self.assertIsNone(storage.get_game_role_by_identity(4, login_open_id="1"))
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()

    async def test_login_rejects_select_zone_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "server.sqlite3")
            storage.initialize()
            user = storage.create_user("wrong-zone-user", "secret")
            assert user is not None
            fixture_dir = root / "fixtures"
            fixture_dir.mkdir()
            _make_fixture(fixture_dir / "role.json", sdk_user_id=user["id"], login_open_id="1", login_user_id="")
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
                token = storage.issue_token(user["id"], "wrong-zone-device")
                login_body = (
                    encode_string_field(3, token)
                    + encode_string_field(4, "1")
                    + encode_varint_field(9, 5)
                )
                writer.write(encode_frame(Frame(login_body, 3, 1, 0)))
                await writer.drain()
                response = await asyncio.wait_for(_read_frame(reader), 1)
                self.assertEqual(response.msg_id, 4)
                self.assertEqual(get_varint(response.body, 1), 1001)
                self.assertIsNone(storage.get_game_role_by_identity(4, login_open_id="1"))
            finally:
                writer.close()
                await writer.wait_closed()
                await service.close()


async def _read_frame(reader: asyncio.StreamReader) -> Frame:
    header = await reader.readexactly(10)
    body = await reader.readexactly(int.from_bytes(header[:2], "big"))
    return decode_frame(header + body)


if __name__ == "__main__":
    unittest.main()
