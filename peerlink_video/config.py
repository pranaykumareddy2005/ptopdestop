"""Network and app configuration."""
import socket

# UDP ports (same LAN broadcast domain)
BROADCAST_PORT = 37020
CHAT_PORT = 37021
TRANSFER_PORT = 37022  # unicast chunked frame transfer

# Max UDP payload safe size
CHUNK_SIZE = 1200
MAGIC = b"PLV1"

# Video temp dir name under user cache
APP_NAME = "PeerLinkVideo"

def get_local_ip() -> str:
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass
