"""
Chunked transfer over PeerLink UDP — each RPC payload must stay under MAX_DATAGRAM (~64KB).
Default chunk_size 10KB → base64 ~14KB + JSON overhead safe.
"""
from __future__ import annotations

import base64
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict

# Safe for PeerLink JSON-RPC size limit
DEFAULT_CHUNK_SIZE = 10 * 1024
# Per-chunk RPC timeout — avoids indefinite hang if peer is down
CHUNK_CALL_TIMEOUT_SEC = 30.0
TRANSFER_TTL_SEC = 180.0
_SWEEP_INTERVAL = 30.0


@dataclass
class _TransferState:
    filename: str
    on_complete: Callable[[str, bytes], None]
    chunk_by_index: Dict[int, bytes] = field(default_factory=dict)
    finished: bool = False
    created_at: float = field(default_factory=time.time)
    last_index: int = -1


_ALL_TRANSFERS: Dict[str, _TransferState] = {}
_TRANSFER_LOCKS: Dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()


def _lock_for(transfer_id: str) -> threading.Lock:
    with _GLOBAL_LOCK:
        if transfer_id not in _TRANSFER_LOCKS:
            _TRANSFER_LOCKS[transfer_id] = threading.Lock()
        return _TRANSFER_LOCKS[transfer_id]


def _finalize(state: _TransferState, transfer_id: str) -> None:
    if state.last_index < 0:
        return
    total = state.last_index + 1
    if len(state.chunk_by_index) != total:
        return
    if not all(i in state.chunk_by_index for i in range(total)):
        return
    ordered = [state.chunk_by_index[i] for i in range(total)]
    data = b"".join(ordered)
    state.finished = True
    with _GLOBAL_LOCK:
        _ALL_TRANSFERS.pop(transfer_id, None)
        _TRANSFER_LOCKS.pop(transfer_id, None)
    try:
        state.on_complete(state.filename, data)
    except Exception:
        pass


def _sweep_loop() -> None:
    while True:
        time.sleep(_SWEEP_INTERVAL)
        now = time.time()
        with _GLOBAL_LOCK:
            dead = [
                tid
                for tid, st in list(_ALL_TRANSFERS.items())
                if not st.finished and (now - st.created_at) > TRANSFER_TTL_SEC
            ]
            for tid in dead:
                _ALL_TRANSFERS.pop(tid, None)
                _TRANSFER_LOCKS.pop(tid, None)


def make_file_chunk_handler(on_complete: Callable[[str, bytes], None]):
    if not getattr(make_file_chunk_handler, "_sweep_started", False):
        setattr(make_file_chunk_handler, "_sweep_started", True)
        threading.Thread(target=_sweep_loop, daemon=True, name="peerlink-transfer-sweep").start()

    def _rpc_file_chunk(
        transfer_id: str,
        filename: str,
        index: int,
        payload_b64: str,
        is_last: bool,
    ) -> None:
        try:
            chunk = base64.b64decode(payload_b64.encode("ascii"))
        except Exception:
            return
        tlock = _lock_for(transfer_id)
        with tlock:
            state = _ALL_TRANSFERS.get(transfer_id)
            if state is None:
                state = _TransferState(filename=filename, on_complete=on_complete)
                _ALL_TRANSFERS[transfer_id] = state
            if state.finished:
                return
            state.chunk_by_index[int(index)] = chunk
            if is_last:
                state.last_index = max(state.last_index, int(index))
            _finalize(state, transfer_id)

    return _rpc_file_chunk


def send_file_to_peer(node, peer: str, path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Send file in small chunks so each RPC fits in one UDP datagram."""
    import os
    transfer_id = uuid.uuid4().hex
    filename = os.path.basename(path)
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        index = 0
        if size == 0:
            # One empty chunk with is_last so receiver can finalize (zero-byte file would otherwise send nothing)
            node.call(
                peer, "__peerlink_file_chunk__", transfer_id, filename, 0,
                base64.b64encode(b"").decode("ascii"), True,
                timeout=CHUNK_CALL_TIMEOUT_SEC,
            )
            return transfer_id
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            payload = base64.b64encode(chunk).decode("ascii")
            pos = f.tell()
            size = os.fstat(f.fileno()).st_size
            is_last = pos >= size
            node.call(
                peer, "__peerlink_file_chunk__", transfer_id, filename, index, payload, is_last,
                timeout=CHUNK_CALL_TIMEOUT_SEC,
            )
            index += 1
    return transfer_id


def send_bytes_to_peer(
    node, peer: str, filename: str, data: bytes, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> str:
    """Send raw bytes as chunked RPC (no temp file)."""
    transfer_id = uuid.uuid4().hex
    total = len(data)
    index = 0
    offset = 0
    if total == 0:
        node.call(
            peer, "__peerlink_file_chunk__", transfer_id, filename, 0,
            base64.b64encode(b"").decode("ascii"), True,
            timeout=CHUNK_CALL_TIMEOUT_SEC,
        )
        return transfer_id
    while offset < total:
        chunk = data[offset : offset + chunk_size]
        offset += len(chunk)
        payload = base64.b64encode(chunk).decode("ascii")
        is_last = offset >= total
        node.call(
            peer, "__peerlink_file_chunk__", transfer_id, filename, index, payload, is_last,
            timeout=CHUNK_CALL_TIMEOUT_SEC,
        )
        index += 1
    return transfer_id
