"""Peer chat over UDP broadcast."""
from __future__ import annotations

import threading
from typing import Callable

from .config import CHAT_PORT
from .network import send_broadcast, UDPReceiver
from .protocol import MsgType, _json_bytes, parse_json_message


class ChatService:
    def __init__(self, node_name: str, on_message: Callable[[str, str], None] | None = None):
        self.node_name = node_name
        self.on_message = on_message or (lambda _from, _text: None)
        self._rx: UDPReceiver | None = None

    def start(self) -> None:
        if self._rx is not None:
            self.stop()
        def on_data(data: bytes, addr):
            parsed = parse_json_message(data)
            if not parsed or parsed[0] != MsgType.CHAT:
                return
            p = parsed[1]
            sender = p.get("from", addr[0])
            text = p.get("text", "")
            self.on_message(sender, text)

        self._rx = UDPReceiver(CHAT_PORT, on_data)
        self._rx.start()

    def stop(self) -> None:
        if self._rx:
            self._rx.stop()

    def send(self, text: str) -> None:
        send_broadcast(_json_bytes(MsgType.CHAT, {"from": self.node_name, "text": text}), CHAT_PORT)
