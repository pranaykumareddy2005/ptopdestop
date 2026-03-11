"""
YOLO inference for distributed video frames.

Thread-safety:
- Model is loaded once under _MODEL_LOCK (race: double load on first concurrent frames).
- predict() is called under _INFER_LOCK by default because many backends are not
  thread-safe; optional allow_parallel for batched single-thread workers.
"""
from __future__ import annotations

import os
import threading
from typing import Any

import numpy as np

# BGR frame in/out
_Model = Any
_model: _Model | None = None
_model_name: str = ""
_MODEL_LOCK = threading.Lock()
_INFER_LOCK = threading.Lock()


def get_model(model_name: str | None = None) -> Any:
    """
    Lazy singleton YOLO model. model_name examples: 'yolov8n.pt', 'yolov8s.pt'.
    Env PEERLINK_YOLO_MODEL overrides default.
    """
    global _model, _model_name
    name = model_name or os.environ.get("PEERLINK_YOLO_MODEL", "yolov8n.pt")
    with _MODEL_LOCK:
        if _model is not None and _model_name == name:
            return _model
        try:
            from ultralytics import YOLO
        except ImportError as e:
            raise RuntimeError("Install ultralytics: pip install ultralytics") from e
        _model = YOLO(name)
        _model_name = name
        return _model


def process_frame_yolo(
    frame_bgr: np.ndarray,
    model_name: str | None = None,
    conf: float = 0.25,
    iou: float = 0.45,
) -> np.ndarray:
    """
    Run YOLO on frame; return annotated BGR image (boxes drawn).
    Serialized through _INFER_LOCK to avoid concurrent predict() races.
    """
    model = get_model(model_name)
    # Ultralytics returns plotted BGR when plot=True
    with _INFER_LOCK:
        results = model.predict(
            source=frame_bgr,
            conf=conf,
            iou=iou,
            verbose=False,
        )
    if not results:
        return frame_bgr
    # result.plot() -> RGB; convert to BGR for OpenCV pipeline
    plotted_rgb = results[0].plot()
    if plotted_rgb is None:
        return frame_bgr
    import cv2
    if len(plotted_rgb.shape) == 3 and plotted_rgb.shape[2] == 3:
        return cv2.cvtColor(plotted_rgb, cv2.COLOR_RGB2BGR)
    return frame_bgr


def process_frame(frame_bgr: np.ndarray) -> np.ndarray:
    """Default pipeline entry: YOLO if available, else grayscale fallback."""
    try:
        return process_frame_yolo(frame_bgr)
    except Exception:
        import cv2
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
