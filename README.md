# Distributed Video Processing — **PeerLink-first**

Desktop app that uses **[PeerLink](https://pypi.org/project/peerlink/)** for almost everything:

| Area | Mechanism |
|------|-----------|
| **Discovery** | mDNS (`PeerNode` / `wait_for_peers`, `peer_names`) |
| **Frame transfer** | Chunked RPC — same wire format as `PeerNode.send_file`, with a **compatible `__peerlink_file_chunk__` handler** (see `peerlink_transfer.py`) |
| **Results** | Chunked send back as `result_g{gen}_frame_*.png` (same RPC as input — fits UDP) |
| **Worker metrics / ACO** | RPC `get_metrics` polled by uploader; local SQLite still used on worker |
| **Chat** | `call("ALL", "chat_append", sender, text)` |

Legacy raw-UDP modules (`coordinator.py`, `worker_service.py`, `chat.py`) are **not used** by `main.py` anymore; they remain only if you want a non-PeerLink fallback.

## Requirements

- Python 3.10+
- `peerlink` (your install may be local `PeerLink_Core` or PyPI)
- Same LAN for mDNS

## Install

```bash
cd "desktop version peer to peer"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

1. **Workers** (other PCs or separate processes): set a **unique node name**, open **Worker** tab → **Start worker (PeerLink)**.
2. **Uploader**: set node name, open **1 — Uploader Dashboard** → **select video** and/or **use device camera** → **Start distributed processing**.

**Camera:** **Capture frames** = grab N stills from webcam into the pipeline (no file needed). **Record** = record a short clip to temp file then process like a normal video. See **`SPEC_MAPPING.md`** for the full checklist vs your original description.

**No workers?** Processing still runs: every frame falls back to **local YOLO** on the uploader machine.

**Headless smoke test** (no GUI):

```bash
python run_smoke.py path\to\video.mp4
python run_smoke.py path\to\video.mp4 --keep   # keep temp dir for inspection
```

**v0.3.0** — Cancel mid-run, configurable max frames (UI + CLI), headless `peerlink-video process`, Worker job history **Export CSV**. See `CHANGELOG.md`.

```bash
peerlink-video                    # GUI (same as python main.py)
peerlink-video process video.mp4 -o out.mp4 --max-frames 60
```

## Why chunked transfer

PeerLink uses a single UDP datagram per RPC (~64KB max). PNG results are larger, so:

- **Input frames** → chunked `__peerlink_file_chunk__` (~10KB binary per chunk).
- **Output frames** → same RPC back to uploader as `result_g{gen}_frame_{i}.png` bytes, chunked — **never** one giant `submit_frame_result` payload.

```bash
python main.py
```

CLI discovery:

```bash
peerlink discover
peerlink ping <WorkerName>
```

## YOLO

- Default model: `yolov8n.pt` (auto-download). Override: `set PEERLINK_YOLO_MODEL=yolov8s.pt`.
- First run downloads weights; worker runs inference **serialized** (one frame at a time) to avoid GPU/thread races.
- See **`RACE_CONDITIONS.md`** for chunk reassembly, duplicate callbacks, and locks.

## Filename convention

Frames are sent as files named `{UploaderNodeName}_frame_{index}.png` so the worker can call the correct peer’s `submit_frame_result` RPC.

## License

MIT (app). PeerLink is separate.
