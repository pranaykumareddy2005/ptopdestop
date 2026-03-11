"""
Uploader-side coordinator: broadcasts job offers, receives claims with IP,
sends frame chunks via UDP unicast, collects results, updates ACO.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Callable

from .aco import WorkerMetrics, pick_worker
from .config import BROADCAST_PORT, TRANSFER_PORT, get_local_ip
from .network import send_broadcast, send_unicast, UDPReceiver, send_chunked_udp
from .protocol import MsgType, _json_bytes, parse_json_message, new_job_id
from .video_split import frame_to_bytes_png, simple_process_frame
import cv2


class Coordinator:
    def __init__(
        self,
        node_name: str,
        on_progress: Callable[[dict], None] | None = None,
        on_peer_update: Callable[[list[str]], None] | None = None,
    ):
        self.node_name = node_name
        self.on_progress = on_progress or (lambda _x: None)
        self.on_peer_update = on_peer_update or (lambda _x: None)
        self._receiver: UDPReceiver | None = None
        self._transfer_rx: UDPReceiver | None = None
        self._peers: set[str] = set()
        self._workers: dict[str, WorkerMetrics] = {}
        self._worker_ips: dict[str, str] = {}
        self._frame_status: dict[int, str] = {}
        self._lock = threading.Lock()
        self._results: dict[int, bytes] = {}
        self._chunks: dict[tuple[str, int], dict[int, bytes]] = defaultdict(dict)

    def start(self) -> None:
        def on_data(data: bytes, addr):
            parsed = parse_json_message(data)
            if parsed:
                self._handle_json(parsed[0], parsed[1], addr)
                return
            from .protocol import parse_chunk_header
            h = parse_chunk_header(data)
            if h:
                job_id, frame_index, seq, total, _is_last, hlen = h
                key = (job_id, frame_index)
                with self._lock:
                    self._chunks[key][seq] = data[hlen:]
                    if len(self._chunks[key]) == total:
                        payload = b"".join(self._chunks[key][i] for i in range(total))
                        del self._chunks[key]
                        self._results[frame_index] = payload
                return

        self._receiver = UDPReceiver(BROADCAST_PORT, on_data)
        self._receiver.start()
        self._transfer_rx = UDPReceiver(TRANSFER_PORT, on_data)
        self._transfer_rx.start()

    def stop(self) -> None:
        if self._receiver:
            self._receiver.stop()
        if self._transfer_rx:
            self._transfer_rx.stop()

    def _handle_json(self, t: MsgType, p: dict, addr) -> None:
        if t == MsgType.HELLO:
            name = p.get("name", addr[0])
            with self._lock:
                self._peers.add(name)
            self.on_peer_update(sorted(self._peers))
            send_unicast(_json_bytes(MsgType.HELLO_ACK, {"name": self.node_name}), addr[0], BROADCAST_PORT)
        elif t == MsgType.JOB_CLAIM:
            worker_name = str(p.get("worker", addr[0]))
            capability = float(p.get("capability", 1.0))
            battery = float(p.get("battery", 1.0))
            with self._lock:
                self._worker_ips[worker_name] = addr[0]
                if worker_name not in self._workers:
                    self._workers[worker_name] = WorkerMetrics(worker_name, capability, battery)
                w = self._workers[worker_name]
                w.capability_score = capability
                w.battery_level = battery
                w.frames_claimed += 1

    def announce_hello(self) -> None:
        send_broadcast(_json_bytes(MsgType.HELLO, {"name": self.node_name, "role": "uploader"}))

    def distribute_frames(self, frame_paths: list[str], process_local_fallback: bool = True) -> dict[int, bytes]:
        self._results.clear()
        n = len(frame_paths)
        for i in range(n):
            self._frame_status[i] = "pending"

        job_id = new_job_id()
        my_ip = get_local_ip()

        for i, path in enumerate(frame_paths):
            frame_bgr = cv2.imread(path)
            if frame_bgr is None:
                self._frame_status[i] = "failed"
                self._emit_progress()
                continue
            payload = frame_to_bytes_png(frame_bgr)

            with self._lock:
                worker_id = pick_worker(self._workers)
            if worker_id is None and process_local_fallback:
                try:
                    out = simple_process_frame(frame_bgr)
                    self._results[i] = frame_to_bytes_png(out)
                    self._frame_status[i] = "done"
                except Exception:
                    self._frame_status[i] = "failed"
                self._emit_progress()
                continue
            if worker_id is None:
                self._frame_status[i] = "failed"
                self._emit_progress()
                continue

            worker_ip = self._worker_ips.get(worker_id)
            if not worker_ip:
                try:
                    out = simple_process_frame(frame_bgr)
                    self._results[i] = frame_to_bytes_png(out)
                    self._frame_status[i] = "done"
                except Exception:
                    self._frame_status[i] = "failed"
                self._emit_progress()
                continue

            total_chunks = (len(payload) + 1200 - 1) // 1200
            send_broadcast(
                _json_bytes(
                    MsgType.JOB_ASSIGN,
                    {
                        "job_id": job_id,
                        "frame_index": i,
                        "worker": worker_id,
                        "uploader_ip": my_ip,
                        "total_chunks": total_chunks,
                    },
                )
            )
            time.sleep(0.08)
            self._frame_status[i] = "claimed"
            send_chunked_udp(payload, worker_ip, TRANSFER_PORT, job_id, i)

            deadline = time.time() + 45
            while time.time() < deadline and i not in self._results:
                time.sleep(0.05)
            if i not in self._results:
                self._frame_status[i] = "failed"
                with self._lock:
                    if worker_id in self._workers:
                        self._workers[worker_id].deposit(False, 0)
            else:
                self._frame_status[i] = "done"
                with self._lock:
                    if worker_id in self._workers:
                        self._workers[worker_id].deposit(True, 1.0)
            self._emit_progress()

        return dict(self._results)

    def _emit_progress(self) -> None:
        per_worker = {
            k: {"done": v.frames_done, "claimed": v.frames_claimed, "speed": v.last_speed_fps, "pheromone": v.pheromone}
            for k, v in self._workers.items()
        }
        self.on_progress({"frame_status": dict(self._frame_status), "workers": per_worker})
