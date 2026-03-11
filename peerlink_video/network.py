"""UDP broadcast listener/sender and unicast chunked transfer."""
from __future__ import annotations

import socket
import struct
import threading
from typing import Callable

from .config import BROADCAST_PORT, CHAT_PORT, TRANSFER_PORT, CHUNK_SIZE, get_local_ip
from .protocol import MAGIC, parse_json_message, _json_bytes, MsgType, chunk_binary_header, parse_chunk_header


def broadcast_socket() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return s


def listen_socket(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    return s


def send_broadcast(data: bytes, port: int = BROADCAST_PORT) -> None:
    with broadcast_socket() as s:
        s.sendto(data, ("255.255.255.255", port))


def send_unicast(data: bytes, ip: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(data, (ip, port))


class UDPReceiver:
    def __init__(self, port: int, on_datagram: Callable[[bytes, tuple], None]):
        self.port = port
        self.on_datagram = on_datagram
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._sock = listen_socket(self.port)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._sock
        while not self._stop.is_set():
            try:
                self._sock.settimeout(0.5)
                data, addr = self._sock.recvfrom(65535)
                self.on_datagram(data, addr)
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None


def send_chunked_udp(payload: bytes, ip: str, port: int, job_id: str, frame_index: int) -> None:
    total = (len(payload) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for seq in range(total):
        start = seq * CHUNK_SIZE
        chunk = payload[start : start + CHUNK_SIZE]
        is_last = seq == total - 1
        header = chunk_binary_header(job_id, frame_index, seq, total, is_last)
        send_unicast(header + chunk, ip, port)
