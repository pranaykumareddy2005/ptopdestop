# region agent log
"""Append NDJSON to debug-cec1c8.log — session cec1c8. Multiple fallbacks + stderr."""
import json
import sys
import tempfile
import time
from pathlib import Path

_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "debug-cec1c8.log",
    Path.cwd() / "debug-cec1c8.log",
    Path(tempfile.gettempdir()) / "debug-cec1c8.log",
]


def agent_log(location: str, message: str, data: dict | None = None, hypothesis_id: str = "") -> None:
    payload = {
        "sessionId": "cec1c8",
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data or {},
        "hypothesisId": hypothesis_id,
    }
    line = json.dumps(payload, default=str)
    # Always mirror to stderr so repro without log file still has evidence
    try:
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass
    for path in _CANDIDATES:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            return
        except Exception:
            continue
# endregion
