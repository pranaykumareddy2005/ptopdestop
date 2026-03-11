"""
Smoke test without GUI: local-only pipeline (no workers required).
Usage: python run_smoke.py <video.mp4>
       python run_smoke.py <video.mp4> --keep   # leave temp dir for inspection
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

from peerlink_video.config import APP_NAME
from peerlink_video.peerlink_coordinator import PeerlinkCoordinator
from peerlink_video.video_split import extract_frames, combine_frames, bytes_to_frame_png


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test: extract → distribute (local fallback) → combine")
    parser.add_argument("video", help="Path to input video")
    parser.add_argument("--keep", action="store_true", help="Do not delete temp dir after run")
    parser.add_argument("--max-frames", type=int, default=5, help="Max frames to extract (default 5 for quick smoke)")
    args = parser.parse_args()
    path = args.video
    if not os.path.isfile(path):
        print("Not a file:", path)
        return 1
    tmp = tempfile.mkdtemp(prefix=APP_NAME + "_smoke_")
    c = None
    try:
        c = PeerlinkCoordinator("SmokeUploader", verbose=False)
        c.start()
        frame_paths, fps, w, h = extract_frames(path, tmp, max_frames=args.max_frames)
        if not frame_paths:
            print("No frames extracted")
            return 1
        results = c.distribute_frames(frame_paths, fps, w, h, process_local_fallback=True)
        if not results:
            print("No results from distribute_frames")
            return 2
        ordered = [results[i] for i in sorted(results.keys()) if i in results]
        if not ordered:
            print("Empty ordered results")
            return 2
        out_path = os.path.join(tmp, "out.mp4")
        try:
            combine_frames([bytes_to_frame_png(b) for b in ordered], out_path, fps, (w, h))
        except Exception as ex:
            print("Combine failed:", ex, file=sys.stderr)
            return 2
        print("OK:", out_path)
        if args.keep:
            print("Temp dir kept:", tmp)
        return 0
    finally:
        if c is not None:
            try:
                c.stop()
            except Exception:
                pass
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
