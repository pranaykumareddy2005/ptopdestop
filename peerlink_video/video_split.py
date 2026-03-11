"""Extract frames from file or device camera; recombine to video."""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

import cv2
import numpy as np

# Optional callback(frame_bgr) each frame — for UI preview (call from worker thread; UI should schedule main-thread update)
FrameCallback = Optional[Callable[[np.ndarray], None]]


def extract_frames(video_path: str, out_dir: str, max_frames: int | None = None) -> tuple[list[str], float, int, int]:
    """
    Reads a video file and writes frame_000000.png … into out_dir.
    Returns (paths, fps, width, height).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    paths: list[str] = []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        w = max(1, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640)
        h = max(1, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480)
        idx = 0
        os.makedirs(out_dir, exist_ok=True)
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if max_frames is not None and idx >= max_frames:
                break
            path = os.path.join(out_dir, f"frame_{idx:06d}.png")
            cv2.imwrite(path, frame)
            paths.append(path)
            idx += 1
    finally:
        cap.release()
    if not paths:
        raise RuntimeError("No frames read from video")
    return paths, fps, w, h


def capture_frames_from_camera(
    out_dir: str,
    max_frames: int = 30,
    fps: float = 25.0,
    camera_index: int = 0,
    warmup_frames: int = 5,
    on_frame: FrameCallback = None,
) -> tuple[list[str], float, int, int]:
    """
    Capture frames directly from the default (or given) device camera.
    Writes the same frame_000000.png layout as extract_frames so the
    uploader pipeline is unchanged.

    Returns (paths, fps, width, height). fps is nominal (used when muxing output).
    """
    os.makedirs(out_dir, exist_ok=True)
    cap = None
    if os.name == "nt":
        try:
            cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        except Exception:
            cap = None
    if cap is not None and not cap.isOpened():
        cap.release()
        cap = None
    if cap is None or not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        if cap is not None:
            cap.release()
        raise RuntimeError(f"Cannot open camera index {camera_index}. Try 0 or 1.")
    w = max(1, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640)
    h = max(1, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480)
    for _ in range(warmup_frames):
        cap.read()
    paths: list[str] = []
    interval = 1.0 / fps if fps > 0 else 0.04
    try:
        for idx in range(max_frames):
            ok, frame = cap.read()
            if not ok:
                break
            if on_frame is not None:
                try:
                    on_frame(frame)
                except Exception:
                    pass
            path = os.path.join(out_dir, f"frame_{idx:06d}.png")
            cv2.imwrite(path, frame)
            paths.append(path)
            if idx < max_frames - 1 and interval > 0:
                time.sleep(interval)
    finally:
        cap.release()
    if not paths:
        raise RuntimeError("No frames captured from camera")
    return paths, fps, w, h


def record_webcam_to_file(
    out_path: str,
    duration_sec: float = 5.0,
    fps: float = 20.0,
    camera_index: int = 0,
    on_frame: FrameCallback = None,
) -> tuple[float, int, int]:
    """
    Record from webcam into a video file (e.g. .mp4). Returns (fps, w, h).
    You can then use extract_frames(out_path, ...) or process the file elsewhere.
    """
    cap = None
    writer = None
    if os.name == "nt":
        try:
            cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        except Exception:
            cap = None
    if cap is not None and not cap.isOpened():
        cap.release()
        cap = None
    if cap is None or not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        if cap is not None:
            cap.release()
        raise RuntimeError(f"Cannot open camera index {camera_index}")
    try:
        w = max(1, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640)
        h = max(1, int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(out_path, fourcc, fps, (w, h))
        if not writer.isOpened():
            raise RuntimeError("VideoWriter failed — try .avi or install codecs")
        end = time.time() + duration_sec
        while time.time() < end:
            ok, frame = cap.read()
            if not ok:
                break
            if on_frame is not None:
                try:
                    on_frame(frame)
                except Exception:
                    pass
            writer.write(frame)
    finally:
        if writer is not None:
            try:
                writer.release()
            except Exception:
                pass
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
    return fps, w, h


def frame_to_bytes_png(frame_bgr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", frame_bgr)
    if not ok:
        raise RuntimeError("imencode failed")
    return buf.tobytes()


def bytes_to_frame_png(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("imdecode failed")
    return frame


def combine_frames(frame_paths_or_arrays: list, out_path: str, fps: float, size: tuple[int, int]) -> None:
    w, h = int(size[0]), int(size[1])
    if w < 1 or h < 1:
        raise ValueError("combine_frames: size must be positive (w, h)")
    size = (w, h)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_path, fourcc, fps, size)
    if not writer.isOpened():
        raise RuntimeError("VideoWriter failed")
    written = 0
    try:
        for item in frame_paths_or_arrays:
            if isinstance(item, str):
                frame = cv2.imread(item)
            else:
                frame = item
            if frame is None:
                continue
            if frame.shape[1] != size[0] or frame.shape[0] != size[1]:
                frame = cv2.resize(frame, size)
            writer.write(frame)
            written += 1
    finally:
        try:
            writer.release()
        except Exception:
            pass
    if written == 0:
        raise RuntimeError("combine_frames: no valid frames to write (output would be empty)")


def simple_process_frame(frame_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
