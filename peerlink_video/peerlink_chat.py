"""Chat via PeerLink call('ALL', ...) or unicast."""
from __future__ import annotations

from typing import Callable

from peerlink import PeerNode


class PeerlinkChat:
    def __init__(self, node: PeerNode, on_message: Callable[[str, str], None] | None = None):
        self._node = node
        self._on_message = on_message or (lambda _s, _t: None)
        # Each peer registers chat_append; broadcaster calls ALL
        self._node.register("chat_append", self._rpc_chat_append)

    def _rpc_chat_append(self, sender: str, text: str) -> dict:
        self._on_message(sender, text)
        return {"ok": True}

    def broadcast(self, text: str) -> None:
        """Notify all peers (including self if registered)."""
        try:
            self._node.call("ALL", "chat_append", self._node.node_name, text, timeout=5.0)
        except Exception:
            pass

    def send_to(self, peer: str, text: str) -> None:
        try:
            self._node.call(peer, "chat_append", self._node.node_name, text, timeout=5.0)
        except Exception as e:
            raise RuntimeError(f"Chat send failed: {e}") from e
