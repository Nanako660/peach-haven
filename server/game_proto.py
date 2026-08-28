"""Minimal wire-compatible codec for the confirmed game TCP messages.

The client uses Google Protobuf, but the repository does not currently carry a
Python protobuf runtime.  This module works at the wire level and preserves
unknown fields when patching captured messages.
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass
from typing import Any, Iterable


HEADER_SIZE = 10
MAX_BODY_LENGTH = 0xFFFF


class ProtoError(ValueError):
    """Raised when a protobuf or TCP frame is malformed."""


@dataclass(frozen=True)
class Frame:
    body: bytes
    msg_id: int
    seq: int
    flag: int

    def to_json(self) -> dict[str, Any]:
        return {
            "msg_id": self.msg_id,
            "seq": self.seq,
            "flag": self.flag,
            "body_b64": base64.b64encode(self.body).decode("ascii"),
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "Frame":
        try:
            body = base64.b64decode(str(value["body_b64"]), validate=True)
            msg_id = int(value["msg_id"])
            seq = int(value.get("seq", 0))
            flag = int(value.get("flag", 0))
        except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
            raise ProtoError("invalid frame JSON") from exc
        if not 0 <= msg_id <= 0xFFFF or not 0 <= flag <= 0xFFFF:
            raise ProtoError("frame field out of range")
        if not -0x80000000 <= seq <= 0x7FFFFFFF:
            raise ProtoError("frame sequence out of range")
        if len(body) > MAX_BODY_LENGTH:
            raise ProtoError("frame body is too large")
        return cls(body=body, msg_id=msg_id, seq=seq, flag=flag)


def encode_frame(frame: Frame) -> bytes:
    if len(frame.body) > MAX_BODY_LENGTH:
        raise ProtoError("frame body is too large")
    return struct.pack(">HHiH", len(frame.body), frame.msg_id, frame.seq, frame.flag) + frame.body


def decode_frame(data: bytes) -> Frame:
    if len(data) < HEADER_SIZE:
        raise ProtoError("incomplete frame header")
    body_len, msg_id, seq, flag = struct.unpack(">HHiH", data[:HEADER_SIZE])
    if len(data) != HEADER_SIZE + body_len:
        raise ProtoError("frame length does not match header")
    return Frame(body=data[HEADER_SIZE:], msg_id=msg_id, seq=seq, flag=flag)


def _encode_varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift >= 70:
            break
    raise ProtoError("invalid protobuf varint")


@dataclass(frozen=True)
class Field:
    number: int
    wire_type: int
    value: int | bytes
    start: int
    end: int


def iter_fields(data: bytes) -> Iterable[Field]:
    offset = 0
    while offset < len(data):
        start = offset
        tag, offset = _decode_varint(data, offset)
        number = tag >> 3
        wire_type = tag & 7
        if number <= 0:
            raise ProtoError("invalid protobuf field number")
        if wire_type == 0:
            value, offset = _decode_varint(data, offset)
        elif wire_type == 1:
            if offset + 8 > len(data):
                raise ProtoError("truncated fixed64 field")
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = _decode_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ProtoError("truncated length-delimited field")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise ProtoError("truncated fixed32 field")
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise ProtoError(f"unsupported protobuf wire type {wire_type}")
        yield Field(number, wire_type, value, start, offset)


def _field_prefix(number: int, wire_type: int) -> bytes:
    if number <= 0:
        raise ProtoError("invalid protobuf field number")
    return _encode_varint((number << 3) | wire_type)


def encode_varint_field(number: int, value: int) -> bytes:
    return _field_prefix(number, 0) + _encode_varint(value)


def encode_bytes_field(number: int, value: bytes) -> bytes:
    return _field_prefix(number, 2) + _encode_varint(len(value)) + value


def encode_string_field(number: int, value: str) -> bytes:
    return encode_bytes_field(number, value.encode("utf-8"))


def _replace_field(data: bytes, number: int, replacement: bytes, *, wire_type: int | None = None) -> bytes:
    fields = list(iter_fields(data))
    for field in fields:
        if field.number == number and (wire_type is None or field.wire_type == wire_type):
            return data[: field.start] + replacement + data[field.end :]
    return data + replacement


def _get_field(data: bytes, number: int, wire_type: int | None = None) -> Field | None:
    for field in iter_fields(data):
        if field.number == number and (wire_type is None or field.wire_type == wire_type):
            return field
    return None


def get_varint(data: bytes, number: int, default: int = 0) -> int:
    field = _get_field(data, number, 0)
    return default if field is None else int(field.value)


def get_repeated_varints(data: bytes, number: int) -> list[int]:
    values: list[int] = []
    for field in iter_fields(data):
        if field.number != number:
            continue
        if field.wire_type == 0:
            values.append(int(field.value))
        elif field.wire_type == 2:
            packed = bytes(field.value)
            offset = 0
            while offset < len(packed):
                value, offset = _decode_varint(packed, offset)
                values.append(value)
    return values


def get_string(data: bytes, number: int, default: str = "") -> str:
    field = _get_field(data, number, 2)
    if field is None:
        return default
    try:
        return bytes(field.value).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtoError(f"field {number} is not valid UTF-8") from exc


def get_bytes(data: bytes, number: int) -> bytes | None:
    field = _get_field(data, number, 2)
    return None if field is None else bytes(field.value)


def get_bytes_all(data: bytes, number: int) -> list[bytes]:
    return [bytes(field.value) for field in iter_fields(data) if field.number == number and field.wire_type == 2]


def decode_string_map_field(data: bytes, number: int) -> dict[str, str]:
    values: dict[str, str] = {}
    for entry in get_bytes_all(data, number):
        key = get_string(entry, 1)
        if not key:
            continue
        values[key] = get_string(entry, 2)
    return values


def encode_string_map_field(number: int, values: dict[str, str]) -> bytes:
    result = bytearray()
    for key, value in values.items():
        entry = encode_string_field(1, str(key)) + encode_string_field(2, str(value))
        result += encode_bytes_field(number, entry)
    return bytes(result)


def _decode_map_entries(data: bytes, number: int) -> Iterable[tuple[int, bytes]]:
    for entry in get_bytes_all(data, number):
        yield get_varint(entry, 1), get_bytes(entry, 2) or b""


def decode_item_data(body: bytes) -> dict[str, int]:
    return {
        "id": get_varint(body, 1),
        "config_id": get_varint(body, 2),
        "quantity": get_varint(body, 3),
        "timestamp": get_varint(body, 4),
    }


def encode_item_data(item: dict[str, Any]) -> bytes:
    result = bytearray()
    item_id = int(item.get("id", item.get("item_id", 0)) or 0)
    config_id = int(item.get("config_id", 0) or 0)
    quantity = int(item.get("quantity", item.get("num", 0)) or 0)
    timestamp = int(item.get("timestamp", 0) or 0)
    if item_id:
        result += encode_varint_field(1, item_id)
    if config_id:
        result += encode_varint_field(2, config_id)
    if quantity:
        result += encode_varint_field(3, quantity)
    if timestamp:
        result += encode_varint_field(4, timestamp)
    return bytes(result)


def decode_role_bag(body: bytes) -> dict[str, Any]:
    items: dict[str, dict[str, int]] = {}
    for item_id, item_body in _decode_map_entries(body, 1):
        item = decode_item_data(item_body)
        if not item["id"]:
            item["id"] = item_id
        items[str(item_id)] = item
    return {"items": items, "next_item_id": get_varint(body, 2)}


def encode_role_bag(bag: dict[str, Any]) -> bytes:
    result = bytearray()
    items = bag.get("items") if isinstance(bag, dict) else None
    for raw_key, raw_item in (items.items() if isinstance(items, dict) else []):
        item = dict(raw_item) if isinstance(raw_item, dict) else {}
        item_id = int(item.get("id", item.get("item_id", raw_key)) or 0)
        if item_id <= 0 or int(item.get("quantity", item.get("num", 0)) or 0) <= 0:
            continue
        entry = encode_varint_field(1, item_id) + encode_bytes_field(2, encode_item_data(item))
        result += encode_bytes_field(1, entry)
    next_item_id = int((bag or {}).get("next_item_id", 0) or 0)
    if next_item_id:
        result += encode_varint_field(2, next_item_id)
    return bytes(result)


def decode_hero_data(body: bytes) -> dict[str, Any]:
    skills: list[dict[str, int]] = []
    for skill_body in get_bytes_all(body, 8):
        skills.append({"id": get_varint(skill_body, 1), "level": get_varint(skill_body, 2)})
    favor = get_bytes(body, 9) or b""
    return {
        "id": get_varint(body, 1),
        "level": get_varint(body, 3),
        "stage": get_varint(body, 4),
        "star": get_varint(body, 5),
        "equip_id": get_varint(body, 6),
        "skins": get_repeated_varints(body, 7),
        "skills": skills,
        "favor": {
            "exp": get_varint(favor, 1),
            "level": get_varint(favor, 2),
            "state": get_varint(favor, 3),
        },
        "status": get_varint(body, 12),
        "cur_skin": get_varint(body, 13),
    }


def encode_hero_data(hero: dict[str, Any]) -> bytes:
    result = bytearray()
    for field, key in ((1, "id"), (3, "level"), (4, "stage"), (5, "star"), (6, "equip_id"), (12, "status"), (13, "cur_skin")):
        value = int(hero.get(key, 0) or 0)
        if value:
            result += encode_varint_field(field, value)
    for skin in hero.get("skins", ()) if isinstance(hero.get("skins"), list) else ():
        result += encode_varint_field(7, int(skin))
    for skill in hero.get("skills", ()) if isinstance(hero.get("skills"), list) else ():
        skill_body = encode_varint_field(1, int(skill.get("id", 0) or 0)) + encode_varint_field(2, int(skill.get("level", 0) or 0))
        result += encode_bytes_field(8, skill_body)
    favor = hero.get("favor") if isinstance(hero.get("favor"), dict) else {}
    favor_body = bytearray()
    for field, key in ((1, "exp"), (2, "level"), (3, "state")):
        value = int(favor.get(key, 0) or 0)
        if value:
            favor_body += encode_varint_field(field, value)
    if favor_body:
        result += encode_bytes_field(9, bytes(favor_body))
    return bytes(result)


def decode_role_hero(body: bytes) -> dict[str, Any]:
    role_hero = get_bytes(body, 1) or body
    heroes: dict[str, dict[str, Any]] = {}
    lineups: dict[str, list[int]] = {}
    for hero_id, hero_body in _decode_map_entries(role_hero, 2):
        hero = decode_hero_data(hero_body)
        hero["id"] = hero.get("id") or hero_id
        heroes[str(hero_id)] = hero
    for lineup_id, lineup_body in _decode_map_entries(role_hero, 4):
        lineups[str(lineup_id)] = get_repeated_varints(lineup_body, 1)
    return {
        "heroes": heroes,
        "lineups": lineups,
        "active_id": get_varint(role_hero, 5),
    }


def _encode_map_entry(key: int, value: bytes) -> bytes:
    return encode_varint_field(1, key) + encode_bytes_field(2, value)


def encode_role_hero(
    heroes: dict[str, Any],
    lineups: dict[str, Any] | None = None,
    active_id: int = 0,
) -> bytes:
    result = bytearray()
    for raw_key, raw_hero in (heroes or {}).items():
        hero = dict(raw_hero) if isinstance(raw_hero, dict) else {}
        hero_id = int(hero.get("id", raw_key) or 0)
        if hero_id <= 0:
            continue
        result += encode_bytes_field(2, _encode_map_entry(hero_id, encode_hero_data(hero)))
    for raw_key, lineup in (lineups or {}).items():
        lineup_id = int(raw_key)
        if lineup_id <= 0 or not isinstance(lineup, list):
            continue
        lineup_body = b"".join(encode_varint_field(1, int(hero_id)) for hero_id in lineup)
        result += encode_bytes_field(4, _encode_map_entry(lineup_id, lineup_body))
    if active_id:
        result += encode_varint_field(5, int(active_id))
    return bytes(result)


def encode_startup_hero_ntf(
    heroes: dict[str, Any],
    lineups: dict[str, Any] | None = None,
    active_id: int = 0,
    replay_body: bytes | None = None,
) -> bytes:
    result = encode_bytes_field(1, encode_role_hero(heroes, lineups, active_id))
    if replay_body:
        result += encode_bytes_field(2, replay_body)
    return result


def encode_item_change_ntf(changes: dict[str, Any]) -> bytes:
    result = bytearray()
    for raw_key, raw_item in (changes or {}).items():
        item = dict(raw_item) if isinstance(raw_item, dict) else {}
        item_id = int(item.get("id", item.get("item_id", raw_key)) or 0)
        if item_id <= 0:
            continue
        result += encode_bytes_field(1, _encode_map_entry(item_id, encode_item_data(item)))
    return bytes(result)


def patch_varint(data: bytes, number: int, value: int) -> bytes:
    return _replace_field(data, number, encode_varint_field(number, value), wire_type=0)


def patch_bytes(data: bytes, number: int, value: bytes) -> bytes:
    return _replace_field(data, number, encode_bytes_field(number, value), wire_type=2)


def patch_string(data: bytes, number: int, value: str) -> bytes:
    return patch_bytes(data, number, value.encode("utf-8"))


def patch_role_base_diamond(role_base: bytes, diamond: int) -> bytes:
    # Confirmed by static analysis: RoleBase.Diamond is field 8.
    if diamond < 0:
        raise ProtoError("diamond cannot be negative")
    return patch_varint(role_base, 8, diamond)


def extract_role_base(startup_body: bytes) -> bytes:
    role_base = get_bytes(startup_body, 4)
    if role_base is None:
        raise ProtoError("startup message has no RoleBase field")
    return role_base


def extract_startup_parts(frames: Iterable[Frame]) -> tuple[bytes, bytes]:
    """Collect RoleBase and RoleBag from a possibly chunked 25-message sequence."""
    role_base: bytes | None = None
    role_bag: bytes | None = None
    for frame in frames:
        if frame.msg_id != 25:
            continue
        if role_base is None:
            role_base = get_bytes(frame.body, 4)
        if role_bag is None:
            role_bag = get_bytes(frame.body, 5)
        if role_base is not None and role_bag is not None:
            break
    if role_base is None:
        raise ProtoError("startup sequence has no RoleBase field")
    if role_bag is None:
        raise ProtoError("startup sequence has no RoleBag field")
    return role_base, role_bag


def patch_startup_diamond(startup_body: bytes, diamond: int) -> bytes:
    role_base = patch_role_base_diamond(extract_role_base(startup_body), diamond)
    return patch_bytes(startup_body, 4, role_base)


def patch_role_base_info(role_info_body: bytes, role_base: bytes, diamond: int) -> bytes:
    # Confirmed by static analysis: SCRoleBaseInfoNtf fields 2 and 3 are
    # Diamond and the complete RoleBase respectively.
    result = patch_varint(role_info_body, 2, diamond)
    return patch_bytes(result, 3, patch_role_base_diamond(role_base, diamond))


def decode_login_request(body: bytes) -> dict[str, Any]:
    return {
        "platform": get_string(body, 1),
        "system_type": get_varint(body, 2),
        "auth_token": get_string(body, 3),
        "open_id": get_string(body, 4),
        "auth_type": get_string(body, 5),
        "game_version": get_varint(body, 7),
        "ip": get_string(body, 8),
        "select_zone": get_varint(body, 9),
        "sub_platform": get_string(body, 10),
        "user_id": get_string(body, 11),
        "device_code": get_string(body, 12),
        "account": get_string(body, 13),
        "client_track_json": get_string(body, 14),
    }


def decode_order_request(body: bytes) -> dict[str, Any]:
    return {
        "platform": get_string(body, 1),
        "server_id": get_varint(body, 2),
        "shop_id": get_varint(body, 3),
        "goods_id": get_varint(body, 4),
        "quantity": get_varint(body, 5),
        "owner_key": get_string(body, 6),
    }


def decode_risk_bat_win_request(body: bytes) -> dict[str, Any]:
    return {
        "level_id": get_varint(body, 1),
        "is_win": bool(get_varint(body, 2)),
        "is_quit": get_varint(body, 3),
        "star": get_varint(body, 4),
        "battle_target": get_repeated_varints(body, 5),
    }


def decode_gacha_request(body: bytes) -> dict[str, Any]:
    return {"gacha_id": get_varint(body, 1), "gacha_num": get_varint(body, 2)}


def decode_hero_level_up_request(body: bytes) -> dict[str, Any]:
    return {"hero_id": get_varint(body, 1), "level_num": get_varint(body, 2)}


def encode_gacha_list_ack(gacha_ids: Iterable[int] = (1, 2, 5), error: int = 0) -> bytes:
    result = bytearray()
    if error:
        result += encode_varint_field(1, error)
    for gacha_id in gacha_ids:
        result += encode_bytes_field(2, encode_varint_field(1, int(gacha_id)))
    return bytes(result)


def _encode_gacha_item_list(config_id: int, quantity: int) -> bytes:
    item = encode_varint_field(1, config_id) + encode_varint_field(2, quantity)
    return encode_bytes_field(1, item)


def _encode_gacha_map_entry(key: int, value: bytes) -> bytes:
    return encode_varint_field(1, key) + encode_bytes_field(2, value)


def encode_gacha_ack(
    *,
    config_id: int,
    quantity: int = 1,
    gain_key: int = 51,
    gain_value: int = 3,
    error: int = 0,
) -> bytes:
    result = bytearray()
    if error:
        result += encode_varint_field(1, error)
    item_list = _encode_gacha_item_list(config_id, quantity)
    result += encode_bytes_field(2, _encode_gacha_map_entry(1, item_list))
    result += encode_bytes_field(2, _encode_gacha_map_entry(2, b""))
    result += encode_bytes_field(3, encode_varint_field(1, gain_key) + encode_varint_field(2, gain_value))
    result += encode_bytes_field(4, _encode_gacha_map_entry(1, item_list))
    result += encode_bytes_field(4, _encode_gacha_map_entry(2, b""))
    return bytes(result)


def encode_hero_change_ntf(hero_id: int, level: int = 1) -> bytes:
    hero = encode_varint_field(1, hero_id) + encode_varint_field(3, level)
    role_hero = encode_bytes_field(2, encode_varint_field(1, hero_id) + encode_bytes_field(2, hero))
    return encode_bytes_field(1, role_hero)


def encode_gacha_open_ntf(gacha_ids: Iterable[int]) -> bytes:
    result = bytearray()
    for gacha_id in gacha_ids:
        result += encode_varint_field(1, int(gacha_id))
    return bytes(result)


def encode_risk_bat_win_ack(error: int = 0, settlement: bytes | None = None) -> bytes:
    result = bytearray()
    if error:
        result += encode_varint_field(1, error)
    if settlement is not None:
        result += encode_bytes_field(2, settlement)
    return bytes(result)


def encode_risk_bat_settlement(*, is_win: bool, win_settlement: bytes | None = None) -> bytes:
    result = bytearray()
    if is_win:
        result += encode_varint_field(1, 1)
    if win_settlement is not None:
        result += encode_bytes_field(2, win_settlement)
    return bytes(result)


def encode_win_settlement(
    *,
    base_exp: int,
    hero_exp: int,
    coin: int,
    diamond: int,
    strength: int,
    exp_before: bytes | None = None,
    exp_after: bytes | None = None,
    item_list: Iterable[bytes] = (),
) -> bytes:
    result = bytearray()
    if exp_before is not None:
        result += encode_bytes_field(1, exp_before)
    if exp_after is not None:
        result += encode_bytes_field(2, exp_after)
    result += encode_varint_field(3, base_exp)
    result += encode_varint_field(4, hero_exp)
    result += encode_varint_field(5, coin)
    result += encode_varint_field(6, diamond)
    result += encode_varint_field(7, strength)
    for item in item_list:
        result += encode_bytes_field(8, item)
    return bytes(result)


def encode_role_strength_ntf(strength: int, max_strength: int = 100) -> bytes:
    role_strength = encode_varint_field(1, strength) + encode_varint_field(2, max_strength)
    return encode_bytes_field(1, role_strength)


def encode_risk_battle_ntf(level_id: int, last_level_id: int = 0) -> bytes:
    risk = encode_varint_field(1, level_id)
    if last_level_id:
        risk += encode_varint_field(2, last_level_id)
    return encode_bytes_field(1, risk)


def encode_role_strength(strength: int, max_strength: int = 100) -> bytes:
    """Encode the inner RoleStrength message used by SCStartupInfoNtf."""
    return encode_varint_field(1, strength) + encode_varint_field(2, max_strength)


def encode_role_risk_battle(risk_battle: dict[str, Any]) -> bytes:
    """Encode RoleRiskBattle from persisted risk battle state.

    The original startup carries an empty-but-present RoleRiskBattle
    (``Tower`` and ``StarReward`` as empty sub-messages).  Keeping those
    sub-messages present is important because the client's 149 settlement
    handler dereferences UserDataComponent.RoleRiskBattle without a null
    check.
    """
    result = bytearray()
    level_id = int(risk_battle.get("current_level") or 0)
    last_level_id = int(risk_battle.get("last_level_id") or 0)
    if level_id:
        result += encode_varint_field(1, level_id)
    if last_level_id:
        result += encode_varint_field(2, last_level_id)

    completed = risk_battle.get("completed") or {}
    stars = risk_battle.get("stars") or {}
    for level_key, value in completed.items():
        try:
            entry_level_id = int(level_key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            star = int(value.get("star") or 0)
        else:
            star = int(value or 0)
        if not star:
            star = int(stars.get(str(entry_level_id)) or 0)
        if entry_level_id and star:
            info = encode_varint_field(1, entry_level_id)
            if star:
                info += encode_varint_field(2, star)
            result += encode_bytes_field(3, encode_varint_field(1, entry_level_id) + encode_bytes_field(2, info))

    # Preserve the original empty sub-messages so the client sees a non-null
    # Tower and StarReward object.
    result += encode_bytes_field(6, b"")
    result += encode_bytes_field(7, b"")
    return bytes(result)



def encode_login_ack(error: int = 0, client_id: int = 0, ext_params: dict[str, str] | None = None) -> bytes:
    result = bytearray()
    if error:
        result += encode_varint_field(1, error)
    if client_id:
        result += encode_varint_field(2, client_id)
    for key, value in (ext_params or {}).items():
        entry = encode_string_field(1, key) + encode_string_field(2, value)
        result += encode_bytes_field(3, entry)
    return bytes(result)


def encode_risk_start_ack(level_id: int, error: int = 0) -> bytes:
    """Encode the level/error fields shared by risk battle start ACKs."""
    if level_id < 0 or error < 0:
        raise ProtoError("risk start ACK fields cannot be negative")
    result = bytearray()
    if level_id:
        result += encode_varint_field(1, level_id)
    if error:
        result += encode_varint_field(2, error)
    return bytes(result)


def encode_order_ack(
    order_no: int,
    notify_url: str,
    shop_id: int,
    goods_id: int,
    quantity: int,
    order_price: int,
    error: int = 0,
) -> bytes:
    result = bytearray()
    if error:
        result += encode_varint_field(1, error)
    result += encode_varint_field(2, order_no)
    if notify_url:
        result += encode_string_field(3, notify_url)
    result += encode_varint_field(4, shop_id)
    result += encode_varint_field(5, goods_id)
    result += encode_varint_field(6, quantity)
    result += encode_varint_field(7, order_price)
    return bytes(result)


def encode_role_info(role_base: bytes, diamond: int, coin: int = 0) -> bytes:
    result = bytearray()
    if coin:
        result += encode_varint_field(1, coin)
    result += encode_varint_field(2, diamond)
    result += encode_bytes_field(3, patch_role_base_diamond(role_base, diamond))
    return bytes(result)
