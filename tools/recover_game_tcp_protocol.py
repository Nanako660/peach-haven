"""Extract a small, repeatable protocol inventory from decompiled C# files.

The input tree is treated as read-only.  This is intentionally a lightweight
scanner for generated Google.Protobuf C# output, not a C# compiler or a packet
decoder.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


MESSAGE_SPECS = {
    3: "CSLoginReq",
    4: "SCLoginAck",
    7: "SCHandShakeNtf",
    25: "SCStartupInfoNtf",
    26: "SCStartupInfoEquipNtf",
    27: "SCStartupInfoHeroNtf",
    28: "SCStartupInfoEndNtf",
    76: "SCRoleBaseInfoNtf",
    377: "CSOrderNoReq",
    378: "SCOrderNoAck",
}

FIELD_RE = re.compile(r"public const int (?P<name>[A-Za-z_][A-Za-z0-9_]*)FieldNumber = (?P<number>\d+);")
PROPERTY_RE = re.compile(
    r"public (?P<type>[A-Za-z0-9_<>, ?]+) (?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:\{|=>)"
)
ENUM_RE = re.compile(
    r"(?P<original>\[OriginalName\(\"(?P<wire>[^\"]+)\"\)\]\s*)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<number>\d+),"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _enum_names(proto_msg_id: Path) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for match in ENUM_RE.finditer(_read(proto_msg_id)):
        number = int(match.group("number"))
        result[number] = {
            "enum_name": match.group("name"),
            "wire_name": match.group("wire") or "",
        }
    return result


def _message_inventory(path: Path, msg_id: int, enum_info: dict[str, str]) -> dict[str, Any]:
    text = _read(path)
    properties = {
        match.group("name"): " ".join(match.group("type").split())
        for match in PROPERTY_RE.finditer(text)
    }
    fields = []
    for match in FIELD_RE.finditer(text):
        name = match.group("name")
        fields.append(
            {
                "number": int(match.group("number")),
                "name": name,
                "type": properties.get(name, "unknown"),
            }
        )
    fields.sort(key=lambda item: item["number"])
    return {
        "msg_id": msg_id,
        "type": path.stem,
        "enum_name": enum_info.get("enum_name", ""),
        "wire_name": enum_info.get("wire_name", ""),
        "source": str(path),
        "fields": fields,
    }


def recover(source_root: Path) -> dict[str, Any]:
    proto_root = source_root / "Serverproto"
    proto_msg_id = proto_root / "protoMsgId.cs"
    if not proto_msg_id.is_file():
        raise FileNotFoundError(f"missing protocol enum: {proto_msg_id}")
    enum_names = _enum_names(proto_msg_id)
    messages = []
    for msg_id, type_name in MESSAGE_SPECS.items():
        path = proto_root / f"{type_name}.cs"
        if not path.is_file():
            raise FileNotFoundError(f"missing message definition: {path}")
        messages.append(_message_inventory(path, msg_id, enum_names.get(msg_id, {})))
    return {
        "evidence": "Confirmed by static analysis",
        "source_root": str(source_root),
        "messages": messages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover confirmed game TCP protocol definitions")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(".tools/client_decompiled/Model.dll"),
        help="decompiled Model.dll directory",
    )
    parser.add_argument("--output", type=Path, help="write JSON inventory to this path")
    args = parser.parse_args()
    inventory = recover(args.source_root)
    payload = json.dumps(inventory, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
