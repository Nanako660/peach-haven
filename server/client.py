"""Small standard-library client for exercising the encrypted local API."""

from __future__ import annotations

import argparse
import time
import urllib.request
from typing import Any

from .crypto import decode_json, encode_json
from .storage import Storage


class ApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080", device_id: str = "python-client"):
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.token = ""

    def request(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        envelope = {"token": self.token, "deviceId": self.device_id, "data": data or {}}
        request = urllib.request.Request(
            self.base_url + path,
            data=encode_json(envelope),
            method="POST",
            headers={"Content-Type": "application/octet-stream"},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return decode_json(response.read())

    def login(self, username: str, password: str, channel_code: str = "local") -> dict[str, Any]:
        result = self.request(
            "/api/sdk/Login/account",
            {"username": username, "password": password, "channel_code": channel_code},
        )
        if result.get("status") == "y":
            self.token = str(result.get("data", {}).get("token", ""))
        return result

    def game_track(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("/api/sdk/system/gameTrack", data or {})

    def create_spend(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("/api/sdk/spend/create2", data or {})

    def system_info(self) -> dict[str, Any]:
        return self.request("/api/sdk/system/info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise the local encrypted SDK API")
    parser.add_argument("--username", default="test")
    parser.add_argument("--password", default="test1234")
    parser.add_argument("--credit-g-points", type=int, default=0)
    parser.add_argument("--purchase-amount", type=int, default=1)
    args = parser.parse_args()

    if args.credit_g_points:
        if args.credit_g_points < 0:
            raise SystemExit("--credit-g-points must be non-negative")
        local_storage = Storage()
        local_storage.initialize()
        user = local_storage.authenticate(args.username, args.password)
        if user is None:
            raise SystemExit("invalid local account")
        balance = local_storage.credit_wallet(
            user["id"],
            args.credit_g_points,
            reference_key=f"client-credit:{user['id']}:{time.time_ns()}",
            metadata={"source": "server.client"},
        )
        print({"username": args.username, "credited": args.credit_g_points, "balance": balance})

    client = ApiClient()
    result = client.login(args.username, args.password)
    track = client.game_track({"event": "python-client-smoke-test"}) if client.token else {}
    order_num = f"python-client-smoke-{args.purchase_amount}-{time.time_ns()}"
    payment = (
        client.create_spend(
            {
                "amount": str(args.purchase_amount),
                "orderNum": order_num,
                "extra": '{"source":"python-client"}',
                "notifyUrl": "https://pxgame-api.showfifa.com/sdk/callback/18game/order",
            }
        )
        if client.token
        else {}
    )
    info = client.system_info() if client.token else {}
    print(
        {
            "login_status": result.get("status"),
            "has_token": bool(client.token),
            "game_track_status": track.get("status"),
            "payment_status": payment.get("status"),
            "payment_error_code": payment.get("errorCode"),
            "balance": info.get("data", {}).get("user", {}).get("balance"),
        }
    )
