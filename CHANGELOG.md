# Changelog

## 0.3.0 — Operational polish

- **Cancel processing** — Stop a run mid-flight from the Uploader tab; coordinator aborts safely without writing a partial video.
- **Configurable max frames** — UI field + CLI `--max-frames` for file extraction (default 30).
- **Headless CLI** — `peerlink-video process <video> [-o out.mp4] [--max-frames N]` (no GUI).
- **Worker job export** — Export SQLite job history to CSV from the Worker tab.

## 0.2.0

- Worker credits + job history (SQLite), P2P chat, Save as, progress bar + frame status grid, `peerlink-video` entry point.

## 0.1.0

- Initial PeerLink + YOLO distributed pipeline, chunked transfer, camera capture/record.
