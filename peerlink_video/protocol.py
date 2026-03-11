"""JSON control messages + binary chunk framing over UDP."""
from __future__ import annotations

import json
import struct
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .config import MAGIC, CHUNK_SIZE


class MsgType(IntEnum):
    # Discovery / coordinator
    HELLO = 1
    HELLO_ACK = 2
    JOB_OFFER = 3
    JOB_CLAIM = 4
    JOB_ASSIGN = 5
    FRAME_CHUNK = 6
    FRAME_ACK = 7
    FRAME_RESULT_META = 8
    FRAME_RESULT_CHUNK = 9
    FRAME_DONE = 10
    JOB_CANCEL = 11
    # Chat
    CHAT = 20


def _json_bytes(msg_type: MsgType, payload: dict[str, Any]) -> bytes:
    body = json.dumps({"t": int(msg_type), "p": payload}, separators=(",", ":")).encode("utf-8")
    return MAGIC + struct.pack("!H", msg_type) + body


def parse_json_message(data: bytes) -> tuple[MsgType, dict[str, Any]] | None:
    if len(data) < len(MAGIC) + 2:
        return None
    if data[: len(MAGIC)] != MAGIC:
        return None
    msg_type = MsgType(struct.unpack("!H", data[len(MAGIC) : len(MAGIC) + 2])[0])
    try:
        obj = json.loads(data[len(MAGIC) + 2 :].decode("utf-8"))
        return msg_type, obj.get("p", {})
    except Exception:
        return None


def new_job_id() -> str:
    return str(uuid.uuid4())[:8]


@dataclass
class FrameJob:
    job_id: str
    frame_index: int
    width: int
    height: int
    total_chunks: int
    uploader_name: str
    uploader_ip: str


def chunk_binary_header(job_id: str, frame_index: int, seq: int, total: int, is_last: bool) -> bytes:
    # MAGIC + u32 seq + u32 total + u16 frame_index + u8 flags + job_id utf8 null-term + payload
    flags = 1 if is_last else 0
    jid = job_id.encode("utf-8")[:32]
    return (
        MAGIC
        + struct.pack("!IIHHB", seq, total, frame_index & 0xFFFF, 0, flags)
        + jid
        + b"\x00"
    )


def parse_chunk_header(data: bytes) -> tuple[str, int, int, int, bool, int] | None:
    """Returns job_id, frame_index, seq, total, is_last, header_len."""
    base = len(MAGIC) + 4 + 4 + 2 + 2 + 1
    if len(data) < base:
        return None
    if data[: len(MAGIC)] != MAGIC:
        return None
    seq, total, frame_index, _, flags = struct.unpack("!IIHHB", data[len(MAGIC) : base])
    rest = data[base:]
    if b"\x00" not in rest:
        return None
    i = rest.index(b"\x00")
    job_id = rest[:i].decode("utf-8", errors="replace")
    header_len = base + i + 1
    return job_id, frame_index, seq, total, bool(flags & 1), header_len
