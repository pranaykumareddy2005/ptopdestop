"""
Uploader: receives input via worker's send_file_to_peer; receives output via same
chunk RPC with filename result_g{gen}_frame_{idx}.png (PNG bytes too large for single RPC).
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
from typing import Callable

from peerlink import PeerNode

from .aco import WorkerMetrics, pick_worker


RESULT_NAME_RE = re.compile(r"^result_g(\d+)_frame_(\d+)\.png$", re.IGNORECASE)


class PeerlinkCoordinator:
    def __init__(
        self,
        node_name: str,
        on_progress: Callable[[dict], None] | None = None,
        verbose: bool = False,
    ):
        self.node_name = node_name
        self.on_progress = on_progress or (lambda _x: None)
        self._node: PeerNode | None = None
        self._results: dict[int, bytes] = {}
        self._frame_status: dict[int, str] = {}
        self._workers: dict[str, WorkerMetrics] = {}
        self._lock = threading.Lock()
        self._results_lock = threading.Lock()
        self._verbose = verbose
        self._job_generation = 0
        self._cancel_requested = False

    def start(self) -> PeerNode:
        self._node = PeerNode(self.node_name, verbose=self._verbose)
        try:
            self._node.register("submit_frame_result", self._rpc_submit_result_small)
            from .peerlink_transfer import make_file_chunk_handler

            def _on_result_file(filename: str, data: bytes) -> None:
                m = RESULT_NAME_RE.match(filename)
                if not m:
                    return
                gen, idx = int(m.group(1)), int(m.group(2))
                with self._lock:
                    if gen != self._job_generation:
                        return
                with self._results_lock:
                    self._results[idx] = data
                    self._frame_status[idx] = "done"
                self._emit_progress()

            self._node.register("__peerlink_file_chunk__", make_file_chunk_handler(_on_result_file))
            self._node.start()
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
        if self._node:
            self._node.stop()
            self._node = None

    def cancel(self) -> None:
        """Request abort of distribute_frames loop (next iteration or wait exits)."""
        self._cancel_requested = True

    def is_cancelled(self) -> bool:
        return self._cancel_requested

    def _rpc_submit_result_small(self, frame_index: int, png_b64: str, generation: int | None = None) -> dict:
        """Only for tiny payloads; normal path is chunked file send."""
        try:
            raw = base64.b64decode(png_b64.encode("ascii"))
            if len(raw) > 50000:
                return {"ok": False, "use_chunked": True}
        except Exception:
            return {"ok": False}
        with self._lock:
            if generation is not None and generation != self._job_generation:
                return {"ok": False, "stale": True}
        with self._results_lock:
            self._results[int(frame_index)] = raw
            self._frame_status[int(frame_index)] = "done"
        self._emit_progress()
        return {"ok": True}

    def _sync_worker_metrics(self) -> None:
        if not self._node:
            return
        for name in self._node.peer_names():
            if name == self.node_name:
                continue
            try:
                m = self._node.call(name, "get_metrics", timeout=3.0)
                if isinstance(m, dict) and m.get("name"):
                    wname = m["name"]
                    with self._lock:
                        if wname not in self._workers:
                            self._workers[wname] = WorkerMetrics(
                                wname,
                                float(m.get("capability", 1.0)),
                                float(m.get("battery", 1.0)),
                            )
                        w = self._workers[wname]
                        w.capability_score = float(m.get("capability", 1.0))
                        w.battery_level = float(m.get("battery", 1.0))
                        w.frames_done = int(m.get("frames_processed", 0))
                        w.pheromone = float(m.get("pheromone", w.pheromone))
                        w.last_speed_fps = float(m.get("speed_fps", 0.0))
            except Exception:
                pass

    def distribute_frames(
        self,
        frame_paths: list[str],
        _fps: float = 25.0,
        _width: int = 0,
        _height: int = 0,
        process_local_fallback: bool = True,
    ) -> dict[int, bytes]:
        self._cancel_requested = False
        with self._lock:
            self._job_generation += 1
            gen = self._job_generation
        with self._results_lock:
            self._results.clear()
        n = len(frame_paths)
        for i in range(n):
            self._frame_status[i] = "pending"

        for i, path in enumerate(frame_paths):
            if self._cancel_requested:
                for j in range(i, n):
                    self._frame_status[j] = "cancelled"
                self._emit_progress()
                with self._results_lock:
                    return {}
            import shutil
            prefixed = os.path.join(
                os.path.dirname(path) or ".",
                f"{self.node_name}_g{gen}_frame_{i:06d}.png",
            )
            if path != prefixed:
                shutil.copy2(path, prefixed)
                path = prefixed
            self._sync_worker_metrics()
            with self._lock:
                worker_name = pick_worker(self._workers)
            if not worker_name and process_local_fallback:
                self._process_local(i, path, gen)
                continue
            if not worker_name:
                self._frame_status[i] = "failed"
                self._emit_progress()
                continue
            self._frame_status[i] = "claimed"
            self._emit_progress()
            if not self._node:
                self._frame_status[i] = "failed"
                self._emit_progress()
                continue
            try:
                from .peerlink_transfer import send_file_to_peer
                send_file_to_peer(self._node, worker_name, path)
                deadline = time.time() + 180
                while time.time() < deadline:
                    if self._cancel_requested:
                        self._frame_status[i] = "cancelled"
                        self._emit_progress()
                        with self._results_lock:
                            return {}
                    with self._results_lock:
                        if i in self._results:
                            break
                    time.sleep(0.05)
                with self._results_lock:
                    got = i in self._results
                if not got:
                    self._frame_status[i] = "failed"
                    with self._lock:
                        if worker_name in self._workers:
                            self._workers[worker_name].deposit(False, 0)
                else:
                    with self._lock:
                        if worker_name in self._workers:
                            self._workers[worker_name].deposit(True, 1.0)
            except Exception:
                self._frame_status[i] = "failed"
            self._emit_progress()

        with self._results_lock:
            return dict(self._results)

    def _process_local(self, i: int, path: str, generation: int) -> None:
        import cv2
        from .video_split import frame_to_bytes_png
        from .yolo_processor import process_frame
        if self._cancel_requested:
            self._frame_status[i] = "cancelled"
            self._emit_progress()
            return
        frame_bgr = cv2.imread(path)
        if frame_bgr is None:
            self._frame_status[i] = "failed"
        else:
            try:
                if self._cancel_requested:
                    self._frame_status[i] = "cancelled"
                    self._emit_progress()
                    return
                out = process_frame(frame_bgr)
                with self._results_lock:
                    with self._lock:
                        if generation != self._job_generation:
                            return
                    self._results[i] = frame_to_bytes_png(out)
                    self._frame_status[i] = "done"
            except Exception:
                self._frame_status[i] = "failed"
        self._emit_progress()

    def _emit_progress(self) -> None:
        with self._lock:
            per_worker = {
                k: {"done": v.frames_done, "claimed": v.frames_claimed, "speed": v.last_speed_fps, "pheromone": v.pheromone}
                for k, v in self._workers.items()
            }
        self.on_progress({"frame_status": dict(self._frame_status), "workers": per_worker})

    def peer_names(self) -> list[str]:
        if not self._node:
            return []
        return [p for p in self._node.peer_names() if p != self.node_name]
