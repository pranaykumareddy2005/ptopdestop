"""Console entry: peerlink-video [gui] | peerlink-video process <video> ..."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path


def _ensure_root_on_path() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def cmd_process(args: argparse.Namespace) -> int:
    """Headless pipeline: extract → distribute (local fallback) → combine."""
    _ensure_root_on_path()
    # region agent log
    try:
        from peerlink_video._debug_log import agent_log
        agent_log("cli.cmd_process", "enter", {"video": args.video, "runId": "repro"}, "H4")
    except Exception:
        pass
    # endregion
    from peerlink_video.config import APP_NAME
    from peerlink_video.peerlink_coordinator import PeerlinkCoordinator
    from peerlink_video.video_split import extract_frames, combine_frames, bytes_to_frame_png

    path = args.video
    if not os.path.isfile(path):
        print("Not a file:", path, file=sys.stderr)
        return 1
    out_path = args.output or os.path.join(os.path.dirname(path) or ".", "peerlink_out.mp4")
    tmp = tempfile.mkdtemp(prefix=APP_NAME + "_cli_")
    c = None
    try:
        c = PeerlinkCoordinator("CLI-Uploader", verbose=args.verbose)
        c.start()
        frame_paths, fps, w, h = extract_frames(path, tmp, max_frames=args.max_frames)
        if not frame_paths:
            print("No frames extracted", file=sys.stderr)
            return 1
        results = c.distribute_frames(frame_paths, fps, w, h, process_local_fallback=True)
        if c.is_cancelled() or not results:
            print("No output (cancelled or failed).", file=sys.stderr)
            return 2
        ordered = [results[i] for i in sorted(results.keys()) if i in results]
        if not ordered:
            print("No output (empty result set).", file=sys.stderr)
            return 2
        try:
            combine_frames([bytes_to_frame_png(b) for b in ordered], out_path, fps, (w, h))
        except Exception as ex:
            # region agent log
            try:
                from peerlink_video._debug_log import agent_log
                agent_log("cli.cmd_process", "combine_failed", {"exc": type(ex).__name__, "runId": "repro"}, "H4")
            except Exception:
                pass
            # endregion
            print("Combine failed:", ex, file=sys.stderr)
            return 2
        print("OK:", out_path)
        return 0
    finally:
        if c is not None:
            try:
                c.stop()
            except Exception:
                pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def launch() -> None:
    """GUI entry point for console script peerlink-video (no args)."""
    _ensure_root_on_path()
    # region agent log
    try:
        from peerlink_video._debug_log import agent_log
        agent_log("cli.launch", "enter_gui", {"runId": "repro"}, "H1")
    except Exception:
        pass
    # endregion
    from main import main as run_app
    run_app()


def main() -> None:
    parser = argparse.ArgumentParser(prog="peerlink-video", description="PeerLink Video — GUI or headless process")
    try:
        from peerlink_video import __version__ as _v
    except Exception:
        _v = "0.3.0"
    parser.add_argument("--version", action="version", version=f"%(prog)s {_v}")
    sub = parser.add_subparsers(dest="command", help="Subcommand (default: open GUI)")

    p_process = sub.add_parser("process", help="Run pipeline without GUI")
    p_process.add_argument("video", help="Input video path")
    p_process.add_argument("-o", "--output", help="Output MP4 path (default: peerlink_out.mp4 next to input)")
    p_process.add_argument("--max-frames", type=int, default=30, help="Max frames to extract (default 30)")
    p_process.add_argument("-v", "--verbose", action="store_true", help="Verbose PeerLink")
    p_process.set_defaults(func=cmd_process)

    args = parser.parse_args()
    if args.command == "process":
        sys.exit(args.func(args))
    launch()


if __name__ == "__main__":
    main()
