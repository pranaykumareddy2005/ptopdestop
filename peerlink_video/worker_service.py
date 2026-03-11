"""
Worker: listens for JOB_ASSIGN + chunks, processes frame, sends result back to uploader.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Callable

from .config import BROADCAST_PORT, TRANSFER_PORT
from .network import UDPReceiver, send_chunked_udp
from .protocol import MsgType, _json_bytes, parse_json_message, new_job_id
from .video_split import bytes_to_frame_png, frame_to_bytes_png, simple_process_frame
from .worker_db import WorkerDB


class WorkerService:
    def __init__(
        self,
        node_name: str,
        capability: float = 1.0,
        battery: float = 1.0,
        db_path: str | None = None,
        on_metrics: Callable[[dict], None] | None = None,
    ):
        self.node_name = node_name
        self.capability = capability
        self.battery = battery
        self.on_metrics = on_metrics or (lambda _x: None)
        self._db = WorkerDB(db_path or "worker_activity.db")
        self._rx: UDPReceiver | None = None
        self._chunks: dict[tuple[str, int], dict[int, bytes]] = defaultdict(dict)
        self._pending_assign: dict[tuple[str, int], str] = {}  # (job_id, frame_index) -> uploader_ip
        self._lock = threading.Lock()
        self.frames_received = 0
        self.frames_processed = 0

    def start(self) -> None:
        def on_data(data: bytes, addr):
            parsed = parse_json_message(data)
            if parsed:
                t, p = parsed
                if t == MsgType.JOB_ASSIGN and p.get("worker") == self.node_name:
                    job_id = p["job_id"]
                    frame_index = int(p["frame_index"])
                    uploader_ip = p.get("uploader_ip", addr[0])
                    with self._lock:
                        self._pending_assign[(job_id, frame_index)] = uploader_ip
                return
            from .protocol import parse_chunk_header
            h = parse_chunk_header(data)
            if not h:
                return
            job_id, frame_index, seq, total, _is_last, hlen = h
            key = (job_id, frame_index)
            with self._lock:
                self._chunks[key][seq] = data[hlen:]
                if len(self._chunks[key]) < total:
                    return
                payload = b"".join(self._chunks[key][i] for i in range(total))
                del self._chunks[key]
                uploader_ip = self._pending_assign.pop(key, None)
            if not uploader_ip:
                return
            self.frames_received += 1
            t0 = time.perf_counter()
            try:
                frame = bytes_to_frame_png(payload)
                out = simple_process_frame(frame)
                out_bytes = frame_to_bytes_png(out)
            except Exception:
                return
            elapsed = time.perf_counter() - t0
            fps = 1.0 / elapsed if elapsed > 0 else 0
            self.frames_processed += 1
            self._db.increment_stat("frames_processed")
            send_chunked_udp(out_bytes, uploader_ip, TRANSFER_PORT, job_id + "_r", frame_index)
            self.on_metrics(
                {
                    "frames_received": self.frames_received,
                    "frames_processed": self.frames_processed,
                    "last_fps": fps,
                    "pheromone": min(1.0, 0.5 + self.frames_processed * 0.01),
                }
            )

        self._rx = UDPReceiver(TRANSFER_PORT, on_data)
        self._rx.start()
        # Also need broadcast port for JOB_ASSIGN
        def on_broadcast(data: bytes, addr):
            parsed = parse_json_message(data)
            if not parsed:
                return
            t, p = parsed
            if t == MsgType.JOB_ASSIGN and p.get("worker") == self.node_name:
                on_data(data, addr)

        self._brx = UDPReceiver(BROADCAST_PORT, on_broadcast)
        self._brx.start()

    def stop(self) -> None:
        if self._rx:
            self._rx.stop()
        if getattr(self, "_brx", None):
            self._brx.stop()

    def claim_loop(self) -> None:
        """Periodically broadcast claim so uploader learns our IP and metrics."""
        from .network import send_broadcast
        while getattr(self, "_claim_run", True):
            send_broadcast(
                _json_bytes(
                    MsgType.JOB_CLAIM,
                    {"worker": self.node_name, "capability": self.capability, "battery": self.battery},
                )
            )
            time.sleep(2.0)

    def start_claim_loop(self) -> None:
        self._claim_run = True
        self._claim_thread = threading.Thread(target=self.claim_loop, daemon=True)
        self._claim_thread.start()

    def stop_claim_loop(self) -> None:
        self._claim_run = False
