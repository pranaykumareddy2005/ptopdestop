"""
Worker sends processed PNG back via chunked __peerlink_file_chunk__ to uploader
(filename result_g{gen}_frame_{idx}.png) — never a single huge RPC.
"""
from __future__ import annotations

import re
import threading
import time
import queue

from peerlink import PeerNode, RemoteError, PeerTimeoutError

from .video_split import bytes_to_frame_png, frame_to_bytes_png
from .yolo_processor import process_frame
from .worker_db import WorkerDB
from .aco import WorkerMetrics
from .peerlink_transfer import send_bytes_to_peer, DEFAULT_CHUNK_SIZE


FRAME_NAME_RE_GEN = re.compile(r"^(.+)_g(\d+)_frame_(\d+)\.png$", re.IGNORECASE)
FRAME_NAME_RE_LEGACY = re.compile(r"^(.+)_frame_(\d+)\.png$", re.IGNORECASE)


class PeerlinkWorker:
    def __init__(
        self,
        node_name: str,
        capability: float = 1.0,
        battery: float = 1.0,
        db_path: str | None = None,
        verbose: bool = False,
    ):
        self.node_name = node_name
        self.capability = capability
        self.battery = battery
        self._db = WorkerDB(db_path or f"worker_{node_name}.db")
        self._node: PeerNode | None = None
        self._metrics = WorkerMetrics(node_name, capability, battery)
        self._lock = threading.Lock()
        self._frames_received = 0
        self._frames_processed = 0
        self._on_metrics = lambda _d: None
        self._verbose = verbose
        self._job_queue: queue.Queue[tuple[str, int, int, bytes]] = queue.Queue()
        self._process_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pending_lock = threading.Lock()
        self._seen_frames: set[tuple[str, int, int]] = set()
        # Credits earned per successful frame (spec) — weighted by throughput
        self._credits_total = 0

    def set_metrics_callback(self, cb):
        self._on_metrics = cb

    def _parse_filename(self, filename: str) -> tuple[str, int, int] | None:
        m = FRAME_NAME_RE_GEN.match(filename)
        if m:
            return m.group(1), int(m.group(2)), int(m.group(3))
        m = FRAME_NAME_RE_LEGACY.match(filename)
        if m:
            return m.group(1), 0, int(m.group(2))
        return None

    def start(self) -> PeerNode:
        self._node = PeerNode(self.node_name, verbose=self._verbose)
        try:
            self._node.register("get_metrics", self._rpc_get_metrics)
            self._node.register("ping_worker", lambda: {"ok": True, "name": self.node_name})
            from .peerlink_transfer import make_file_chunk_handler

            def _complete(filename: str, data: bytes) -> None:
                parsed = self._parse_filename(filename)
                if not parsed:
                    return
                uploader_name, generation, frame_index = parsed
                key = (uploader_name, generation, frame_index)
                with self._pending_lock:
                    if len(self._seen_frames) > 15000:
                        self._seen_frames.clear()
                    if key in self._seen_frames:
                        return
                    self._seen_frames.add(key)
                self._frames_received += 1
                self._job_queue.put((uploader_name, generation, frame_index, data))

            self._node.register("__peerlink_file_chunk__", make_file_chunk_handler(_complete))
            self._node.start()
            self._stop_event.clear()
            self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
            self._process_thread.start()
            return self._node
        except Exception:
            if self._node:
                try:
                    self._node.stop()
                except Exception:
                    pass
                self._node = None
            raise

    def stop(self) -> None:
        self._stop_event.set()
        if self._process_thread:
            self._job_queue.put(("__shutdown__", -1, -1, b""))
            self._process_thread.join(timeout=5.0)
            self._process_thread = None
        if self._node:
            self._node.stop()
            self._node = None

    def _process_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._job_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            uploader_name, generation, frame_index, data = item
            if uploader_name == "__shutdown__":
                break
            self._run_yolo_and_reply(uploader_name, generation, frame_index, data)

    def _run_yolo_and_reply(self, uploader_name: str, generation: int, frame_index: int, data: bytes) -> None:
        # Do not increment frames_processed until success — avoids inflated stats on decode/YOLO failures
        t0 = time.perf_counter()
        try:
            frame = bytes_to_frame_png(data)
            out = process_frame(frame)
            out_bytes = frame_to_bytes_png(out)
        except Exception as _e:
            # region agent log
            try:
                from ._debug_log import agent_log
                agent_log(
                    "worker._run_yolo_and_reply",
                    "decode_or_yolo_failed",
                    {"frame_index": frame_index, "exc_type": type(_e).__name__, "runId": "repro"},
                    "H3",
                )
            except Exception:
                pass
            # endregion
            with self._lock:
                self._metrics.deposit(False, 0)
            with self._pending_lock:
                self._seen_frames.discard((uploader_name, generation, frame_index))
            try:
                self._db.add_job(
                    f"g{generation}_f{frame_index}",
                    uploader_name,
                    "failed",
                    0,
                )
            except Exception:
                pass
            return
        elapsed = time.perf_counter() - t0
        fps = 1.0 / elapsed if elapsed > 0 else 0.0
        try:
            self._db.increment_stat("frames_processed")
        except Exception:
            pass
        with self._lock:
            self._frames_processed += 1
            self._metrics.deposit(True, fps)
        self._on_metrics(self._rpc_get_metrics())
        if not self._node:
            return
        result_filename = f"result_g{generation}_frame_{frame_index:06d}.png"
        try:
            # Chunked send — fits UDP; never one giant submit_frame_result
            send_bytes_to_peer(
                self._node,
                uploader_name,
                result_filename,
                out_bytes,
                chunk_size=DEFAULT_CHUNK_SIZE,
            )
            # Credits: base + bonus for higher fps (contribution weight)
            credit_delta = 10 + min(50, int(fps))
            with self._lock:
                self._credits_total += credit_delta
            self._db.increment_stat("credits", credit_delta)
            self._db.add_job(
                f"g{generation}_f{frame_index}",
                uploader_name,
                "completed",
                1,
            )
        except (PeerTimeoutError, RemoteError, Exception):
            with self._lock:
                self._metrics.deposit(False, 0)
            with self._pending_lock:
                self._seen_frames.discard((uploader_name, generation, frame_index))
            try:
                self._db.add_job(
                    f"g{generation}_f{frame_index}",
                    uploader_name,
                    "failed",
                    0,
                )
            except Exception:
                pass

    def _rpc_get_metrics(self) -> dict:
        with self._lock:
            credits_db = self._db.get_stat("credits")
            return {
                "name": self.node_name,
                "capability": self.capability,
                "battery": self.battery,
                "frames_received": self._frames_received,
                "frames_processed": self._frames_processed,
                "pheromone": self._metrics.pheromone,
                "speed_fps": self._metrics.last_speed_fps,
                "credits_earned": credits_db,
                "credits_session": self._credits_total,
            }
