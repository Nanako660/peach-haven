"""AES protocol helpers used by the APK's OkHttp interceptor."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


KEY = b"f237311e06398eac"
BLOCK_SIZE = 16


class ProtocolError(ValueError):
    """Raised when an encrypted request cannot be decoded."""


def _load_aes() -> Any:
    try:
        from Crypto.Cipher import AES

        return AES
    except ModuleNotFoundError as exc:
        # Keep the optional dependency inside the workspace as requested.
        dependency_dir = Path(__file__).resolve().parents[1] / ".tools" / "server_deps"
        if str(dependency_dir) not in sys.path:
            sys.path.insert(0, str(dependency_dir))
        try:
            from Crypto.Cipher import AES

            return AES
        except ModuleNotFoundError:
            raise ModuleNotFoundError(
                "PyCryptodome is not available; install it into .tools/server_deps"
            ) from exc


def _pad(value: bytes) -> bytes:
    padding = BLOCK_SIZE - (len(value) % BLOCK_SIZE)
    return value + bytes([padding]) * padding


def _unpad(value: bytes) -> bytes:
    if not value or len(value) % BLOCK_SIZE:
        raise ProtocolError("AES plaintext has an invalid length")
    padding = value[-1]
    if padding < 1 or padding > BLOCK_SIZE or value[-padding:] != bytes([padding]) * padding:
        raise ProtocolError("AES plaintext has invalid PKCS5/PKCS7 padding")
    return value[:-padding]


def encrypt_bytes(plaintext: bytes) -> bytes:
    aes = _load_aes()
    return aes.new(KEY, aes.MODE_ECB).encrypt(_pad(plaintext))


def decrypt_bytes(ciphertext: bytes) -> bytes:
    if not ciphertext or len(ciphertext) % BLOCK_SIZE:
        raise ProtocolError("AES ciphertext has an invalid length")
    aes = _load_aes()
    return _unpad(aes.new(KEY, aes.MODE_ECB).decrypt(ciphertext))


def encrypt_text(content: str) -> bytes:
    return encrypt_bytes(content.encode("utf-8"))


def decrypt_text(ciphertext: bytes) -> str:
    try:
        return decrypt_bytes(ciphertext).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("AES plaintext is not valid UTF-8") from exc


def encode_json(value: Any) -> bytes:
    """Serialize JSON like the Android JSONObject/Gson transport layer."""
    return encrypt_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def decode_json(ciphertext: bytes) -> Any:
    try:
        return json.loads(decrypt_text(ciphertext))
    except json.JSONDecodeError as exc:
        raise ProtocolError("AES plaintext is not valid JSON") from exc


def decode_request(ciphertext: bytes) -> dict[str, Any]:
    value = decode_json(ciphertext)
    if not isinstance(value, dict):
        raise ProtocolError("request envelope must be a JSON object")

    data = value.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ProtocolError("request envelope data must be a JSON object")

    return {
        "token": _string_or_empty(value.get("token")),
        "deviceId": _string_or_empty(value.get("deviceId")),
        "data": data,
    }


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)

