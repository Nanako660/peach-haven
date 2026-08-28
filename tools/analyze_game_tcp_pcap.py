"""Read a tcpdump pcap and recover the game's length-prefixed TCP frames."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import sys
import struct
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.game_proto import HEADER_SIZE, ProtoError, decode_login_request


def _parse_packet_records(path: Path) -> list[tuple[float, bytes]]:
    data = path.read_bytes()
    if len(data) < 24:
        raise ValueError("pcap is shorter than the global header")
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"M<\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2<M"):
        endian = ">"
    else:
        raise ValueError(f"unsupported pcap magic: {magic.hex()}")
    link_type = struct.unpack_from(endian + "I", data, 20)[0]
    if link_type != 276:
        raise ValueError(f"expected Linux cooked v2 (276), got {link_type}")

    records: list[tuple[float, bytes]] = []
    offset = 24
    while offset + 16 <= len(data):
        ts_sec, ts_usec, captured_len, _original_len = struct.unpack_from(
            endian + "IIII", data, offset
        )
        offset += 16
        end = offset + captured_len
        if end > len(data):
            raise ValueError("truncated pcap packet")
        records.append((ts_sec + ts_usec / 1_000_000, data[offset:end]))
        offset = end
    return records


def _extract_tcp(record: bytes) -> tuple[str, str, int, int, int, bytes] | None:
    if len(record) < 20:
        return None
    protocol = struct.unpack_from(">H", record, 0)[0]
    if protocol != 0x0800:
        return None
    ip_offset = 20
    if len(record) < ip_offset + 20:
        return None
    version_ihl = record[ip_offset]
    if version_ihl >> 4 != 4:
        return None
    ip_header_len = (version_ihl & 0x0F) * 4
    ip_total_length = struct.unpack_from(">H", record, ip_offset + 2)[0]
    if (
        ip_header_len < 20
        or ip_total_length < ip_header_len
        or len(record) < ip_offset + ip_total_length
    ):
        return None
    if record[ip_offset + 9] != 6:
        return None
    source = str(ipaddress.IPv4Address(record[ip_offset + 12 : ip_offset + 16]))
    target = str(ipaddress.IPv4Address(record[ip_offset + 16 : ip_offset + 20]))
    tcp_offset = ip_offset + ip_header_len
    if len(record) < tcp_offset + 20:
        return None
    source_port, target_port, sequence, _ack = struct.unpack_from(">HHII", record, tcp_offset)
    tcp_header_len = (record[tcp_offset + 12] >> 4) * 4
    if tcp_header_len < 20 or len(record) < tcp_offset + tcp_header_len:
        return None
    payload_end = ip_offset + ip_total_length
    if payload_end < tcp_offset + tcp_header_len:
        return None
    payload = record[tcp_offset + tcp_header_len : payload_end]
    return source, target, source_port, target_port, sequence, payload


def _reassemble(segments: list[tuple[float, int, bytes]]) -> tuple[bytes, list[float], int]:
    ordered = sorted(segments, key=lambda item: (item[1], item[0]))
    stream = bytearray()
    end_sequence: int | None = None
    timestamps: list[float] = []
    gaps = 0
    for timestamp, sequence, payload in ordered:
        if not payload:
            continue
        if end_sequence is None:
            end_sequence = sequence
        if sequence > end_sequence:
            gaps += 1
            continue
        start = max(0, end_sequence - sequence)
        if start >= len(payload):
            continue
        stream.extend(payload[start:])
        end_sequence += len(payload) - start
        timestamps.extend([timestamp] * (len(payload) - start))
    return bytes(stream), timestamps, gaps


def _decode_frames(stream: bytes, timestamps: list[float], direction: str) -> list[dict[str, Any]]:
    offset = 0
    frames: list[dict[str, Any]] = []
    while len(stream) - offset >= HEADER_SIZE:
        body_length, message_id, frame_sequence, flag = struct.unpack_from(">HHiH", stream, offset)
        total_length = HEADER_SIZE + body_length
        if len(stream) - offset < total_length:
            break
        body_start = offset + HEADER_SIZE
        body = stream[body_start : offset + total_length]
        end_offset = offset + total_length - 1
        record: dict[str, Any] = {
            "direction": direction,
            "timestamp": timestamps[end_offset] if end_offset < len(timestamps) else None,
            "msg_id": message_id,
            "seq": frame_sequence,
            "flag": flag,
            "body_len": body_length,
            "body_sha256": hashlib.sha256(body).hexdigest(),
        }
        if direction == "c2s" and message_id == 3:
            record["body_b64_redacted"] = True
            try:
                login = decode_login_request(body)
                token = login.get("auth_token", "")
                login["auth_token"] = {
                    "length": len(token),
                    "sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                }
                record["login"] = login
            except ProtoError as exc:
                record["login_decode_error"] = str(exc)
        else:
            record["body_b64"] = base64.b64encode(body).decode("ascii")
        frames.append(record)
        offset += total_length
    return frames


def analyze(path: Path, remote_ip: str, remote_port: int) -> dict[str, Any]:
    directions: dict[str, list[tuple[float, int, bytes]]] = defaultdict(list)
    packet_counts = defaultdict(int)
    payload_bytes = defaultdict(int)
    for timestamp, packet in _parse_packet_records(path):
        parsed = _extract_tcp(packet)
        if parsed is None:
            continue
        source, target, source_port, target_port, sequence, payload = parsed
        if source == remote_ip and source_port == remote_port:
            direction = "s2c"
        elif target == remote_ip and target_port == remote_port:
            direction = "c2s"
        else:
            continue
        packet_counts[direction] += 1
        payload_bytes[direction] += len(payload)
        directions[direction].append((timestamp, sequence, payload))

    output: dict[str, Any] = {
        "pcap": str(path),
        "remote": {"ip": remote_ip, "port": remote_port},
        "packets": dict(packet_counts),
        "payload_bytes": dict(payload_bytes),
        "streams": {},
        "frames": [],
    }
    for direction in ("c2s", "s2c"):
        stream, timestamps, gaps = _reassemble(directions[direction])
        output["streams"][direction] = {
            "reassembled_bytes": len(stream),
            "sequence_gaps": gaps,
        }
        output["frames"].extend(_decode_frames(stream, timestamps, direction))
    output["frames"].sort(key=lambda item: (item["timestamp"] is None, item["timestamp"] or 0))
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pcap", type=Path)
    parser.add_argument("--remote-ip", required=True)
    parser.add_argument("--remote-port", type=int, default=21001)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.pcap, args.remote_ip, args.remote_port)
    args.output.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "packets": result["packets"],
        "payload_bytes": result["payload_bytes"],
        "streams": result["streams"],
        "frame_count": len(result["frames"]),
        "msg_ids": [frame["msg_id"] for frame in result["frames"]],
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
