# Spec ↔ App mapping (clear checklist)

Your description had **three main sections**. The UI and code are aligned as follows.

---

## 1. Uploader Section (Dashboard)

| You asked for | Where it is |
|---------------|-------------|
| **Video source — select existing file** | **Uploader** tab → **Select existing video file** |
| **Video source — record new video** | **Record new video from camera** (+ seconds) → saves a clip then same pipeline as file |
| **Video source — use device cam without file** | **Use device camera (capture frames)** → grabs N frames directly (no intermediate file required) |
| **Network status — devices connected** | **Network status** + **Connected devices** list (updates when coordinator runs) |
| **Available worker nodes** | **Network status** line *Worker nodes used* after processing starts |
| **Start processing** | **Start processing** (Run card) |
| **Cancel mid-run** | **Cancel** button — aborts safely (v0.3) |
| **Max frames (file)** | **Max frames (file source)** field before Start (v0.3) |
| **Export job history** | Worker tab **Export CSV** (v0.3) |
| **Processing progress** | **Processing progress & frame grid** text box |
| **Frame grid — Pending / Claimed / Done / Failed** | Same section — counts updated live |
| **Connected devices list** | **Connected devices** text box (peer names from mDNS) |
| **Processed output** | **Processed output** — preview + path in log |
| **Processing analysis graph** | **Processing analysis graph** button (after a run) |

---

## 2. Worker Section (Worker Dashboard)

| You asked for | Where it is |
|---------------|-------------|
| **Uploader information** | **Uploader information** — explains who assigns tasks |
| **Connection status** | **Connection status** — port when online |
| **Performance metrics** | **Performance metrics** — frames received/processed/speed |
| **ACO metrics — pheromone, capability, battery** | **Ant Colony Optimization–style metrics** block |
| **Received frames** | Included in performance line |
| **Local database — jobs, history, date/time** | **Received frames & local database** — **Refresh job history** + scroll area |

---

## 3. Chat Section

| You asked for | Where it is |
|---------------|-------------|
| **Connected devices** | Chat tab intro + uploader **Connected devices** when coordinator is up |
| **Peer-to-peer messaging** | **Refresh peer list** → choose peer → **Send to peer** (unicast); or **Send to all** (broadcast) |
| **Credits earned** (worker) | Worker Dashboard ACO line shows **Credits** (accumulated from completed frames) |
| **Job history** | Worker DB lists each completed/failed frame job after processing |

---

## Workflow (your 8 steps) — still the same

1. Uploader selects **file** or **camera capture/record**.  
2. Video/frames are split into frames.  
3. Frames are sent to workers over **PeerLink** (chunked UDP).  
4. Workers run **YOLO** (or fallback) per frame.  
5. ACO-style metrics bias **which worker** gets the next frame.  
6. Processed frames are sent back **chunked** to the uploader.  
7. Frames are **combined** into one output video.  
8. **Graph** shows per-worker contribution when you open it.

---

## Camera notes

- **Camera index** `0` = default webcam; try `1` if you have multiple cameras.  
- **Frames** = how many stills to capture when using **capture** (feeds the same distributed pipeline).  
- **Record sec** = length when using **record** to a temp `.mp4`, then processed like any file.
