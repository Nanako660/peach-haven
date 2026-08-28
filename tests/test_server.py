from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from server.config import load_settings
from server.crypto import decode_json, encode_json, encrypt_text, decrypt_text
from server.main import app, create_app, storage
from server.products import resolve_product
from server.storage import Storage


class ProtocolTests(unittest.TestCase):
    def test_aes_round_trip_and_fixed_vector(self) -> None:
        plaintext = '{"hello":"world","n":1}'
        ciphertext = encrypt_text(plaintext)
        self.assertEqual(decrypt_text(ciphertext), plaintext)
        self.assertEqual(
            ciphertext.hex(),
            "5eae169448f9182dd3a72c6c267dc5f814a236da9c04e0c33fc811f804e3dad1",
        )

    def test_json_envelope(self) -> None:
        envelope = {"token": "t", "deviceId": "d", "data": {"username": "test"}}
        self.assertEqual(decode_json(encode_json(envelope)), envelope)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)

    def setUp(self) -> None:
        self.client.get("/healthz")

    def post_encrypted_on(
        self,
        client: TestClient,
        path: str,
        data: dict,
        token: str = "",
        device_id: str = "test-device",
    ) -> dict:
        request = {"token": token, "deviceId": device_id, "data": data}
        response = client.post(path, content=encode_json(request))
        self.assertEqual(response.status_code, 200)
        return decode_json(response.content)

    def post_encrypted(self, path: str, data: dict, token: str = "", device_id: str = "test-device") -> dict:
        return self.post_encrypted_on(self.client, path, data, token=token, device_id=device_id)

    def test_login_validate_update_system_and_game_verify(self) -> None:
        login = self.post_encrypted(
            "/api/sdk/Login/account", {"username": "test", "password": "test1234", "channel_code": "local"}
        )
        self.assertEqual(login["status"], "y")
        token = login["data"]["token"]
        self.assertTrue(token)
        self.assertEqual(login["data"]["user_id"], login["data"]["userId"])

        valid = self.post_encrypted("/api/sdk/user/validateToken", {"token": token}, token=token)
        self.assertEqual(valid["data"], True)

        updated = self.post_encrypted(
            "/api/sdk/User/doUpdate", {"type": "1", "nickname": "Local Test", "sex": "unknown", "headico": "avatar"}, token=token
        )
        self.assertEqual(updated["status"], "y")

        info = self.post_encrypted("/api/sdk/system/info", {}, token=token)
        self.assertEqual(info["data"]["user"]["nickname"], "Local Test")
        self.assertEqual(info["data"]["user"]["has_login"], "y")
        self.assertEqual(
            info["data"]["task_points"],
            {"daily_invite_charge": 0, "newbie_bind_email": 0},
        )
        self.assertIn("site_url", info["data"])
        self.assertTrue(info["data"]["game_track_url"].endswith("/api/sdk/system/gameTrack"))

        verified = self.post_encrypted("/api/sdk/login/singleGameVerify", {}, token=token)
        self.assertEqual(verified["data"]["is_vip"], "1")

    def test_game_track_records_empty_and_nested_data(self) -> None:
        login = self.post_encrypted(
            "/api/sdk/Login/account", {"username": "test", "password": "test1234"}
        )
        token = login["data"]["token"]
        marker = "track-" + uuid.uuid4().hex
        track = self.post_encrypted(
            "/api/sdk/system/gameTrack", {}, token=token, device_id="track-device"
        )
        self.assertEqual(track["status"], "y")
        nested = self.post_encrypted(
            "/api/sdk/system/gameTrack",
            {"event": marker, "payload": {"level": 3, "items": ["a", "b"]}},
            token=token,
            device_id="track-device",
        )
        self.assertEqual(nested["status"], "y")

        tracks = storage.list_game_tracks()
        matching = [row for row in tracks if marker in row["data_json"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["device_id"], "track-device")

    def test_game_track_accepts_apk_composite_token(self) -> None:
        login = self.post_encrypted(
            "/api/sdk/Login/account", {"username": "test", "password": "test1234"}
        )
        token = login["data"]["token"]
        user_id = login["data"]["userId"]
        composite_token = f"{token}_{user_id}"
        track = self.post_encrypted(
            "/api/sdk/system/gameTrack",
            {"event": "apk-composite-token"},
            token=composite_token,
            device_id="apk-device",
        )
        self.assertEqual(track["status"], "y")
        self.assertIsNotNone(storage.get_session(composite_token))
        self.assertIsNone(storage.get_session(f"{token}_999999"))

    def test_game_track_rejects_invalid_token_and_malformed_request(self) -> None:
        with self.assertLogs("apk_sdk_server", level="WARNING") as logs:
            invalid = self.post_encrypted(
                "/api/sdk/system/gameTrack", {"event": "not-recorded"}, token="invalid-token"
            )
        self.assertEqual(invalid["status"], "n")
        self.assertEqual(invalid["errorCode"], "2002")
        self.assertTrue(any("system/gameTrack rejected" in message for message in logs.output))

        response = self.client.post("/api/sdk/system/gameTrack", content=b"not-aes-payload")
        self.assertEqual(response.status_code, 200)
        malformed = decode_json(response.content)
        self.assertEqual(malformed["status"], "n")
        self.assertEqual(malformed["errorCode"], "4000")

    def test_system_info_game_track_url_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "empty.toml"
            config_path.write_text("", encoding="utf-8")
            settings = load_settings(
                config_path,
                environ={},
                overrides={
                    "storage.database": root / "server.sqlite3",
                    "logging.data_dir": root / "logs",
                    "sdk.game_track_url": "http://example.test/track",
                },
            )
            with TestClient(create_app(settings)) as client:
                login = self.post_encrypted_on(
                    client,
                    "/api/sdk/Login/account",
                    {"username": "test", "password": "test1234"},
                )
                info = self.post_encrypted_on(
                    client,
                    "/api/sdk/system/info",
                    {},
                    token=login["data"]["token"],
                )
            self.assertEqual(info["data"]["game_track_url"], "http://example.test/track")

    def test_payment_endpoints_return_local_success_shapes(self) -> None:
        login = self.post_encrypted(
            "/api/sdk/Login/account", {"username": "test", "password": "test1234"}
        )
        token = login["data"]["token"]
        composite_token = f"{token}_{login['data']['userId']}"
        expected = {
            "/api/sdk/UserProduct/getProductList": {
                "is_new": [],
                "product_list": [],
                "pay_banner": [],
            },
            "/api/sdk/Recharge/create": {
                "success": True,
                "msg": "success",
                "url": "",
            },
            "/api/sdk/Recharge/createAndSpend": {"url": ""},
            "/api/sdk/spend/create2": {"extra": ""},
        }
        for path, data in expected.items():
            result = self.post_encrypted(
                path,
                {"amount": "1", "order_num": "local-test"},
                token=composite_token,
            )
            self.assertEqual(result["status"], "y")
            self.assertEqual(result["data"], data)

    def test_unknown_spend_records_and_deduplicates_without_crediting(self) -> None:
        login = self.post_encrypted(
            "/api/sdk/Login/account", {"username": "test", "password": "test1234"}
        )
        token = login["data"]["token"]
        order_num = "order-" + uuid.uuid4().hex
        request_data = {
            "amount": "1",
            "extra": '{"orderNo":"order-no-1","serverId":"4"}',
            "game_key": "local-game",
            "notifyUrl": "https://pxgame-api.showfifa.com/sdk/callback/18game/order",
            "orderNum": order_num,
            "sign": "test-signature",
            "timestamp": "1787418768",
            "type": "1",
        }

        with patch("urllib.request.urlopen") as urlopen:
            first = self.post_encrypted(
                "/api/sdk/spend/create2",
                request_data,
                token=token,
                device_id="payment-device",
            )
            second = self.post_encrypted(
                "/api/sdk/spend/create2",
                request_data,
                token=token,
                device_id="payment-device",
            )
            tampered = self.post_encrypted(
                "/api/sdk/spend/create2",
                {**request_data, "amount": "60"},
                token=token,
                device_id="payment-device",
            )
        urlopen.assert_not_called()
        self.assertEqual(first["status"], "y")
        self.assertEqual(first["data"], {"extra": ""})
        self.assertEqual(second["status"], "y")
        self.assertEqual(second["data"], {"extra": ""})
        self.assertEqual(tampered["status"], "y")

        orders = [
            row for row in storage.list_payment_orders(login["data"]["userId"])
            if row["order_num"] == order_num
        ]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "duplicate")
        self.assertEqual(orders[0]["request_count"], 3)
        self.assertEqual(orders[0]["device_id"], "payment-device")
        self.assertEqual(orders[0]["extra_raw"], request_data["extra"])
        self.assertEqual(orders[0]["extra_json"], '{"orderNo":"order-no-1","serverId":"4"}')
        self.assertEqual(
            orders[0]["sign_fingerprint"],
            hashlib.sha256(b"test-signature").hexdigest()[:12],
        )

        info = self.post_encrypted("/api/sdk/system/info", {}, token=token)
        self.assertEqual(info["data"]["user"]["balance"], "0")

    def test_known_product_debits_wallet_grants_first_purchase_bonus_and_is_idempotent(self) -> None:
        username = "wallet_test_" + uuid.uuid4().hex[:10]
        user = storage.create_user(username, "secret")
        self.assertIsNotNone(user)
        storage.credit_wallet(
            user["id"],
            60,
            reference_key=f"test-credit:{uuid.uuid4().hex}",
            metadata={"test": True},
        )
        token = storage.issue_token(user["id"], "wallet-device")
        order_num = "known-product-" + uuid.uuid4().hex
        request_data = {
            "amount": "60",
            "extra": '{"orderNo":"' + order_num + '","serverId":"4"}',
            "game_key": "local-game",
            "orderNum": order_num,
            "type": "1",
        }

        first = self.post_encrypted("/api/sdk/spend/create2", request_data, token=token)
        second = self.post_encrypted("/api/sdk/spend/create2", request_data, token=token)
        self.assertEqual(first["status"], "y")
        self.assertEqual(second["status"], "y")

        info = self.post_encrypted("/api/sdk/system/info", {}, token=token)
        self.assertEqual(info["data"]["user"]["balance"], "0")
        grants = [row for row in storage.list_product_grants(user["id"]) if row["payment_order_id"]]
        matching = [row for row in grants if row["product_id"] == "4000001"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["base_quantity"], 20)
        self.assertEqual(matching[0]["bonus_quantity"], 20)
        self.assertEqual(matching[0]["total_quantity"], 40)
        self.assertEqual(len(storage.list_wallet_transactions(user["id"])), 2)

    def test_known_product_rejects_insufficient_wallet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "empty.toml"
            config_path.write_text("", encoding="utf-8")
            settings = load_settings(
                config_path,
                environ={},
                overrides={
                    "storage.database": root / "server.sqlite3",
                    "logging.data_dir": root / "logs",
                    "sdk.auto_credit_g_points": False,
                },
            )
            local_storage = Storage(settings.storage.database_path, settings.storage.token_ttl_seconds)
            local_storage.initialize()
            username = "wallet_empty_" + uuid.uuid4().hex[:10]
            user = local_storage.create_user(username, "secret")
            self.assertIsNotNone(user)
            token = local_storage.issue_token(user["id"], "empty-wallet-device")
            order_num = "empty-product-" + uuid.uuid4().hex
            with TestClient(create_app(settings)) as client:
                result = self.post_encrypted_on(
                    client,
                    "/api/sdk/spend/create2",
                    {"amount": "300", "orderNum": order_num, "extra": "{}"},
                    token=token,
                )
            self.assertEqual(result["status"], "n")
            self.assertEqual(result["errorCode"], "2003")
            orders = [row for row in local_storage.list_payment_orders(user["id"]) if row["order_num"] == order_num]
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["status"], "insufficient_balance")
            self.assertEqual(local_storage.wallet_balance(user["id"]), 0)

    def test_known_product_auto_credits_by_default_and_is_idempotent(self) -> None:
        username = "wallet_auto_" + uuid.uuid4().hex[:10]
        user = storage.create_user(username, "secret")
        self.assertIsNotNone(user)
        token = storage.issue_token(user["id"], "auto-wallet-device")
        order_num = "auto-product-" + uuid.uuid4().hex
        request_data = {"amount": "60", "orderNum": order_num, "extra": "{}"}

        with patch.dict(os.environ, {}, clear=True):
            first = self.post_encrypted("/api/sdk/spend/create2", request_data, token=token)
            second = self.post_encrypted("/api/sdk/spend/create2", request_data, token=token)

        self.assertEqual(first["status"], "y")
        self.assertEqual(second["status"], "y")
        self.assertEqual(storage.wallet_balance(user["id"]), 0)
        orders = [row for row in storage.list_payment_orders(user["id"]) if row["order_num"] == order_num]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "duplicate")
        grants = storage.list_product_grants(user["id"])
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["total_quantity"], 40)
        transactions = storage.list_wallet_transactions(user["id"])
        self.assertEqual([row["transaction_type"] for row in transactions], ["auto_credit", "spend"])
        self.assertEqual(transactions[0]["amount"], 60)
        self.assertEqual(transactions[1]["amount"], -60)

    def test_spend_invalid_extra_is_preserved_without_crediting(self) -> None:
        login = self.post_encrypted(
            "/api/sdk/Login/account", {"username": "test", "password": "test1234"}
        )
        token = login["data"]["token"]
        order_num = "invalid-extra-" + uuid.uuid4().hex
        result = self.post_encrypted(
            "/api/sdk/spend/create2",
            {"orderNum": order_num, "extra": "not-json", "amount": "1"},
            token=token,
        )
        self.assertEqual(result["status"], "y")
        orders = [
            row for row in storage.list_payment_orders(login["data"]["userId"])
            if row["order_num"] == order_num
        ]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "unresolved")
        self.assertEqual(orders[0]["extra_raw"], "not-json")
        self.assertEqual(orders[0]["extra_json"], "null")

    def test_payment_endpoints_reject_invalid_token(self) -> None:
        paths = (
            "/api/sdk/UserProduct/getProductList",
            "/api/sdk/Recharge/create",
            "/api/sdk/Recharge/createAndSpend",
            "/api/sdk/spend/create2",
        )
        for path in paths:
            result = self.post_encrypted(path, {}, token="invalid-payment-token")
            self.assertEqual(result["status"], "n")
            self.assertEqual(result["errorCode"], "2002")

    def test_registration_and_invalid_token(self) -> None:
        username = "user_test_" + uuid.uuid4().hex[:10]
        registered = self.post_encrypted(
            "/api/sdk/Login/username", {"username": username, "password": "password1", "channel_code": "local"}
        )
        self.assertEqual(registered["status"], "y")
        self.assertEqual(registered["data"]["username"], username)

        invalid = self.post_encrypted("/api/sdk/user/validateToken", {}, token="invalid-token")
        self.assertEqual(invalid["status"], "n")
        self.assertEqual(invalid["errorCode"], "2002")

    def test_login_before_token_for_single_game_verify(self) -> None:
        result = self.post_encrypted(
            "/api/sdk/login/singleGameVerify",
            {"username": "test", "password": "test1234", "game_key": "local-game"},
        )
        self.assertEqual(result["status"], "y")
        self.assertTrue(result["data"]["token"])


class StorageTests(unittest.TestCase):
    def test_persistence_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "server.sqlite3"
            first = Storage(path)
            first.initialize()
            row = first.create_user("persisted", "secret")
            self.assertIsNotNone(row)
            token = first.issue_token(row["id"])

            second = Storage(path)
            self.assertIsNotNone(second.authenticate("persisted", "secret"))
            self.assertIsNotNone(second.get_session(token))

    def test_game_track_persistence_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "server.sqlite3"
            first = Storage(path)
            first.initialize()
            row = first.create_user("track_persisted", "secret")
            self.assertIsNotNone(row)
            event_id = first.record_game_track(row["id"], "persist-device", {"event": "persisted"})
            self.assertGreater(event_id, 0)

            second = Storage(path)
            tracks = second.list_game_tracks(row["id"])
            self.assertEqual(len(tracks), 1)
            self.assertEqual(tracks[0]["device_id"], "persist-device")
            self.assertEqual(tracks[0]["data_json"], '{"event":"persisted"}')

    def test_payment_order_persistence_and_user_isolation_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "server.sqlite3"
            first = Storage(path)
            first.initialize()
            user_one = first.create_user("payment_one", "secret")
            user_two = first.create_user("payment_two", "secret")
            self.assertIsNotNone(user_one)
            self.assertIsNotNone(user_two)

            order_one, duplicate_one = first.record_payment_order(
                user_one["id"],
                "device-one",
                {"orderNum": "same-order", "amount": "60", "extra": "{}"},
            )
            order_two, duplicate_two = first.record_payment_order(
                user_two["id"],
                "device-two",
                {"orderNum": "same-order", "amount": "60", "extra": "{}"},
            )
            self.assertFalse(duplicate_one)
            self.assertFalse(duplicate_two)
            self.assertNotEqual(order_one["id"], order_two["id"])

            second = Storage(path)
            orders = second.list_payment_orders()
            self.assertEqual(len(orders), 2)
            self.assertEqual({row["order_num"] for row in orders}, {"same-order"})
            self.assertEqual({row["device_id"] for row in orders}, {"device-one", "device-two"})

    def test_wallet_and_product_grant_persist_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "server.sqlite3"
            first = Storage(path)
            first.initialize()
            user = first.create_user("wallet_persisted", "secret")
            self.assertIsNotNone(user)
            first.credit_wallet(
                user["id"],
                60,
                reference_key="persist-credit",
                metadata={"source": "test"},
            )
            order, duplicate = first.record_payment_order(
                user["id"],
                "persist-device",
                {"orderNum": "persist-order", "amount": "60", "game_key": "local-game"},
            )
            self.assertFalse(duplicate)
            settlement = first.settle_payment_order(order["id"], resolve_product("60"))
            self.assertEqual(settlement["state"], "granted")

            second = Storage(path)
            self.assertEqual(second.wallet_balance(user["id"]), 0)
            grants = second.list_product_grants(user["id"])
            self.assertEqual(len(grants), 1)
            self.assertEqual(grants[0]["total_quantity"], 40)

    def test_list_users_returns_accounts_without_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "server.sqlite3")
            storage.initialize()
            storage.create_user("alice", "secret")
            storage.create_user("bob", "secret")

            rows = storage.list_users()
            usernames = {row["username"] for row in rows}
            self.assertTrue({"alice", "bob"} <= usernames)
            for row in rows:
                self.assertNotIn("password_salt", row.keys())
                self.assertNotIn("password_hash", row.keys())
                self.assertIn("id", row.keys())

    def test_set_password_updates_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "server.sqlite3")
            storage.initialize()
            storage.create_user("alice", "old-secret")

            self.assertIsNone(storage.authenticate("alice", "new-secret"))
            self.assertTrue(storage.set_password("alice", "new-secret"))
            self.assertIsNotNone(storage.authenticate("alice", "new-secret"))
            self.assertIsNone(storage.authenticate("alice", "old-secret"))
            self.assertFalse(storage.set_password("missing", "whatever"))


if __name__ == "__main__":
    unittest.main()
