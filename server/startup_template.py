"""Static startup-frame template support.

The game client expects a legacy-shaped startup sequence.  The exact bytes
come from the approved local TCP capture; at runtime the server only needs to
patch a few confirmed fields (RoleBase, RoleBag, RoleRiskBattle, RoleGuide,
RoleStrength, hero lineup).  This module keeps the rest of the sequence as an
opaque static template so config-driven mode does not need the original
capture files.
"""

from __future__ import annotations

import json
import base64
from pathlib import Path

from .game_proto import Frame, ProtoError, get_bytes


def load_startup_template(path: Path) -> list[Frame]:
    """Load and validate a startup template JSON file."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtoError(f"unable to read startup template {path}: {exc}") from exc

    if not isinstance(value, dict) or not isinstance(value.get("frames"), list):
        raise ProtoError("startup template must contain a frames list")
    source_frames = value["frames"]
    if not source_frames:
        raise ProtoError("startup template frames list is empty")

    frames: list[Frame] = []
    for item in source_frames:
        if not isinstance(item, dict):
            raise ProtoError("startup template frame must be a JSON object")
        frame = Frame.from_json(item)
        if frame.msg_id in {3, 4, 7}:
            raise ProtoError(
                f"startup template must only contain frames after SCLoginAck, got msg_id={frame.msg_id}"
            )
        frames.append(frame)

    if not any(frame.msg_id == 25 for frame in frames):
        raise ProtoError("startup template must contain at least one SCStartupInfoNtf(25)")
    if not any(frame.msg_id == 26 for frame in frames):
        raise ProtoError("startup template must contain SCStartupInfoEquipNtf(26)")
    if not any(frame.msg_id == 27 for frame in frames):
        raise ProtoError("startup template must contain SCStartupInfoHeroNtf(27)")
    if not any(frame.msg_id == 28 for frame in frames):
        raise ProtoError("startup template must contain SCStartupInfoEndNtf(28)")
    if not any(frame.msg_id == 25 and get_bytes(frame.body, 6) is not None for frame in frames):
        raise ProtoError("startup template must contain RoleRiskBattle (SCStartupInfoNtf field 6)")
    return frames


def build_startup_template(fixture_path: Path, capture_path: Path) -> list[Frame]:
    """Build the legacy startup sequence from fixture and capture files."""
    fixture_value = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture_frames = [Frame.from_json(item) for item in fixture_value["messages"]]

    capture_value = json.loads(capture_path.read_text(encoding="utf-8"))
    source_frames = capture_value.get("frames") if isinstance(capture_value, dict) else capture_value
    records: list[tuple[str, Frame]] = []
    for item in source_frames:
        if not isinstance(item, dict) or item.get("direction") not in {"c2s", "s2c"}:
            continue
        frame = Frame.from_json(
            {
                "msg_id": item.get("msg_id"),
                "seq": item.get("seq", 0),
                "flag": item.get("flag", 0),
                "body_b64": item.get("body_b64", ""),
            }
        )
        records.append((str(item["direction"]), frame))

    ack_index = next(
        (index for index, (direction, frame) in enumerate(records) if direction == "s2c" and frame.msg_id == 4),
        None,
    )
    if ack_index is None:
        raise ProtoError("capture must contain SCLoginAck(4)")

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
        raise ProtoError("built startup template is missing SCStartupInfoEndNtf(28)")
    return result


def generate_startup_template(
    fixture_path: Path,
    capture_path: Path,
    output_path: Path,
) -> None:
    """Write a compact startup template JSON file."""
    frames = build_startup_template(fixture_path, capture_path)
    document = {
        "version": 1,
        "frames": [
            {
                "msg_id": frame.msg_id,
                "seq": frame.seq,
                "flag": frame.flag,
                "body_b64": base64.b64encode(frame.body).decode("ascii"),
            }
            for frame in frames
        ],
    }
    output_path.write_text(
        json.dumps(document, ensure_ascii=True, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate a static startup template JSON")
    parser.add_argument("--fixture", type=Path, default=Path("server/data/fixtures/captured-lily6985-local.json"))
    parser.add_argument("--capture", type=Path, default=Path("server/data/captures/tao-original-20260823-1605-game-frames.json"))
    parser.add_argument("--output", type=Path, default=Path("server/data/startup_template.json"))
    args = parser.parse_args()
    generate_startup_template(args.fixture, args.capture, args.output)
    print(f"wrote {args.output}")