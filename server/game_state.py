"""Versioned, field-oriented state model for one game role.

The game protocol contains many partially recovered messages.  This module
keeps confirmed role data structured while allowing unknown wire payloads to
remain opaque until their schema is confirmed.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import time
from typing import Any, Iterable

from .game_proto import (
    ProtoError,
    decode_role_bag,
    decode_role_hero,
    get_bytes,
    get_string,
    get_varint,
    patch_bytes,
    patch_role_base_diamond,
    patch_string,
    patch_varint,
)


STATE_SCHEMA_VERSION = 1
MAX_OPERATION_RECEIPTS = 256


def _int(value: Any, default: int = 0, minimum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _wire_b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii") if value else ""


def _default_role_base(role_base_blob: bytes) -> dict[str, Any]:
    exp = get_bytes(role_base_blob, 9) or b""
    return {
        "uid": get_varint(role_base_blob, 1),
        "nickname": get_string(role_base_blob, 2),
        "signature": get_string(role_base_blob, 3),
        "gender": get_varint(role_base_blob, 4),
        "level": get_varint(exp, 1),
        "exp": get_varint(exp, 2),
        "max_level": get_varint(exp, 3),
        "total_exp": get_varint(exp, 4),
        "coin": get_varint(role_base_blob, 7),
        "diamond": get_varint(role_base_blob, 8),
        "hero_exp": get_varint(role_base_blob, 26),
        "head_id": get_varint(role_base_blob, 16),
        "area_id": get_varint(role_base_blob, 29),
        "daily_reset_at": get_varint(role_base_blob, 130),
        "online_stamp": get_varint(role_base_blob, 149),
        "offline_stamp": get_varint(role_base_blob, 150),
        "week_reset_at": get_varint(role_base_blob, 153),
    }


def role_base_from_wire(role_base_blob: bytes) -> dict[str, Any]:
    """Decode the confirmed RoleBase scalar fields for fixture migration."""
    return _default_role_base(role_base_blob)


def _default_bag(role_bag_blob: bytes) -> dict[str, Any]:
    try:
        bag = decode_role_bag(role_bag_blob)
    except ProtoError:
        bag = {"items": {}, "next_item_id": 0}
    bag["wire_b64"] = _wire_b64(role_bag_blob)
    bag["wire_dirty"] = False
    return bag


def default_role_state(role_base_blob: bytes, role_bag_blob: bytes = b"") -> dict[str, Any]:
    role_base = _default_role_base(role_base_blob)
    strength = {"current": 100, "max": 100, "restore_at": 0, "cost_rules": {}}
    risk = {
        "current_level": 0,
        "unlocked_levels": [],
        "completed": {},
        "stars": {},
        "first_rewards_claimed": {},
    }
    state: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "role_base": role_base,
        "role_bag": _default_bag(role_bag_blob),
        "equipment": {"by_hero": {}, "items": {}, "wire_b64": "", "wire_dirty": False},
        "heroes": {},
        "lineups": {"normal": [], "battle": [], "by_id": {}, "active_id": 0},
        "risk_battle": risk,
        "strength_state": strength,
        "tasks": {"region": {}, "general": {}, "activity": {}, "main": {}},
        "story": {"read": {}, "conditions": {}, "transmit": {}, "guide": {}},
        "gacha": {"pools": {}, "history": [], "encyclopedia": {}, "duplicate_count": 0},
        "social": {"ranking": [], "mail": [], "friends": [], "community": {}, "activities": {}},
        "preferences": {},
        "operations": {"battle": {}, "gacha": {}, "hero_level_up": {}, "payment": {}},
        # These aliases are retained for callers written before schema v1.
        "coin": role_base["coin"],
        "diamond": role_base["diamond"],
        "level": role_base["level"],
        "strength": strength["current"],
        "lineup": [],
        "risk": risk,
        "read_data": {},
        "conditions": {},
        "transmit": {},
        "guide": {},
    }
    return state


def _merge_dict(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dict(target[key], value)
        else:
            target[str(key)] = _copy(value)


def _merge_keyed(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for key, value in source.items():
        key = str(key)
        if value is None or value is False:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_dict(target[key], value)
        else:
            target[key] = _copy(value)


def _sync_aliases(state: dict[str, Any]) -> dict[str, Any]:
    role_base = _dict(state.get("role_base"))
    lineups = _dict(state.get("lineups"))
    risk = _dict(state.get("risk_battle"))
    strength = _dict(state.get("strength_state"))
    story = _dict(state.get("story"))
    state["role_base"] = role_base
    state["lineups"] = lineups
    state["risk_battle"] = risk
    state["strength_state"] = strength
    state["story"] = story
    state["coin"] = _int(role_base.get("coin"), 0, 0)
    state["diamond"] = _int(role_base.get("diamond"), 0, 0)
    state["level"] = _int(role_base.get("level"), 0, 0)
    state["strength"] = _int(strength.get("current"), 0, 0)
    state["lineup"] = _copy(lineups.get("normal") or [])
    state["risk"] = _copy(risk)
    state["read_data"] = _copy(story.get("read") or {})
    state["conditions"] = _copy(story.get("conditions") or {})
    state["transmit"] = _copy(story.get("transmit") or {})
    state["guide"] = _copy(story.get("guide") or {})
    return state


def normalize_role_state(
    raw: Any,
    role_base_blob: bytes,
    role_bag_blob: bytes = b"",
    *,
    hero_body: bytes | None = None,
    equipment_body: bytes | None = None,
) -> dict[str, Any]:
    """Migrate legacy state and fill missing fields without replacing data."""
    state = default_role_state(role_base_blob, role_bag_blob)
    raw_dict = _dict(raw)

    for key in (
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
        "preferences",
        "operations",
    ):
        value = raw_dict.get(key)
        if isinstance(value, dict):
            if key in {"heroes", "operations"}:
                _merge_keyed(state[key], value)
            else:
                _merge_dict(state[key], value)

    role_base = state["role_base"]
    legacy_role_fields = {
        "coin": "coin",
        "diamond": "diamond",
        "level": "level",
    }
    for legacy_key, model_key in legacy_role_fields.items():
        if legacy_key in raw_dict:
            role_base[model_key] = _int(raw_dict[legacy_key], role_base[model_key], 0)
    if "lineup" in raw_dict and isinstance(raw_dict["lineup"], list):
        state["lineups"]["normal"] = [_int(value, 0, 0) for value in raw_dict["lineup"]]
    if isinstance(raw_dict.get("risk"), dict):
        _merge_dict(state["risk_battle"], raw_dict["risk"])
    if "strength" in raw_dict:
        state["strength_state"]["current"] = _int(raw_dict["strength"], 100, 0)
    for legacy_key, model_key in (
        ("read_data", "read"),
        ("conditions", "conditions"),
        ("transmit", "transmit"),
        ("guide", "guide"),
    ):
        if isinstance(raw_dict.get(legacy_key), dict):
            _merge_dict(state["story"][model_key], raw_dict[legacy_key])

    if equipment_body and not state["equipment"].get("wire_b64"):
        state["equipment"]["wire_b64"] = _wire_b64(equipment_body)

    if hero_body and not state["heroes"]:
        try:
            decoded = decode_role_hero(hero_body)
        except ProtoError:
            decoded = {"heroes": {}, "lineups": {}, "active_id": 0}
        _merge_keyed(state["heroes"], decoded.get("heroes"))
        for lineup_id, lineup in _dict(decoded.get("lineups")).items():
            state["lineups"]["by_id"][str(lineup_id)] = lineup
        if decoded.get("active_id"):
            state["lineups"]["active_id"] = _int(decoded["active_id"])
        active_id = str(state["lineups"].get("active_id") or "")
        if active_id and active_id in state["lineups"]["by_id"]:
            state["lineups"]["normal"] = _copy(state["lineups"]["by_id"][active_id])
            if not state["lineups"].get("battle"):
                state["lineups"]["battle"] = _copy(state["lineups"]["normal"])

    state["schema_version"] = STATE_SCHEMA_VERSION
    return _sync_aliases(state)


def merge_role_state(state: Any, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a field-level state patch with explicit collection semantics."""
    result = _copy(state) if isinstance(state, dict) else {}
    result.setdefault("schema_version", STATE_SCHEMA_VERSION)
    for key, value in patch.items():
        key = str(key)
        if key == "role_base" and isinstance(value, dict):
            _merge_dict(result.setdefault("role_base", {}), value)
        elif key == "role_bag" and isinstance(value, dict):
            bag = result.setdefault("role_bag", {})
            if "items" in value:
                _merge_keyed(bag.setdefault("items", {}), value["items"])
                bag["wire_dirty"] = True
            for scalar in ("next_item_id", "wire_b64"):
                if scalar in value:
                    bag[scalar] = _copy(value[scalar])
            if "wire_dirty" in value:
                bag["wire_dirty"] = bool(value["wire_dirty"])
        elif key in {"heroes", "operations"} and isinstance(value, dict):
            _merge_keyed(result.setdefault(key, {}), value)
        elif key in {"equipment", "tasks", "story", "gacha", "social", "preferences", "risk_battle", "strength_state", "lineups"} and isinstance(value, dict):
            target = result.setdefault(key, {})
            if key in {"risk_battle", "strength_state", "lineups"}:
                _merge_dict(target, value)
            else:
                _merge_dict(target, value)
        elif key in {"coin", "diamond", "level"}:
            result.setdefault("role_base", {})[key] = _int(value, 0, 0)
        elif key == "strength":
            result.setdefault("strength_state", {})["current"] = _int(value, 0, 0)
        elif key == "lineup" and isinstance(value, list):
            result.setdefault("lineups", {})["normal"] = [_int(item, 0, 0) for item in value]
        elif key in {"risk", "read_data", "conditions", "transmit", "guide"}:
            target_key = {
                "risk": "risk_battle",
                "read_data": "story.read",
                "conditions": "story.conditions",
                "transmit": "story.transmit",
                "guide": "story.guide",
            }[key]
            target = result
            parts = target_key.split(".")
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            if isinstance(value, dict):
                _merge_dict(target.setdefault(parts[-1], {}), value)
        else:
            # Unknown state is retained under extensions instead of silently
            # replacing a known model section.
            result.setdefault("extensions", {})[key] = _copy(value)
    return _sync_aliases(result)


def operation_key(namespace: str, body: bytes) -> str:
    return f"{namespace}:{hashlib.sha256(body).hexdigest()}"


def get_operation(state: dict[str, Any], namespace: str, key: str) -> dict[str, Any] | None:
    operations = _dict(state.get("operations"))
    value = operations.get(namespace, {}).get(key) if isinstance(operations.get(namespace), dict) else None
    return _copy(value) if isinstance(value, dict) else None


def record_operation(
    state: dict[str, Any],
    namespace: str,
    key: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    operations = state.setdefault("operations", {})
    bucket = operations.setdefault(namespace, {})
    bucket[key] = {"result": _copy(result), "recorded_at": int(time.time())}
    if len(bucket) > MAX_OPERATION_RECEIPTS:
        for old_key in sorted(bucket, key=lambda item: bucket[item].get("recorded_at", 0))[: len(bucket) - MAX_OPERATION_RECEIPTS]:
            bucket.pop(old_key, None)
    return _sync_aliases(state)


def add_item(
    state: dict[str, Any],
    *,
    item_id: int,
    config_id: int,
    quantity: int,
    quality: int = 0,
    timestamp: int = 0,
) -> dict[str, Any]:
    if item_id <= 0 or config_id <= 0 or quantity < 0:
        raise ValueError("invalid item")
    bag = state.setdefault("role_bag", {})
    items = bag.setdefault("items", {})
    bag["wire_dirty"] = True
    if quantity == 0:
        items.pop(str(item_id), None)
    else:
        items[str(item_id)] = {
            "id": item_id,
            "config_id": config_id,
            "quantity": quantity,
            "quality": quality,
            "timestamp": timestamp,
        }
    bag["next_item_id"] = max(_int(bag.get("next_item_id"), 0), item_id + 1)
    return _sync_aliases(state)


def apply_item_delta(state: dict[str, Any], changes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Merge item changes; quantity zero is the explicit delete operation."""
    for change in changes:
        item_id = _int(change.get("id", change.get("item_id")), 0, 0)
        current = _dict(state.setdefault("role_bag", {}).setdefault("items", {}).get(str(item_id)))
        add_item(
            state,
            item_id=item_id,
            config_id=_int(change.get("config_id"), _int(current.get("config_id"), 0), 0),
            quantity=_int(change.get("quantity", change.get("num")), _int(current.get("quantity"), 0), 0),
            quality=_int(change.get("quality"), _int(current.get("quality"), 0), 0),
            timestamp=_int(change.get("timestamp"), _int(current.get("timestamp"), 0), 0),
        )
    return _sync_aliases(state)


def patch_role_base_from_state(role_base: bytes, state: dict[str, Any], uid: int | None = None) -> bytes:
    """Patch only confirmed RoleBase fields from the local structured state."""
    values = _dict(state.get("role_base"))
    result = role_base
    result = patch_varint(result, 1, _int(uid, _int(values.get("uid"), get_varint(result, 1), 0), 0))
    for field, key in ((2, "nickname"), (3, "signature")):
        if key in values and str(values[key]) != "":
            result = patch_string(result, field, str(values[key]))
    for field, key in ((4, "gender"), (7, "coin"), (8, "diamond"), (16, "head_id"), (26, "hero_exp"), (29, "area_id"), (130, "daily_reset_at"), (149, "online_stamp"), (150, "offline_stamp"), (153, "week_reset_at")):
        if key in values:
            value = _int(values[key], 0, 0)
            result = patch_role_base_diamond(result, value) if field == 8 else patch_varint(result, field, value)
    exp = get_bytes(result, 9) or b""
    if values.get("level") is not None:
        exp = patch_varint(exp, 1, _int(values.get("level"), 0, 0))
    if values.get("exp") is not None:
        exp = patch_varint(exp, 2, _int(values.get("exp"), 0, 0))
    if exp:
        result = patch_bytes(result, 9, exp)
    return result
