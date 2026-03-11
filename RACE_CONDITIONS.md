# Race conditions & concurrency plan

This document maps **who runs where**, **what can race**, and **what we did** to keep the distributed YOLO pipeline correct.

---

## 1. Execution contexts

| Component | Threads / entrypoints |
|-----------|------------------------|
| **PeerLink UDP** | One receive loop; **each RPC handled in a new thread** (`core._handle_message` → thread per packet). |
| **Chunk RPC `__peerlink_file_chunk__`** | Many concurrent invocations per transfer_id possible if UDP duplicates or multiple uploaders. |
| **Uploader `distribute_frames`** | Single thread (caller); sequential `send_file_to_peer` per frame. |
| **Worker YOLO** | **One dedicated `_process_thread`** pulling from `_job_queue` — no concurrent `predict()` on same process. |

---

## 2. Race matrix

### A. Chunk reassembly (worker)

| Risk | Cause | Mitigation |
|------|--------|------------|
| **Wrong byte order** | UDP reordering; append-only assembly is invalid. | Store chunks in `chunk_by_index[index]`; assemble `0..N-1` when `is_last` and all present. |
| **Interleaved transfers** | Same worker, two uploaders, same filename different `transfer_id`. | State keyed by `transfer_id` (UUID per send). |
| **Double `on_complete`** | Duplicate `is_last` or logic bug. | `state.finished` flag; pop state before callback; lock per `transfer_id`. |
| **Concurrent chunk writes** | Two threads same `transfer_id`. | `_TRANSFER_LOCKS[transfer_id]` — serialize append/finalize per transfer. |

### B. `submit_frame_result` (uploader)

| Risk | Cause | Mitigation |
|------|--------|------------|
| **Duplicate frame_index** | Worker retry or duplicate transfer. | **Idempotent**: dict overwrite by `frame_index` is fine (same image). |
| **Stale callback** | Old job finishes after new `distribute_frames` cleared `_results`. | **`_job_generation`**: incremented each job; optional RPC arg `generation` to ignore stale (worker can be extended to pass it). |
| **Read during write** | Main thread waits `i in self._results` while RPC thread writes. | **`_results_lock`**: all writes and the wait loop snapshot under lock (wait loop releases lock while sleeping). |

### C. YOLO / GPU

| Risk | Cause | Mitigation |
|------|--------|------------|
| **Double model load** | First two frames concurrently call `get_model()`. | **`_MODEL_LOCK`** singleton load. |
| **Concurrent predict** | Multiple RPC threads call YOLO. | **`_INFER_LOCK`** around `model.predict()`; worker also serializes via single `_process_thread`. |

### D. Worker dedup

| Risk | Cause | Mitigation |
|------|--------|------------|
| **Same frame queued twice** | Retransfer same file. | **`_seen_frames`** set `(uploader_name, frame_index)` under `_pending_lock`; discard duplicates before queue. |
| **Failed inference retry** | Need to allow retry. | On failure, `discard` key so uploader can resend (optional policy). |

### E. ACO / `_workers` dict

| Risk | Cause | Mitigation |
|------|--------|------------|
| **Torn read** | `pick_worker` while `get_metrics` updates. | **`_lock`** around all `_workers` mutations and `pick_worker` snapshot (coordinator holds lock only briefly). |

---

## 3. What is intentionally **not** parallel

- **One frame per worker process at a time** (queue + single thread) — simplifies YOLO and avoids GPU contention.
- **Uploader sends one frame file at a time** to a given worker — avoids overlapping chunk streams with same worker name (would still be safe by `transfer_id` but adds load).

---

## 4. Implemented hardening

- **TTL on transfer state** — `_ALL_TRANSFERS` evicted after `TRANSFER_TTL_SEC` (180s) by background sweep; prevents leak when chunks drop.
- **Generation in filename** — `{Uploader}_g{gen}_frame_{i}.png`; worker parses and calls `submit_frame_result(frame_index, b64, generation)` so stale callbacks are rejected.
- **Single global transfer store** — one dict + per-transfer lock; sweep can remove stale entries safely.
- **Checksum** per assembled file before YOLO to detect corruption.

---

## 5. Summary

- **Chunks**: ordered by index + per-transfer lock + single finalize.
- **Results**: lock-protected dict; idempotent by frame index; generation for stale guard.
- **YOLO**: single model singleton + inference lock + worker process queue.

This keeps behavior **clear and predictable** under LAN jitter, retries, and concurrent peers.
