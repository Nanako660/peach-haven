"""SQLite persistence for local users and opaque token sessions."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import DEFAULT_DATA_DIR, DEFAULT_TOKEN_TTL_SECONDS as CONFIG_DEFAULT_TOKEN_TTL_SECONDS, load_settings
from .game_state import merge_role_state, role_base_from_wire
from .products import ProductSpec


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = DEFAULT_DATA_DIR
DATABASE_PATH = DATA_DIR / "server.sqlite3"
PBKDF2_ITERATIONS = 210_000
DEFAULT_TOKEN_TTL_SECONDS = CONFIG_DEFAULT_TOKEN_TTL_SECONDS


def _now() -> float:
    return time.time()


def _default_profile(username: str, channel_code: str = "") -> dict[str, Any]:
    return {
        "nickname": username,
        "headico": "",
        "sex": "unknown",
        "email": "",
        "check_email": "0",
        "channel_name": channel_code,
    }


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return salt.hex(), digest.hex()


def _verify_password(password: str, salt_hex: str, digest_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    ).hex()
    return hmac.compare_digest(candidate, digest_hex)


class Storage:
    def __init__(self, database_path: Path | None = None, token_ttl_seconds: int | None = None):
        if database_path is None or token_ttl_seconds is None:
            settings = load_settings()
            if database_path is None:
                database_path = settings.storage.database_path
            if token_ttl_seconds is None:
                token_ttl_seconds = settings.storage.token_ttl_seconds
        self.database_path = Path(database_path)
        self.token_ttl_seconds = int(token_ttl_seconds)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tokens_user_id ON tokens(user_id);
                CREATE INDEX IF NOT EXISTS idx_tokens_expires_at ON tokens(expires_at);
                CREATE TABLE IF NOT EXISTS game_tracks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL DEFAULT '',
                    data_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_game_tracks_user_id ON game_tracks(user_id);
                CREATE INDEX IF NOT EXISTS idx_game_tracks_created_at ON game_tracks(created_at);
                CREATE TABLE IF NOT EXISTS payment_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    device_id TEXT NOT NULL DEFAULT '',
                    dedupe_key TEXT NOT NULL,
                    order_num TEXT NOT NULL DEFAULT '',
                    order_no TEXT NOT NULL DEFAULT '',
                    game_key TEXT NOT NULL DEFAULT '',
                    amount TEXT NOT NULL DEFAULT '',
                    type TEXT NOT NULL DEFAULT '',
                    notify_url TEXT NOT NULL DEFAULT '',
                    extra_raw TEXT NOT NULL DEFAULT '',
                    extra_json TEXT NOT NULL DEFAULT 'null',
                    raw_data_json TEXT NOT NULL,
                    sign_fingerprint TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'unresolved',
                    status_reason TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(user_id, dedupe_key)
                );
                CREATE INDEX IF NOT EXISTS idx_payment_orders_user_id ON payment_orders(user_id);
                CREATE INDEX IF NOT EXISTS idx_payment_orders_order_num ON payment_orders(order_num);
                CREATE INDEX IF NOT EXISTS idx_payment_orders_created_at ON payment_orders(created_at);
                CREATE TABLE IF NOT EXISTS wallet_accounts (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    balance INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wallet_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    reference_key TEXT NOT NULL UNIQUE,
                    transaction_type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    balance_before INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_wallet_transactions_user_id
                    ON wallet_transactions(user_id);
                CREATE INDEX IF NOT EXISTS idx_wallet_transactions_created_at
                    ON wallet_transactions(created_at);
                CREATE TABLE IF NOT EXISTS product_grants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    payment_order_id INTEGER NOT NULL UNIQUE REFERENCES payment_orders(id) ON DELETE CASCADE,
                    game_key TEXT NOT NULL DEFAULT '',
                    product_id TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    base_quantity INTEGER NOT NULL,
                    bonus_quantity INTEGER NOT NULL DEFAULT 0,
                    total_quantity INTEGER NOT NULL,
                    first_purchase INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'granted',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_product_grants_user_id
                    ON product_grants(user_id);
                CREATE INDEX IF NOT EXISTS idx_product_grants_product_id
                    ON product_grants(product_id);
                CREATE TABLE IF NOT EXISTS game_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sdk_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    server_id INTEGER NOT NULL,
                    login_open_id TEXT NOT NULL DEFAULT '',
                    login_user_id TEXT NOT NULL,
                    game_uid TEXT NOT NULL,
                    fixture_name TEXT NOT NULL DEFAULT '',
                    startup_json TEXT NOT NULL,
                    role_base_blob BLOB NOT NULL,
                    role_bag_blob BLOB NOT NULL DEFAULT X'',
                    diamond INTEGER NOT NULL DEFAULT 0,
                    role_version INTEGER NOT NULL DEFAULT 0,
                    game_state_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(server_id, login_user_id),
                    UNIQUE(server_id, game_uid)
                );
                CREATE INDEX IF NOT EXISTS idx_game_roles_sdk_user_id ON game_roles(sdk_user_id);
                CREATE TABLE IF NOT EXISTS game_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES game_roles(id) ON DELETE CASCADE,
                    sdk_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    game_order_no TEXT NOT NULL UNIQUE,
                    server_id INTEGER NOT NULL,
                    shop_id INTEGER NOT NULL,
                    goods_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    order_price INTEGER NOT NULL,
                    product_id TEXT NOT NULL,
                    notify_url TEXT NOT NULL DEFAULT '',
                    payment_order_id INTEGER REFERENCES payment_orders(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_game_orders_role_id ON game_orders(role_id);
                CREATE INDEX IF NOT EXISTS idx_game_orders_sdk_user_id ON game_orders(sdk_user_id);
                CREATE TABLE IF NOT EXISTS game_diamond_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES game_roles(id) ON DELETE CASCADE,
                    game_order_id INTEGER NOT NULL UNIQUE REFERENCES game_orders(id) ON DELETE CASCADE,
                    payment_order_id INTEGER NOT NULL UNIQUE REFERENCES payment_orders(id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL,
                    base_quantity INTEGER NOT NULL,
                    bonus_quantity INTEGER NOT NULL DEFAULT 0,
                    total_quantity INTEGER NOT NULL,
                    first_purchase INTEGER NOT NULL DEFAULT 0,
                    balance_before INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_game_diamond_transactions_role_id
                    ON game_diamond_transactions(role_id);
                CREATE TABLE IF NOT EXISTS game_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role_id INTEGER NOT NULL REFERENCES game_roles(id) ON DELETE CASCADE,
                    game_order_id INTEGER NOT NULL REFERENCES game_orders(id) ON DELETE CASCADE,
                    role_version INTEGER NOT NULL,
                    event_type TEXT NOT NULL DEFAULT 'role_base_update',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    delivered_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_game_events_pending
                    ON game_events(status, id);
                """
            )
            payment_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(payment_orders)").fetchall()
            }
            if "status_reason" not in payment_columns:
                connection.execute(
                    "ALTER TABLE payment_orders ADD COLUMN status_reason TEXT NOT NULL DEFAULT ''"
                )
            role_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(game_roles)").fetchall()
            }
            if "login_open_id" not in role_columns:
                connection.execute(
                    "ALTER TABLE game_roles ADD COLUMN login_open_id TEXT NOT NULL DEFAULT ''"
                )
            if "game_state_json" not in role_columns:
                connection.execute(
                    "ALTER TABLE game_roles ADD COLUMN game_state_json TEXT NOT NULL DEFAULT '{}'"
                )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_game_roles_server_open_id
                ON game_roles(server_id, login_open_id)
                WHERE login_open_id <> ''
                """
            )
            connection.execute("PRAGMA user_version = 4")
            now = _now()
            connection.execute(
                """
                INSERT OR IGNORE INTO wallet_accounts(user_id, balance, updated_at)
                SELECT id, 0, ? FROM users
                """,
                (now,),
            )
            existing = connection.execute("SELECT id FROM users WHERE username = ?", ("test",)).fetchone()
            if existing is None:
                salt_hex, digest_hex = _hash_password("test1234")
                now = _now()
                connection.execute(
                    """
                    INSERT INTO users(username, password_salt, password_hash, profile_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "test",
                        salt_hex,
                        digest_hex,
                        json.dumps(_default_profile("test"), ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                user_id = connection.execute(
                    "SELECT id FROM users WHERE username = ?", ("test",)
                ).fetchone()["id"]
                connection.execute(
                    "INSERT OR IGNORE INTO wallet_accounts(user_id, balance, updated_at) VALUES (?, 0, ?)",
                    (user_id, now),
                )

    def create_user(self, username: str, password: str, channel_code: str = "") -> sqlite3.Row | None:
        username = username.strip()
        if not username or not password:
            return None
        salt_hex, digest_hex = _hash_password(password)
        now = _now()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO users(username, password_salt, password_hash, profile_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        salt_hex,
                        digest_hex,
                        json.dumps(_default_profile(username, channel_code), ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO wallet_accounts(user_id, balance, updated_at) VALUES (?, 0, ?)",
                    (cursor.lastrowid, now),
                )
                return connection.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            return None

    def authenticate(self, username: str, password: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)
            ).fetchone()
        if row is None or not _verify_password(password, row["password_salt"], row["password_hash"]):
            return None
        return row

    def get_user_by_id(self, user_id: int) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def list_users(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, username, profile_json, created_at, updated_at
                FROM users ORDER BY id
                """
            ).fetchall()
        return list(rows)

    def set_password(self, username: str, new_password: str) -> bool:
        username = username.strip()
        if not username or not new_password:
            return False
        salt_hex, digest_hex = _hash_password(new_password)
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE users SET password_salt = ?, password_hash = ?, updated_at = ?
                WHERE username = ? COLLATE NOCASE
                """,
                (salt_hex, digest_hex, now, username),
            )
        return cursor.rowcount > 0

    def issue_token(self, user_id: int, device_id: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tokens(token, user_id, device_id, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (token, user_id, device_id, now, now + self.token_ttl_seconds),
            )
        return token

    def get_session(self, token: str) -> tuple[sqlite3.Row, str] | None:
        if not token:
            return None
        now = _now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.*, tokens.token AS session_token, tokens.expires_at
                FROM tokens JOIN users ON users.id = tokens.user_id
                WHERE tokens.token = ?
                """,
                (token,),
            ).fetchone()
            canonical_token = token
            if row is None:
                base_token, separator, user_id_text = token.rpartition("_")
                if separator and base_token and user_id_text.isdigit():
                    row = connection.execute(
                        """
                        SELECT users.*, tokens.token AS session_token, tokens.expires_at
                        FROM tokens JOIN users ON users.id = tokens.user_id
                        WHERE tokens.token = ? AND tokens.user_id = ?
                        """,
                        (base_token, int(user_id_text)),
                    ).fetchone()
                    if row is not None:
                        canonical_token = base_token
            if row is not None and row["expires_at"] <= now:
                connection.execute("DELETE FROM tokens WHERE token = ?", (canonical_token,))
                row = None
        return (row, canonical_token) if row is not None else None

    def wallet_balance(self, user_id: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT balance FROM wallet_accounts WHERE user_id = ?", (user_id,)
            ).fetchone()
            return int(row["balance"]) if row is not None else 0

    def credit_wallet(
        self,
        user_id: int,
        amount: int,
        *,
        reference_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Credit G points through a local, explicit test/admin operation."""
        if amount <= 0:
            raise ValueError("wallet credit must be positive")
        now = _now()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            wallet = connection.execute(
                "SELECT balance FROM wallet_accounts WHERE user_id = ?", (user_id,)
            ).fetchone()
            if wallet is None:
                connection.execute(
                    "INSERT INTO wallet_accounts(user_id, balance, updated_at) VALUES (?, 0, ?)",
                    (user_id, now),
                )
                balance_before = 0
            else:
                balance_before = int(wallet["balance"])
            existing = connection.execute(
                "SELECT balance_after FROM wallet_transactions WHERE reference_key = ?",
                (reference_key,),
            ).fetchone()
            if existing is not None:
                return int(existing["balance_after"])
            balance_after = balance_before + amount
            connection.execute(
                "UPDATE wallet_accounts SET balance = ?, updated_at = ? WHERE user_id = ?",
                (balance_after, now, user_id),
            )
            connection.execute(
                """
                INSERT INTO wallet_transactions(
                    user_id, reference_key, transaction_type, amount,
                    balance_before, balance_after, metadata_json, created_at
                ) VALUES (?, ?, 'credit', ?, ?, ?, ?, ?)
                """,
                (user_id, reference_key, amount, balance_before, balance_after, metadata_json, now),
            )
            return balance_after

    def user_data(self, row: sqlite3.Row, token: str = "", purchased: bool = True) -> dict[str, Any]:
        try:
            profile = json.loads(row["profile_json"])
        except (TypeError, json.JSONDecodeError):
            profile = {}
        username = row["username"]
        return {
            "token": token,
            "userId": str(row["id"]),
            "user_id": str(row["id"]),
            "account": username,
            "username": username,
            "password": "",
            "nickname": profile.get("nickname") or username,
            "headico": profile.get("headico", ""),
            "email": profile.get("email", ""),
            "check_email": profile.get("check_email", "0"),
            # The APK's UserModelKt.isLoggedInFromSystemInfo() checks for "y".
            "has_login": "y",
            "parent_id": profile.get("parent_id", ""),
            "sex": profile.get("sex", "unknown"),
            "balance": str(self.wallet_balance(row["id"])),
            "point": 0,
            "is_vip": "1" if purchased else "0",
            "nickname_changed_30": 0,
            "preference_value": {
                "category": [],
                "game_state": [],
                "pay": [],
                "platform": [],
                "publisher": [],
                "sexual_orientation": [],
                "type": [],
            },
            "share_info": None,
            "group_id": "",
            "group_name": "",
            "group_end_time": "",
            "open_customer": 0,
            "is_download_vip": 0,
            "download_num": 0,
            "download_vip_group_id": 0,
            "download_remain_num": 0,
            "download_vip_end_time": "",
            "download_vip_group_name": "",
            "channel_name": profile.get("channel_name", ""),
            "parent_name": "",
            "jp_customer_open": "",
            "return_product": {
                "can_buy": False,
                "effective_time": "",
                "num": "0",
                "price": "0",
                "product_id": "",
            },
            "expire": "",
            "vip_bg_image": "",
            "vip_end_time_text": "",
            "vip_received_coin": "",
            "h5_community_url": "",
            "game_info": None,
        }

    def update_profile(self, token: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        session = self.get_session(token)
        if session is None:
            return None
        row, _ = session
        try:
            profile = json.loads(row["profile_json"])
        except (TypeError, json.JSONDecodeError):
            profile = {}
        allowed = {"nickname", "sex", "headico", "email", "check_email", "channel_name", "parent_id"}
        for key, value in updates.items():
            if key in allowed and value is not None:
                profile[key] = str(value)
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET profile_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(profile, ensure_ascii=False), now, row["id"]),
            )
            updated = connection.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        return self.user_data(updated, token=token)

    def settle_payment_order(
        self,
        order_id: int,
        product: ProductSpec,
        *,
        auto_credit_g_points: bool = False,
    ) -> dict[str, Any]:
        """Atomically top up, debit G points, and create one game product grant."""
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            order = connection.execute(
                "SELECT * FROM payment_orders WHERE id = ?", (order_id,)
            ).fetchone()
            if order is None:
                raise ValueError(f"payment order {order_id} does not exist")

            wallet = connection.execute(
                "SELECT balance FROM wallet_accounts WHERE user_id = ?", (order["user_id"],)
            ).fetchone()
            if wallet is None:
                connection.execute(
                    "INSERT INTO wallet_accounts(user_id, balance, updated_at) VALUES (?, 0, ?)",
                    (order["user_id"], now),
                )
                balance = 0
            else:
                balance = int(wallet["balance"])
            balance_before_auto_credit = balance

            grant = connection.execute(
                "SELECT * FROM product_grants WHERE payment_order_id = ?", (order_id,)
            ).fetchone()
            if grant is not None:
                return {
                    "state": "already_granted",
                    "balance_before": balance,
                    "balance_after": balance,
                    "auto_credit_amount": 0,
                    "grant": grant,
                }

            auto_credit_amount = 0
            if balance < product.price:
                if not auto_credit_g_points:
                    connection.execute(
                        "UPDATE payment_orders SET status = 'insufficient_balance', updated_at = ? WHERE id = ?",
                        (now, order_id),
                    )
                    return {
                        "state": "insufficient_balance",
                        "balance_before": balance,
                        "balance_after": balance,
                        "auto_credit_amount": 0,
                        "grant": None,
                    }

                auto_credit_amount = product.price - balance
                balance_after_credit = balance + auto_credit_amount
                credit_metadata = json.dumps(
                    {
                        "order_num": order["order_num"],
                        "product_id": product.product_id,
                        "source": "auto_credit_before_spend",
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                connection.execute(
                    "UPDATE wallet_accounts SET balance = ?, updated_at = ? WHERE user_id = ?",
                    (balance_after_credit, now, order["user_id"]),
                )
                connection.execute(
                    """
                    INSERT INTO wallet_transactions(
                        user_id, reference_key, transaction_type, amount,
                        balance_before, balance_after, metadata_json, created_at
                    ) VALUES (?, ?, 'auto_credit', ?, ?, ?, ?, ?)
                    """,
                    (
                        order["user_id"],
                        f"payment-order:{order_id}:auto-credit",
                        auto_credit_amount,
                        balance,
                        balance_after_credit,
                        credit_metadata,
                        now,
                    ),
                )
                balance = balance_after_credit

            prior_purchase = connection.execute(
                """
                SELECT 1 FROM product_grants
                WHERE user_id = ? AND product_id = ? AND status = 'granted'
                LIMIT 1
                """,
                (order["user_id"], product.product_id),
            ).fetchone()
            first_purchase = prior_purchase is None
            bonus_quantity = product.first_purchase_bonus if first_purchase else 0
            total_quantity = product.quantity + bonus_quantity
            balance_after = balance - product.price
            reference_key = f"payment-order:{order_id}:debit"
            metadata = json.dumps(
                {
                    "order_num": order["order_num"],
                    "product_id": product.product_id,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            connection.execute(
                "UPDATE wallet_accounts SET balance = ?, updated_at = ? WHERE user_id = ?",
                (balance_after, now, order["user_id"]),
            )
            connection.execute(
                """
                INSERT INTO wallet_transactions(
                    user_id, reference_key, transaction_type, amount,
                    balance_before, balance_after, metadata_json, created_at
                ) VALUES (?, ?, 'spend', ?, ?, ?, ?, ?)
                """,
                (
                    order["user_id"],
                    reference_key,
                    -product.price,
                    balance,
                    balance_after,
                    metadata,
                    now,
                ),
            )
            cursor = connection.execute(
                """
                INSERT INTO product_grants(
                    user_id, payment_order_id, game_key, product_id, price,
                    base_quantity, bonus_quantity, total_quantity, first_purchase,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'granted', ?)
                """,
                (
                    order["user_id"],
                    order_id,
                    order["game_key"],
                    product.product_id,
                    product.price,
                    product.quantity,
                    bonus_quantity,
                    total_quantity,
                    int(first_purchase),
                    now,
                ),
            )
            connection.execute(
                "UPDATE payment_orders SET status = 'completed', updated_at = ? WHERE id = ?",
                (now, order_id),
            )
            grant = connection.execute(
                "SELECT * FROM product_grants WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return {
                "state": "granted",
                "balance_before": balance,
                "balance_after": balance_after,
                "balance_before_auto_credit": balance_before_auto_credit,
                "auto_credit_amount": auto_credit_amount,
                "grant": grant,
            }

    def list_wallet_transactions(self, user_id: int | None = None) -> list[sqlite3.Row]:
        with self._connect() as connection:
            if user_id is None:
                return connection.execute(
                    "SELECT * FROM wallet_transactions ORDER BY id"
                ).fetchall()
            return connection.execute(
                "SELECT * FROM wallet_transactions WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()

    def list_product_grants(self, user_id: int | None = None) -> list[sqlite3.Row]:
        with self._connect() as connection:
            if user_id is None:
                return connection.execute(
                    "SELECT * FROM product_grants ORDER BY id"
                ).fetchall()
            return connection.execute(
                "SELECT * FROM product_grants WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()

    def record_game_track(self, user_id: int, device_id: str, data: dict[str, Any]) -> int:
        now = _now()
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO game_tracks(user_id, device_id, data_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, str(device_id or ""), payload, now),
            )
            return int(cursor.lastrowid)

    def list_game_tracks(self, user_id: int | None = None) -> list[sqlite3.Row]:
        with self._connect() as connection:
            if user_id is None:
                rows = connection.execute(
                    "SELECT * FROM game_tracks ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM game_tracks WHERE user_id = ? ORDER BY id",
                    (user_id,),
                ).fetchall()
        return rows

    def ensure_game_role(
        self,
        *,
        sdk_user_id: int,
        server_id: int,
        login_user_id: str,
        game_uid: str,
        fixture_name: str,
        startup_json: str,
        role_base_blob: bytes,
        login_open_id: str = "",
        role_bag_blob: bytes = b"",
        initial_diamond: int = 0,
        preserve_existing_state: bool = True,
    ) -> sqlite3.Row:
        """Create a role or refresh its identity without resetting persisted state."""
        login_open_id = str(login_open_id or "")
        login_user_id = str(login_user_id or "")
        if sdk_user_id <= 0 or server_id <= 0 or (not login_open_id and not login_user_id) or not game_uid:
            raise ValueError("invalid game role identity")
        now = _now()
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT * FROM game_roles
                WHERE (server_id = ? AND login_open_id <> '' AND login_open_id = ?)
                   OR (server_id = ? AND login_user_id <> '' AND login_user_id = ?)
                   OR (server_id = ? AND game_uid = ?)
                ORDER BY id LIMIT 1
                """,
                (server_id, login_open_id, server_id, login_user_id, server_id, game_uid),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """
                    INSERT INTO game_roles(
                        sdk_user_id, server_id, login_open_id, login_user_id, game_uid,
                        fixture_name, startup_json, role_base_blob, role_bag_blob,
                        diamond, role_version, game_state_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '{}', ?, ?)
                    """,
                    (
                        sdk_user_id,
                        server_id,
                        login_open_id,
                        login_user_id,
                        game_uid,
                        fixture_name,
                        startup_json,
                        sqlite3.Binary(role_base_blob),
                        sqlite3.Binary(role_bag_blob),
                        max(0, initial_diamond),
                        now,
                        now,
                    ),
                )
                return connection.execute(
                    "SELECT * FROM game_roles WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
            if preserve_existing_state:
                connection.execute(
                    """
                    UPDATE game_roles
                    SET sdk_user_id = ?, login_open_id = ?, login_user_id = ?, game_uid = ?,
                        fixture_name = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        sdk_user_id,
                        login_open_id,
                        login_user_id,
                        game_uid,
                        fixture_name,
                        now,
                        existing["id"],
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE game_roles
                    SET sdk_user_id = ?, login_open_id = ?, login_user_id = ?, game_uid = ?,
                        fixture_name = ?, startup_json = ?, role_base_blob = ?,
                        role_bag_blob = ?, diamond = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        sdk_user_id,
                        login_open_id,
                        login_user_id,
                        game_uid,
                        fixture_name,
                        startup_json,
                        sqlite3.Binary(role_base_blob),
                        sqlite3.Binary(role_bag_blob),
                        max(0, initial_diamond),
                        now,
                        existing["id"],
                    ),
                )
                try:
                    current_state = json.loads(str(existing["game_state_json"] or "{}"))
                except (TypeError, json.JSONDecodeError):
                    current_state = {}
                migrated_state = merge_role_state(
                    current_state,
                    {"role_base": role_base_from_wire(role_base_blob)},
                )
                connection.execute(
                    "UPDATE game_roles SET game_state_json = ? WHERE id = ?",
                    (
                        json.dumps(migrated_state, ensure_ascii=False, separators=(",", ":")),
                        existing["id"],
                    ),
                )
            return connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (existing["id"],)
            ).fetchone()

    def get_game_role_by_identity(
        self,
        server_id: int,
        *,
        login_open_id: str = "",
        login_user_id: str = "",
    ) -> sqlite3.Row | None:
        """Find a role by authenticated OpenId, falling back to legacy UserId."""
        with self._connect() as connection:
            if login_open_id:
                row = connection.execute(
                    "SELECT * FROM game_roles WHERE server_id = ? AND login_open_id = ?",
                    (server_id, str(login_open_id)),
                ).fetchone()
                if row is not None:
                    return row
            if login_user_id:
                return connection.execute(
                    "SELECT * FROM game_roles WHERE server_id = ? AND login_user_id = ?",
                    (server_id, str(login_user_id)),
                ).fetchone()
        return None

    def get_game_role_by_login(self, server_id: int, login_user_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM game_roles WHERE server_id = ? AND login_user_id = ?",
                (server_id, str(login_user_id)),
            ).fetchone()

    def get_game_role(self, role_id: int) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM game_roles WHERE id = ?", (role_id,)).fetchone()

    def update_game_role_base_blob(
        self,
        role_id: int,
        role_base_blob: bytes,
        *,
        increment_version: bool = True,
    ) -> sqlite3.Row:
        """Persist a complete RoleBase blob without changing the diamond ledger."""
        now = _now()
        with self._connect() as connection:
            role = connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()
            if role is None:
                raise ValueError("game role does not exist")
            role_version = int(role["role_version"]) + (1 if increment_version else 0)
            connection.execute(
                """
                UPDATE game_roles
                SET role_base_blob = ?, role_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (sqlite3.Binary(role_base_blob), role_version, now, role_id),
            )
            return connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()

    def get_game_state(self, role_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT game_state_json FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()
        if row is None:
            raise ValueError("game role does not exist")
        try:
            value = json.loads(str(row["game_state_json"] or "{}"))
        except json.JSONDecodeError:
            value = {}
        return value if isinstance(value, dict) else {}

    def update_game_state(
        self,
        role_id: int,
        state: dict[str, Any],
        *,
        increment_version: bool = True,
    ) -> sqlite3.Row:
        now = _now()
        serialized = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            role = connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()
            if role is None:
                raise ValueError("game role does not exist")
            role_version = int(role["role_version"]) + (1 if increment_version else 0)
            connection.execute(
                """
                UPDATE game_roles
                SET game_state_json = ?, role_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (serialized, role_version, now, role_id),
            )
            return connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()

    def merge_game_state(
        self,
        role_id: int,
        patch: dict[str, Any],
        *,
        role_base_blob: bytes | None = None,
        role_bag_blob: bytes | None = None,
        diamond: int | None = None,
        increment_version: bool = True,
    ) -> sqlite3.Row:
        """Apply a field-level role patch in one SQLite write."""
        now = _now()
        with self._connect() as connection:
            role = connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()
            if role is None:
                raise ValueError("game role does not exist")
            try:
                current = json.loads(str(role["game_state_json"] or "{}"))
            except (TypeError, json.JSONDecodeError):
                current = {}
            merged = merge_role_state(current, patch)
            next_version = int(role["role_version"]) + (1 if increment_version else 0)
            next_base = role["role_base_blob"] if role_base_blob is None else sqlite3.Binary(role_base_blob)
            next_bag = role["role_bag_blob"] if role_bag_blob is None else sqlite3.Binary(role_bag_blob)
            next_diamond = int(role["diamond"]) if diamond is None else max(0, int(diamond))
            connection.execute(
                """
                UPDATE game_roles
                SET game_state_json = ?, role_base_blob = ?, role_bag_blob = ?,
                    diamond = ?, role_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(merged, ensure_ascii=False, separators=(",", ":")),
                    next_base,
                    next_bag,
                    next_diamond,
                    next_version,
                    now,
                    role_id,
                ),
            )
            return connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()

    def update_game_role_progress(
        self,
        role_id: int,
        *,
        state: dict[str, Any],
        role_base_blob: bytes | None = None,
        diamond: int | None = None,
    ) -> sqlite3.Row:
        now = _now()
        serialized = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            role = connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()
            if role is None:
                raise ValueError("game role does not exist")
            next_diamond = int(role["diamond"]) if diamond is None else max(0, int(diamond))
            next_role_base = role["role_base_blob"] if role_base_blob is None else sqlite3.Binary(role_base_blob)
            connection.execute(
                """
                UPDATE game_roles
                SET game_state_json = ?, role_base_blob = ?, diamond = ?,
                    role_version = role_version + 1, updated_at = ?
                WHERE id = ?
                """,
                (serialized, next_role_base, next_diamond, now, role_id),
            )
            return connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (role_id,)
            ).fetchone()

    def create_game_order(
        self,
        *,
        role_id: int,
        game_order_no: str,
        server_id: int,
        shop_id: int,
        goods_id: int,
        quantity: int,
        order_price: int,
        product_id: str,
        notify_url: str = "",
    ) -> tuple[sqlite3.Row, bool]:
        if not game_order_no or quantity <= 0 or order_price <= 0:
            raise ValueError("invalid game order")
        now = _now()
        with self._connect() as connection:
            role = connection.execute("SELECT * FROM game_roles WHERE id = ?", (role_id,)).fetchone()
            if role is None:
                raise ValueError("game role does not exist")
            existing = connection.execute(
                "SELECT * FROM game_orders WHERE game_order_no = ?", (game_order_no,)
            ).fetchone()
            if existing is not None:
                if existing["role_id"] != role_id:
                    raise ValueError("game order belongs to another role")
                return existing, True
            cursor = connection.execute(
                """
                INSERT INTO game_orders(
                    role_id, sdk_user_id, game_order_no, server_id, shop_id,
                    goods_id, quantity, order_price, product_id, notify_url,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    role_id,
                    role["sdk_user_id"],
                    game_order_no,
                    server_id,
                    shop_id,
                    goods_id,
                    quantity,
                    order_price,
                    product_id,
                    notify_url,
                    now,
                    now,
                ),
            )
            return connection.execute(
                "SELECT * FROM game_orders WHERE id = ?", (cursor.lastrowid,)
            ).fetchone(), False

    def find_game_order_for_payment(
        self,
        sdk_user_id: int,
        order_num: str = "",
        extra_order_no: str = "",
    ) -> sqlite3.Row | None:
        candidates = [value for value in (str(order_num or ""), str(extra_order_no or "")) if value]
        if not candidates:
            return None
        placeholders = ",".join("?" for _ in candidates)
        with self._connect() as connection:
            return connection.execute(
                f"""
                SELECT * FROM game_orders
                WHERE sdk_user_id = ? AND game_order_no IN ({placeholders})
                ORDER BY id LIMIT 1
                """,
                (sdk_user_id, *candidates),
            ).fetchone()

    def settle_game_payment(
        self,
        *,
        game_order_id: int,
        payment_order_id: int,
        product: ProductSpec,
    ) -> dict[str, Any]:
        """Atomically apply a game diamond grant and enqueue its online update."""
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            order = connection.execute(
                "SELECT * FROM game_orders WHERE id = ?", (game_order_id,)
            ).fetchone()
            payment = connection.execute(
                "SELECT * FROM payment_orders WHERE id = ?", (payment_order_id,)
            ).fetchone()
            if order is None or payment is None:
                raise ValueError("game or payment order does not exist")
            if order["sdk_user_id"] != payment["user_id"]:
                return {"state": "rejected", "reason": "sdk user mismatch"}
            if order["product_id"] != product.product_id or order["order_price"] != product.price:
                return {"state": "rejected", "reason": "product mismatch"}
            existing = connection.execute(
                "SELECT * FROM game_diamond_transactions WHERE game_order_id = ?",
                (game_order_id,),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    "UPDATE payment_orders SET status = 'completed', updated_at = ? WHERE id = ?",
                    (now, payment_order_id),
                )
                return {
                    "state": "already_granted",
                    "diamond_before": existing["balance_before"],
                    "diamond_after": existing["balance_after"],
                    "transaction": existing,
                }
            if order["payment_order_id"] not in (None, payment_order_id):
                return {"state": "rejected", "reason": "payment order mismatch"}

            role = connection.execute(
                "SELECT * FROM game_roles WHERE id = ?", (order["role_id"],)
            ).fetchone()
            if role is None:
                raise ValueError("game role does not exist")
            prior = connection.execute(
                """
                SELECT 1 FROM game_diamond_transactions
                WHERE role_id = ? AND product_id = ?
                LIMIT 1
                """,
                (role["id"], product.product_id),
            ).fetchone()
            first_purchase = prior is None
            bonus_quantity = product.first_purchase_bonus if first_purchase else 0
            total_quantity = product.quantity + bonus_quantity
            balance_before = int(role["diamond"])
            balance_after = balance_before + total_quantity
            role_version = int(role["role_version"]) + 1
            try:
                game_state = json.loads(str(role["game_state_json"] or "{}"))
            except (KeyError, TypeError, json.JSONDecodeError):
                game_state = {}
            if not isinstance(game_state, dict):
                game_state = {}
            game_state = merge_role_state(game_state, {"diamond": balance_after})
            connection.execute(
                """
                UPDATE game_roles
                SET diamond = ?, game_state_json = ?, role_version = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    balance_after,
                    json.dumps(game_state, ensure_ascii=False, separators=(",", ":")),
                    role_version,
                    now,
                    role["id"],
                ),
            )
            cursor = connection.execute(
                """
                INSERT INTO game_diamond_transactions(
                    role_id, game_order_id, payment_order_id, product_id,
                    base_quantity, bonus_quantity, total_quantity, first_purchase,
                    balance_before, balance_after, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    role["id"],
                    game_order_id,
                    payment_order_id,
                    product.product_id,
                    product.quantity,
                    bonus_quantity,
                    total_quantity,
                    int(first_purchase),
                    balance_before,
                    balance_after,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE game_orders
                SET payment_order_id = ?, status = 'completed', updated_at = ?
                WHERE id = ?
                """,
                (payment_order_id, now, game_order_id),
            )
            connection.execute(
                "UPDATE payment_orders SET status = 'completed', updated_at = ? WHERE id = ?",
                (now, payment_order_id),
            )
            event_cursor = connection.execute(
                """
                INSERT INTO game_events(role_id, game_order_id, role_version, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (role["id"], game_order_id, role_version, now),
            )
            transaction = connection.execute(
                "SELECT * FROM game_diamond_transactions WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return {
                "state": "granted",
                "diamond_before": balance_before,
                "diamond_after": balance_after,
                "role_version": role_version,
                "event_id": int(event_cursor.lastrowid),
                "transaction": transaction,
            }

    def list_pending_game_events(self, limit: int = 100) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT e.*, r.sdk_user_id, r.server_id, r.login_user_id,
                       r.game_uid, r.diamond, r.role_base_blob
                FROM game_events e
                JOIN game_roles r ON r.id = e.role_id
                WHERE e.status = 'pending'
                ORDER BY e.id LIMIT ?
                """,
                (max(1, min(limit, 1000)),),
            ).fetchall()

    def mark_payment_order_rejected(self, payment_order_id: int, reason: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE payment_orders
                SET status = 'rejected', status_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(reason), _now(), payment_order_id),
            )

    def mark_game_event_delivered(self, event_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE game_events
                SET status = 'delivered', delivered_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (_now(), event_id),
            )

    def mark_role_events_delivered(self, role_id: int, role_version: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE game_events
                SET status = 'delivered', delivered_at = ?
                WHERE role_id = ? AND role_version <= ? AND status = 'pending'
                """,
                (_now(), role_id, role_version),
            )

    def list_game_diamond_transactions(self, role_id: int | None = None) -> list[sqlite3.Row]:
        with self._connect() as connection:
            if role_id is None:
                return connection.execute(
                    "SELECT * FROM game_diamond_transactions ORDER BY id"
                ).fetchall()
            return connection.execute(
                "SELECT * FROM game_diamond_transactions WHERE role_id = ? ORDER BY id",
                (role_id,),
            ).fetchall()

    def record_payment_order(
        self,
        user_id: int,
        device_id: str,
        data: dict[str, Any],
    ) -> tuple[sqlite3.Row, bool]:
        """Persist one opaque payment request without granting any entitlement."""
        now = _now()
        order_num = str(data.get("orderNum") or data.get("order_num") or "")
        order_no = str(data.get("orderNo") or data.get("order_no") or "")
        game_key = str(data.get("game_key") or data.get("gameKey") or "")
        amount = str(data.get("amount") or "")
        payment_type = str(data.get("type") or "")
        notify_url = str(data.get("notifyUrl") or data.get("notify_url") or "")
        sign = str(data.get("sign") or "")

        extra_value = data.get("extra", "")
        if isinstance(extra_value, str):
            extra_raw = extra_value
            try:
                extra_parsed: Any = json.loads(extra_value)
            except (TypeError, json.JSONDecodeError):
                extra_parsed = None
        else:
            extra_raw = json.dumps(extra_value, ensure_ascii=False, separators=(",", ":"))
            extra_parsed = extra_value

        raw_data_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        dedupe_key = order_num or hashlib.sha256(raw_data_json.encode("utf-8")).hexdigest()
        sign_fingerprint = hashlib.sha256(sign.encode("utf-8")).hexdigest()[:12] if sign else ""
        values = (
            user_id,
            str(device_id or ""),
            dedupe_key,
            order_num,
            order_no,
            game_key,
            amount,
            payment_type,
            notify_url,
            extra_raw,
            json.dumps(extra_parsed, ensure_ascii=False, separators=(",", ":")),
            raw_data_json,
            sign_fingerprint,
            now,
            now,
        )

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM payment_orders WHERE user_id = ? AND dedupe_key = ?",
                (user_id, dedupe_key),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE payment_orders
                    SET updated_at = ?, request_count = request_count + 1, status = 'duplicate'
                    WHERE id = ?
                    """,
                    (now, existing["id"]),
                )
                row = connection.execute(
                    "SELECT * FROM payment_orders WHERE id = ?", (existing["id"],)
                ).fetchone()
                return row, True

            cursor = connection.execute(
                """
                INSERT INTO payment_orders(
                    user_id, device_id, dedupe_key, order_num, order_no, game_key,
                    amount, type, notify_url, extra_raw, extra_json, raw_data_json,
                    sign_fingerprint, status, created_at, updated_at, request_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unresolved', ?, ?, 1)
                """,
                values,
            )
            row = connection.execute(
                "SELECT * FROM payment_orders WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return row, False

    def list_payment_orders(self, user_id: int | None = None) -> list[sqlite3.Row]:
        with self._connect() as connection:
            if user_id is None:
                rows = connection.execute(
                    "SELECT * FROM payment_orders ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM payment_orders WHERE user_id = ? ORDER BY id",
                    (user_id,),
                ).fetchall()
        return rows
