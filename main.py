"""
Distributed video processing — PeerLink + YOLO.
Polished UI: card layout, scrollable tabs, clear hierarchy.
"""
from __future__ import annotations

import os
import tempfile
import threading
from tkinter import filedialog

import customtkinter as ctk
import cv2
import numpy as np
from PIL import Image, ImageTk

from peerlink_video.config import APP_NAME, get_local_ip
from peerlink_video.peerlink_coordinator import PeerlinkCoordinator
from peerlink_video.peerlink_worker import PeerlinkWorker
from peerlink_video.peerlink_chat import PeerlinkChat
from peerlink_video.video_split import (
    extract_frames,
    combine_frames,
    bytes_to_frame_png,
    capture_frames_from_camera,
    record_webcam_to_file,
)
from peerlink_video.worker_db import WorkerDB

# ─── Visual theme: bright colours (vivid, high saturation) ─────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# Light airy base so brights pop
COLOR_BG = "#E0F2FE"           # sky 100 — bright light blue wash
COLOR_CARD = "#FFFFFF"         # crisp white cards
COLOR_CARD_BORDER = "#7DD3FC"  # sky 300 — bright border
COLOR_HEADER = "#0EA5E9"       # sky 500 — bright header bar
COLOR_INSET = "#F0F9FF"        # sky 50 — soft blue inset

# Primary = electric cyan-blue
COLOR_ACCENT = "#0284C7"       # sky 600 — strong blue
COLOR_ACCENT_HOVER = "#0EA5E9" # sky 500 — brighter on hover
COLOR_ACCENT_SOFT = "#BAE6FD"  # sky 200 — progress track

# Extra brights for buttons / accents
COLOR_BRIGHT_GREEN = "#16A34A"  # green 600
COLOR_BRIGHT_ORANGE = "#EA580C" # orange 600
COLOR_BRIGHT_PURPLE = "#9333EA" # violet 600
COLOR_BRIGHT_PINK = "#DB2777"   # pink 600

# Text
COLOR_TEXT = "#0C4A6E"         # sky 900 — readable on light
COLOR_MUTED = "#0369A1"        # sky 700
COLOR_SUCCESS = "#15803D"      # green 700
COLOR_WARN = "#CA8A04"         # yellow 600
COLOR_ERR = "#DC2626"          # red 600
COLOR_BTN_SECONDARY = "#38BDF8" # sky 400 — bright secondary
COLOR_BTN_HOVER = "#0EA5E9"    # sky 500
COLOR_ON_BRIGHT = "#FFFFFF"    # text on saturated buttons

FONT_TITLE = ("Segoe UI", 22, "bold")
FONT_HEAD = ("Segoe UI", 13, "bold")
FONT_BODY = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 11)


def _card(parent, **pack_kw) -> ctk.CTkFrame:
    f = ctk.CTkFrame(
        parent,
        fg_color=COLOR_CARD,
        corner_radius=14,
        border_width=1,
        border_color=COLOR_CARD_BORDER,
    )
    f.pack(fill="x", pady=8, padx=2, **pack_kw)
    return f


def _section_title(parent, text: str) -> None:
    ctk.CTkLabel(
        parent,
        text=text,
        font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        text_color=COLOR_TEXT,
        anchor="w",
    ).pack(anchor="w", padx=16, pady=(14, 6))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.configure(fg_color=COLOR_BG)
        self.title("PeerLink Video — Distributed processing")
        self.geometry("1200x820")
        self.minsize(900, 640)

        self._node_name = ctk.StringVar(value=os.environ.get("PEERLINK_NAME", "Node-" + get_local_ip().split(".")[-1]))
        self._coordinator = None
        self._coord_node = None
        self._last_worker_stats = {}
        self._worker = None
        self._worker_node = None
        self._chat = None
        self._temp_dir = None
        self._output_path = None
        self._source_mode = ctk.StringVar(value="file")
        self._video_path = ctk.StringVar()
        self._camera_index = ctk.StringVar(value="0")
        self._camera_frames = ctk.StringVar(value="30")
        self._record_seconds = ctk.StringVar(value="5")
        self._max_frames_extract = ctk.StringVar(value="30")
        self._processing_cancelled = False

        # ─── Header ─────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color=COLOR_HEADER, corner_radius=0, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=12)
        ctk.CTkLabel(inner, text="PeerLink Video", font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"), text_color=COLOR_ON_BRIGHT).pack(side="left")
        ctk.CTkLabel(
            inner,
            text="  ·  LAN + YOLO  ·  ",
            font=ctk.CTkFont(size=12),
            text_color="#E0F2FE",
        ).pack(side="left")
        ctk.CTkLabel(inner, text="Node", font=ctk.CTkFont(size=11), text_color="#E0F2FE").pack(side="right", padx=(0, 6))
        ctk.CTkEntry(inner, textvariable=self._node_name, width=140, height=28, corner_radius=8, fg_color=COLOR_CARD, border_color=COLOR_CARD_BORDER).pack(side="right", padx=4)
        ctk.CTkLabel(inner, text=get_local_ip(), font=ctk.CTkFont(size=11, weight="bold"), text_color="#FDE047").pack(side="right", padx=12)  # bright yellow IP

        # ─── Tab view — bright selected tab ─────────────────────────────
        self.tabs = ctk.CTkTabview(
            self,
            fg_color=COLOR_BG,
            segmented_button_fg_color=COLOR_CARD,
            segmented_button_selected_color=COLOR_BRIGHT_PURPLE,
            segmented_button_selected_hover_color="#A855F7",
            segmented_button_unselected_color=COLOR_ACCENT_SOFT,
            segmented_button_unselected_hover_color=COLOR_BTN_SECONDARY,
            text_color=COLOR_TEXT,
            text_color_disabled=COLOR_MUTED,
            anchor="w",
        )
        self.tabs.pack(fill="both", expand=True, padx=16, pady=(12, 16))
        self.tabs.add("Uploader")
        self.tabs.add("Worker")
        self.tabs.add("Chat")

        self._build_uploader(self.tabs.tab("Uploader"))
        self._build_worker(self.tabs.tab("Worker"))
        self._build_chat(self.tabs.tab("Chat"))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _scroll_tab(self, parent) -> ctk.CTkScrollableFrame:
        """Each tab is scrollable so layout never clips."""
        scroll = ctk.CTkScrollableFrame(parent, fg_color=COLOR_BG, corner_radius=0)
        scroll.pack(fill="both", expand=True)
        return scroll

    def _build_uploader(self, parent):
        root = self._scroll_tab(parent)

        # --- Source card ---
        card = _card(root)
        _section_title(card, "Video source")
        src = ctk.CTkFrame(card, fg_color="transparent")
        src.pack(fill="x", padx=16, pady=(0, 8))
        row1 = ctk.CTkFrame(src, fg_color="transparent")
        row1.pack(fill="x", pady=4)
        ctk.CTkButton(
            row1, text="Open video file", command=self._pick_video, width=160, height=36,
            corner_radius=8, fg_color=COLOR_BRIGHT_GREEN, hover_color="#22C55E", text_color=COLOR_ON_BRIGHT,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row1, text="Capture from camera", command=self._capture_from_camera, width=170, height=36,
            corner_radius=8, fg_color=COLOR_BRIGHT_ORANGE, hover_color="#F97316", text_color=COLOR_ON_BRIGHT,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            row1, text="Record from camera", command=self._record_from_camera, width=150, height=36,
            corner_radius=8, fg_color=COLOR_BRIGHT_PINK, hover_color="#EC4899", text_color=COLOR_ON_BRIGHT,
        ).pack(side="left", padx=4)
        row2 = ctk.CTkFrame(src, fg_color="transparent")
        row2.pack(fill="x", pady=8)
        for label, var, w in [("Camera #", self._camera_index, 50), ("Frames", self._camera_frames, 55), ("Record sec", self._record_seconds, 50)]:
            ctk.CTkLabel(row2, text=label, text_color=COLOR_MUTED, font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
            ctk.CTkEntry(row2, textvariable=var, width=w, height=28, corner_radius=6).pack(side="left", padx=(0, 14))
        path_fr = ctk.CTkFrame(card, fg_color=COLOR_INSET, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        path_fr.pack(fill="x", padx=16, pady=(4, 8))
        ctk.CTkLabel(path_fr, textvariable=self._video_path, wraplength=1000, text_color=COLOR_MUTED, font=ctk.CTkFont(size=11), anchor="w").pack(fill="x", padx=12, pady=10)

        # Live camera / record preview (fixed box)
        preview_wrap = ctk.CTkFrame(card, fg_color="transparent")
        preview_wrap.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(preview_wrap, text="Camera preview (capture / record)", text_color=COLOR_MUTED, font=ctk.CTkFont(size=11), anchor="w").pack(anchor="w", pady=(0, 4))
        self._camera_preview_box = ctk.CTkFrame(
            preview_wrap, width=360, height=240, fg_color="#0F172A", corner_radius=10,
            border_width=2, border_color=COLOR_CARD_BORDER,
        )
        self._camera_preview_box.pack(anchor="w")
        self._camera_preview_box.pack_propagate(False)
        self._camera_preview_label = ctk.CTkLabel(
            self._camera_preview_box, text="No preview — use Capture or Record to see live feed.",
            text_color="#94A3B8", font=ctk.CTkFont(size=11), wraplength=320,
        )
        self._camera_preview_label.place(relx=0.5, rely=0.5, anchor="center")
        self._camera_preview_photo = None

        # --- Network card ---
        card2 = _card(root)
        _section_title(card2, "Network")
        net = ctk.CTkFrame(card2, fg_color="transparent")
        net.pack(fill="x", padx=16, pady=(0, 14))
        self._peer_count = ctk.StringVar(value="LAN devices: 0")
        self._worker_list = ctk.StringVar(value="Workers: —")
        ctk.CTkLabel(net, textvariable=self._peer_count, text_color=COLOR_TEXT, font=ctk.CTkFont(size=12)).pack(anchor="w", pady=2)
        ctk.CTkLabel(net, textvariable=self._worker_list, text_color=COLOR_MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", pady=2)

        # --- Actions ---
        card3 = _card(root)
        _section_title(card3, "Run")
        act = ctk.CTkFrame(card3, fg_color="transparent")
        act.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(act, text="Max frames (file source)", text_color=COLOR_MUTED, font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))
        ctk.CTkEntry(act, textvariable=self._max_frames_extract, width=50, height=32, corner_radius=6).pack(side="left", padx=(0, 14))
        ctk.CTkButton(
            act, text="Start processing", command=self._start_processing, width=200, height=40,
            corner_radius=10, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color=COLOR_ON_BRIGHT, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            act, text="Worker contribution graph", command=self._show_graph, width=200, height=40,
            corner_radius=10, fg_color=COLOR_BRIGHT_PURPLE, hover_color="#A855F7", text_color=COLOR_ON_BRIGHT,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            act, text="Cancel", command=self._cancel_processing, width=90, height=40,
            corner_radius=10, fg_color="#64748B", hover_color="#94A3B8", text_color=COLOR_ON_BRIGHT,
        ).pack(side="left", padx=8)

        # --- Progress card ---
        card4 = _card(root)
        _section_title(card4, "Progress")
        prog = ctk.CTkFrame(card4, fg_color="transparent")
        prog.pack(fill="x", padx=16, pady=(0, 6))
        self._progress_bar = ctk.CTkProgressBar(prog, height=16, corner_radius=8, progress_color="#22C55E", fg_color=COLOR_ACCENT_SOFT)
        self._progress_bar.pack(fill="x", pady=6)
        self._progress_bar.set(0)
        self._progress_text = ctk.CTkTextbox(card4, height=100, corner_radius=8, fg_color=COLOR_INSET, border_color=COLOR_CARD_BORDER, border_width=1, font=ctk.CTkFont(size=11), text_color=COLOR_TEXT)
        self._progress_text.pack(fill="x", padx=16, pady=8)
        leg = ctk.CTkFrame(card4, fg_color="transparent")
        leg.pack(fill="x", padx=16, pady=4)
        for txt, col in [("Pending", "#94A3B8"), ("Claimed", "#F59E0B"), ("Done", "#22C55E"), ("Failed", "#EF4444"), ("Cancelled", "#64748B")]:
            ctk.CTkFrame(leg, width=12, height=12, fg_color=col, corner_radius=3).pack(side="left", padx=(0, 4))
            ctk.CTkLabel(leg, text=txt, text_color=COLOR_MUTED, font=ctk.CTkFont(size=10)).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(card4, text="Per-frame status (updates while processing)", text_color=COLOR_MUTED, font=ctk.CTkFont(size=10), anchor="w").pack(fill="x", padx=16, pady=(4, 2))
        self._frame_grid_scroll = ctk.CTkScrollableFrame(card4, height=200, fg_color=COLOR_INSET, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        self._frame_grid_scroll.pack(fill="both", expand=True, padx=16, pady=6)
        self._frame_grid_cells = []
        self._frame_grid_label = ctk.CTkLabel(card4, text="Frame counts appear when processing runs.", text_color=COLOR_MUTED, font=ctk.CTkFont(size=11), anchor="w")
        self._frame_grid_label.pack(fill="x", padx=16, pady=(0, 14))

        # --- Peers card ---
        card5 = _card(root)
        _section_title(card5, "Connected peers")
        self._connected_devices = ctk.CTkTextbox(card5, height=80, corner_radius=8, fg_color=COLOR_INSET, border_color=COLOR_CARD_BORDER, border_width=1, font=ctk.CTkFont(size=11), text_color=COLOR_TEXT)
        self._connected_devices.pack(fill="x", padx=16, pady=(0, 14))
        self._connected_devices.insert("end", "Start processing or worker to discover peers.\n")

        # --- Output card ---
        card6 = _card(root)
        _section_title(card6, "Output")
        out_btn = ctk.CTkFrame(card6, fg_color="transparent")
        out_btn.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(
            out_btn, text="Save video as…", command=self._save_output_as, width=140, height=32,
            corner_radius=8, fg_color=COLOR_BRIGHT_ORANGE, hover_color="#F97316", text_color=COLOR_ON_BRIGHT,
        ).pack(side="left")
        out_fr = ctk.CTkFrame(card6, fg_color=COLOR_INSET, corner_radius=10, border_width=1, border_color=COLOR_CARD_BORDER)
        out_fr.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._output_preview = ctk.CTkLabel(out_fr, text="Preview appears here after processing.", text_color=COLOR_MUTED, font=ctk.CTkFont(size=12))
        self._output_preview.pack(fill="both", expand=True, padx=8, pady=12)
        ctk.CTkLabel(out_fr, text="Result frames (after distribution)", text_color=COLOR_MUTED, font=ctk.CTkFont(size=10), anchor="w").pack(anchor="w", padx=8, pady=(0, 4))
        self._frames_gallery_scroll = ctk.CTkScrollableFrame(out_fr, height=100, orientation="horizontal", fg_color=COLOR_CARD, corner_radius=8, border_width=1, border_color=COLOR_CARD_BORDER)
        self._frames_gallery_scroll.pack(fill="x", padx=8, pady=(0, 12))

    def _build_worker(self, parent):
        root = self._scroll_tab(parent)
        for title, var_attr, default in [
            ("Uploader", "_worker_uploader", "Tasks from LAN uploaders via PeerLink."),
            ("Status", "_worker_status", "Stopped."),
            ("Performance", "_worker_metrics", "—"),
            ("ACO & credits", "_worker_aco", "Pheromone · capability · battery · credits"),
        ]:
            card = _card(root)
            _section_title(card, title)
            var = ctk.StringVar(value=default)
            setattr(self, var_attr, var)
            ctk.CTkLabel(card, textvariable=var, wraplength=1000, text_color=COLOR_MUTED if var_attr != "_worker_status" else COLOR_TEXT, font=ctk.CTkFont(size=12), justify="left", anchor="w").pack(fill="x", padx=16, pady=(0, 14))

        card = _card(root)
        _section_title(card, "Controls & job history")
        btn_fr = ctk.CTkFrame(card, fg_color="transparent")
        btn_fr.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(btn_fr, text="Start worker", command=self._start_worker, width=120, height=34, corner_radius=8, fg_color=COLOR_BRIGHT_GREEN, hover_color="#22C55E", text_color=COLOR_ON_BRIGHT).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_fr, text="Stop", command=self._stop_worker, width=80, height=34, corner_radius=8, fg_color="#EF4444", hover_color="#F87171", text_color=COLOR_ON_BRIGHT).pack(side="left", padx=4)
        ctk.CTkButton(btn_fr, text="Refresh DB", command=self._refresh_worker_db, width=100, height=34, corner_radius=8, fg_color=COLOR_BTN_SECONDARY, hover_color=COLOR_BTN_HOVER, text_color=COLOR_ON_BRIGHT).pack(side="left", padx=4)
        ctk.CTkButton(btn_fr, text="Export CSV", command=self._export_worker_csv, width=100, height=34, corner_radius=8, fg_color=COLOR_BRIGHT_ORANGE, hover_color="#F97316", text_color=COLOR_ON_BRIGHT).pack(side="left", padx=4)
        self._worker_db_text = ctk.CTkTextbox(card, height=240, corner_radius=8, fg_color=COLOR_INSET, border_color=COLOR_CARD_BORDER, border_width=1, font=ctk.CTkFont(size=11), text_color=COLOR_TEXT)
        self._worker_db_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._refresh_worker_db()

    def _build_chat(self, parent):
        root = self._scroll_tab(parent)
        card = _card(root)
        _section_title(card, "Messaging")
        ctk.CTkLabel(card, text="Broadcast to everyone or send to one peer.", text_color=COLOR_MUTED, font=ctk.CTkFont(size=11), anchor="w").pack(anchor="w", padx=16, pady=(0, 8))
        peer_row = ctk.CTkFrame(card, fg_color="transparent")
        peer_row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(peer_row, text="Peer", text_color=COLOR_MUTED).pack(side="left", padx=(0, 8))
        self._chat_peer_var = ctk.StringVar(value="")
        self._chat_peer_combo = ctk.CTkComboBox(peer_row, variable=self._chat_peer_var, values=[], width=220, height=32, corner_radius=8)
        self._chat_peer_combo.pack(side="left", padx=4)
        ctk.CTkButton(peer_row, text="Refresh peers", command=self._refresh_chat_peers, width=100, height=32, corner_radius=8, fg_color=COLOR_BRIGHT_PURPLE, hover_color="#A855F7", text_color=COLOR_ON_BRIGHT).pack(side="left", padx=12)
        self._chat_log = ctk.CTkTextbox(card, height=280, corner_radius=8, fg_color=COLOR_INSET, border_color=COLOR_CARD_BORDER, border_width=1, font=ctk.CTkFont(size=12), text_color=COLOR_TEXT)
        self._chat_log.pack(fill="both", expand=True, padx=16, pady=12)
        entry_fr = ctk.CTkFrame(card, fg_color="transparent")
        entry_fr.pack(fill="x", padx=16, pady=(0, 16))
        self._chat_entry = ctk.CTkEntry(entry_fr, placeholder_text="Type a message…", height=40, corner_radius=10, border_color=COLOR_CARD_BORDER)
        self._chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(entry_fr, text="To all", command=self._send_chat_broadcast, width=90, height=40, corner_radius=10, fg_color=COLOR_BRIGHT_ORANGE, hover_color="#F97316", text_color=COLOR_ON_BRIGHT).pack(side="right", padx=4)
        ctk.CTkButton(entry_fr, text="To peer", command=self._send_chat_p2p, width=90, height=40, corner_radius=10, fg_color=COLOR_BRIGHT_PINK, hover_color="#EC4899", text_color=COLOR_ON_BRIGHT).pack(side="right", padx=4)

    # ─── Callbacks (unchanged logic) ─────────────────────────────────────
    def _pick_video(self):
        path = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.avi *.mkv"), ("All", "*.*")])
        if path:
            self._source_mode.set("file")
            self._video_path.set(path)

    def _capture_from_camera(self):
        try:
            cam = int(self._camera_index.get().strip() or "0")
            n = int(self._camera_frames.get().strip() or "30")
        except ValueError:
            self._progress_text.insert("end", "Camera # and frame count must be numbers.\n")
            return
        if self._temp_dir:
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = tempfile.mkdtemp(prefix=APP_NAME + "_cam_")
        self._progress_text.insert("end", f"Capturing {n} frames from camera {cam}…\n")
        self.update()

        def on_frame(bgr):
            # Copy buffer — OpenCV may reuse; UI must run on main thread
            try:
                arr = np.ascontiguousarray(bgr)
                self.after(0, lambda a=arr: self._apply_camera_preview(a))
            except Exception:
                pass

        def run():
            try:
                frame_paths, fps, w, h = capture_frames_from_camera(
                    self._temp_dir, max_frames=n, fps=25.0, camera_index=cam, on_frame=on_frame
                )
                self._camera_capture = (frame_paths, fps, w, h)
                self._source_mode.set("camera")
                self._video_path.set(f"(camera) {len(frame_paths)} frames @ {w}x{h}")
                self.after(0, lambda: self._progress_text.insert("end", f"Ready: {len(frame_paths)} frames. Start processing.\n"))
                self.after(0, self._clear_camera_preview)
            except Exception as e:
                self.after(0, lambda err=str(e): self._progress_text.insert("end", f"Camera error: {err}\n"))

        threading.Thread(target=run, daemon=True).start()

    def _record_from_camera(self):
        try:
            cam = int(self._camera_index.get().strip() or "0")
            sec = float(self._record_seconds.get().strip() or "5")
        except ValueError:
            self._progress_text.insert("end", "Camera # and seconds must be numbers.\n")
            return
        if self._temp_dir:
            import shutil
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = tempfile.mkdtemp(prefix=APP_NAME + "_rec_")
        out_path = os.path.join(self._temp_dir, "webcam_record.mp4")
        self._progress_text.insert("end", f"Recording {sec}s…\n")
        self.update()

        def on_frame(bgr):
            try:
                arr = np.ascontiguousarray(bgr)
                self.after(0, lambda a=arr: self._apply_camera_preview(a))
            except Exception:
                pass

        def run():
            try:
                record_webcam_to_file(out_path, duration_sec=sec, fps=20.0, camera_index=cam, on_frame=on_frame)
                self._source_mode.set("file")
                self._video_path.set(out_path)
                self.after(0, lambda: self._progress_text.insert("end", f"Recorded. Start processing.\n"))
                self.after(0, self._clear_camera_preview)
            except Exception as e:
                self.after(0, lambda err=str(e): self._progress_text.insert("end", f"Record error: {err}\n"))

        threading.Thread(target=run, daemon=True).start()

    def _update_connected_devices(self):
        if self._coord_node:
            names = self._coord_node.peer_names()
            self._connected_devices.delete("1.0", "end")
            for n in names:
                self._connected_devices.insert("end", f"  {n}\n")
            if not names:
                self._connected_devices.insert("end", "  No peers yet.\n")

    def _show_graph(self):
        from peerlink_video.ui_graph import show_contribution_graph
        if not self._last_worker_stats:
            self._progress_text.insert("end", "Run processing first.\n")
            return
        show_contribution_graph(self._last_worker_stats, self)

    def _start_processing(self):
        name = self._node_name.get().strip() or "Uploader"
        frame_paths = None
        fps, w, h = 25.0, 640, 480
        if self._source_mode.get() == "camera" and getattr(self, "_camera_capture", None):
            frame_paths, fps, w, h = self._camera_capture
        else:
            path = self._video_path.get()
            if not path or not os.path.isfile(path):
                self._progress_text.insert("end", "Select a file or capture from camera first.\n")
                return

        def on_progress(d):
            self._last_worker_stats = d.get("workers", {})
            fs = d.get("frame_status", {})
            pending = sum(1 for v in fs.values() if v == "pending")
            claimed = sum(1 for v in fs.values() if v == "claimed")
            done = sum(1 for v in fs.values() if v == "done")
            failed = sum(1 for v in fs.values() if v == "failed")
            cancelled = sum(1 for v in fs.values() if v == "cancelled")
            total = len(fs) or getattr(self, "_processing_total_frames", 1) or 1
            pct = (done + failed + cancelled) / total if total else 0
            self.after(0, lambda p=pct: self._progress_bar.set(min(1.0, p)))
            label_text = (
                f"Pending {pending}  ·  Claimed {claimed}  ·  Done {done}  ·  Failed {failed}"
                + (f"  ·  Cancelled {cancelled}" if cancelled else "")
            )
            self.after(0, lambda t=label_text: self._frame_grid_label.configure(text=t))
            # Copy fs for lambda — avoid stale closure if dict is mutated later
            fs_copy = dict(fs)
            self.after(0, lambda fsc=fs_copy: self._update_frame_grid_cells(fsc))
            # Do not insert a line every tick (floods the log); grid + bar + label are enough
            node = self._coord_node
            coord = self._coordinator
            if node and coord:
                try:
                    peers = [p for p in node.peer_names() if p != name]
                    peer_count = len(peers) + 1
                except Exception:
                    peer_count = 0
                workers_keys = list(coord._workers.keys())
                self.after(0, lambda c=peer_count: self._peer_count.set(f"LAN devices: {c}"))
                self.after(0, lambda w=workers_keys: self._worker_list.set(f"Workers: {w}"))
                self.after(0, self._update_connected_devices)

        if self._coordinator:
            self._coordinator.stop()
        self._processing_cancelled = False
        self._coordinator = PeerlinkCoordinator(name, on_progress=on_progress, verbose=False)
        self._coord_node = self._coordinator.start()
        self._coord_node.wait_for_peers(1, timeout=3.0)
        self._peer_count.set(f"LAN devices: {len(self._coord_node.peer_names())}")
        self._update_connected_devices()
        self._progress_text.insert("end", "Preparing…\n")
        self.update()

        if self._source_mode.get() != "camera" or not frame_paths:
            if self._temp_dir and self._source_mode.get() == "file":
                import shutil
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = tempfile.mkdtemp(prefix=APP_NAME + "_")
            path = self._video_path.get()
            try:
                max_f = int(self._max_frames_extract.get().strip() or "30")
                max_f = max(1, min(max_f, 500))
            except ValueError:
                max_f = 30
            try:
                frame_paths, fps, w, h = extract_frames(path, self._temp_dir, max_frames=max_f)
            except Exception as e:
                self._progress_text.insert("end", f"Extract failed: {e}\n")
                if self._coordinator:
                    self._coordinator.stop()
                    self._coord_node = None
                return

        self._progress_text.insert("end", f"{len(frame_paths)} frames @ {fps} fps\n")
        self._processing_total_frames = len(frame_paths)
        self._progress_bar.set(0)

        def run():
            # Capture coordinator for this run only — avoid stopping a newer run if user clicked Start again
            coord = self._coordinator
            if coord is None:
                return
            results = coord.distribute_frames(frame_paths, fps, w, h)
            cancelled = coord.is_cancelled()
            if cancelled or not results:

                def _abort():
                    msg = "Cancelled — no output written.\n" if cancelled else "No output.\n"
                    self._progress_text.insert("end", msg)
                    if self._coordinator is coord:
                        coord.stop()
                        self._coord_node = None

                self.after(0, _abort)
                return
            ordered = [results[i] for i in sorted(results.keys()) if i in results]
            if not ordered:
                self.after(0, lambda: self._progress_text.insert("end", "No output.\n"))
                return
            out_path = os.path.join(self._temp_dir, "output.mp4")
            try:
                combine_frames([bytes_to_frame_png(b) for b in ordered], out_path, fps, (w, h))
            except Exception as ex:
                self.after(0, lambda e=str(ex): self._progress_text.insert("end", f"Combine failed: {e}\n"))
                return
            self._output_path = out_path
            self.after(0, lambda: self._progress_bar.set(1.0))
            self.after(0, lambda: self._show_preview(out_path))
            self.after(0, lambda: self._fill_frames_gallery(ordered))
            self.after(0, lambda: self._progress_text.insert("end", f"Saved: {out_path}\n"))

        threading.Thread(target=run, daemon=True).start()

    def _cancel_processing(self) -> None:
        if self._coordinator and not self._coordinator.is_cancelled():
            self._coordinator.cancel()
            self._processing_cancelled = True
            self._progress_text.insert("end", "Cancel requested…\n")

    def _show_preview(self, path):
        try:
            import cv2
            cap = cv2.VideoCapture(path)
            try:
                ok, frame = cap.read()
            finally:
                cap.release()
            if ok:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                im = Image.fromarray(frame)
                im.thumbnail((720, 405))
                photo = ImageTk.PhotoImage(im)
                self._output_preview.configure(image=photo, text="")
                self._output_preview.image = photo
        except Exception as e:
            self._output_preview.configure(text=str(e))

    def _start_worker(self):
        if self._worker:
            self._worker.stop()
        name = self._node_name.get().strip() or "Worker"
        db_path = os.path.join(os.path.expanduser("~"), f"{APP_NAME}_worker_{name}.db")

        def on_metrics(m):
            self.after(0, lambda: self._worker_uploader.set("Receiving from LAN uploaders over PeerLink."))
            self.after(0, lambda: self._worker_metrics.set(
                f"Received {m.get('frames_received')}  ·  Processed {m.get('frames_processed')}  ·  {m.get('speed_fps', 0):.1f} fps"
            ))
            self.after(0, lambda: self._worker_aco.set(
                f"Pheromone {m.get('pheromone', 0):.2f}  ·  Capability {m.get('capability', 1)}  ·  Battery {m.get('battery', 1)}  ·  Credits {m.get('credits_earned', 0)}"
            ))

        try:
            self._worker = PeerlinkWorker(name, db_path=db_path, verbose=False)
            self._worker.set_metrics_callback(on_metrics)
            self._worker_node = self._worker.start()
            self._worker_status.set(f"Online — port {self._worker_node.port}")
            self._refresh_worker_db()
        except Exception as e:
            self._worker = None
            self._worker_node = None
            self._worker_status.set(f"Start failed: {e}")

    def _stop_worker(self):
        if self._worker:
            self._worker.stop()
            self._worker = None
            self._worker_node = None
        self._worker_status.set("Stopped.")

    def _export_worker_csv(self):
        name = self._node_name.get().strip() or "Worker"
        db_path = os.path.join(os.path.expanduser("~"), f"{APP_NAME}_worker_{name}.db")
        if not os.path.isfile(db_path):
            self._worker_db_text.insert("end", "No DB to export.\n")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"{APP_NAME}_jobs.csv")
        if path:
            n = WorkerDB(db_path).export_csv(path)
            self._worker_db_text.insert("end", f"Exported {n} rows to {path}\n")

    def _refresh_worker_db(self):
        name = self._node_name.get().strip() or "Worker"
        db_path = os.path.join(os.path.expanduser("~"), f"{APP_NAME}_worker_{name}.db")
        self._worker_db_text.delete("1.0", "end")
        if not os.path.isfile(db_path):
            self._worker_db_text.insert("end", "No history yet.\n")
            return
        db = WorkerDB(db_path)
        for row in db.job_history(80):
            self._worker_db_text.insert("end", f"{row}\n")

    def _ensure_chat(self):
        name = self._node_name.get().strip() or "Node"
        try:
            if not self._coord_node and not self._worker_node:
                w = PeerlinkWorker(name + "-chat", verbose=False)
                node = w.start()
                self._worker = w
                self._worker_node = node
                self._chat = PeerlinkChat(node, on_message=lambda s, t: self.after(0, lambda: self._chat_log.insert("end", f"{s}: {t}\n")))
            elif self._worker_node and not self._chat:
                self._chat = PeerlinkChat(self._worker_node, on_message=lambda s, t: self.after(0, lambda: self._chat_log.insert("end", f"{s}: {t}\n")))
            elif self._coord_node and not self._chat:
                self._chat = PeerlinkChat(self._coord_node, on_message=lambda s, t: self.after(0, lambda: self._chat_log.insert("end", f"{s}: {t}\n")))
        except Exception as e:
            self._chat_log.insert("end", f"Chat init failed: {e}\n")

    def _refresh_chat_peers(self):
        self._ensure_chat()
        node = self._coord_node or self._worker_node
        if not node:
            return
        names = [p for p in node.peer_names() if p != node.node_name]
        self._chat_peer_combo.configure(values=names)
        if names and not self._chat_peer_var.get():
            self._chat_peer_var.set(names[0])

    def _send_chat_broadcast(self):
        text = self._chat_entry.get().strip()
        if not text:
            return
        self._ensure_chat()
        if self._chat:
            self._chat.broadcast(text)
        self._chat_log.insert("end", f"You (all): {text}\n")
        self._chat_entry.delete(0, "end")

    def _send_chat_p2p(self):
        text = self._chat_entry.get().strip()
        if not text:
            return
        peer = self._chat_peer_var.get().strip()
        if not peer:
            self._chat_log.insert("end", "Pick a peer and Refresh.\n")
            return
        self._ensure_chat()
        if self._chat:
            try:
                self._chat.send_to(peer, text)
                self._chat_log.insert("end", f"You → {peer}: {text}\n")
            except Exception as e:
                self._chat_log.insert("end", f"Failed: {e}\n")
        self._chat_entry.delete(0, "end")

    def _save_output_as(self):
        if not self._output_path or not os.path.isfile(self._output_path):
            self._progress_text.insert("end", "No output yet.\n")
            return
        path = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")], initialfile="output.mp4")
        if path:
            import shutil
            shutil.copy2(self._output_path, path)
            self._progress_text.insert("end", f"Copied to {path}\n")

    def _apply_camera_preview(self, bgr: np.ndarray) -> None:
        """Main thread: show BGR frame in preview box."""
        try:
            if bgr is None or bgr.size == 0:
                return
            h, w = bgr.shape[:2]
            max_w, max_h = 352, 228
            scale = min(max_w / w, max_h / h, 1.0)
            if scale < 1.0:
                bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            im = Image.fromarray(rgb)
            photo = ImageTk.PhotoImage(im)
            self._camera_preview_photo = photo
            self._camera_preview_label.configure(image=photo, text="")
            self._camera_preview_label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception:
            pass

    def _clear_camera_preview(self) -> None:
        self._camera_preview_photo = None
        self._camera_preview_label.configure(image="", text="No preview — use Capture or Record.")
        self._camera_preview_label.place(relx=0.5, rely=0.5, anchor="center")

    def _fill_frames_gallery(self, ordered_bytes: list) -> None:
        """Show thumbnails of processed frames in horizontal strip."""
        if not getattr(self, "_frames_gallery_scroll", None):
            return
        for w in self._frames_gallery_scroll.winfo_children():
            w.destroy()
        if not ordered_bytes:
            return
        n = min(len(ordered_bytes), 36)
        for idx in range(n):
            try:
                bgr = bytes_to_frame_png(ordered_bytes[idx])
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                im = Image.fromarray(rgb)
                im.thumbnail((72, 48))
                photo = ImageTk.PhotoImage(im)
                fr = ctk.CTkFrame(self._frames_gallery_scroll, fg_color=COLOR_CARD, corner_radius=6, border_width=1, border_color=COLOR_CARD_BORDER)
                fr.pack(side="left", padx=4, pady=6)
                lb = ctk.CTkLabel(fr, image=photo, text="")
                lb.pack(padx=2, pady=2)
                lb.image = photo
                ctk.CTkLabel(fr, text=f"#{idx}", text_color=COLOR_MUTED, font=ctk.CTkFont(size=9)).pack()
            except Exception:
                pass

    def _update_frame_grid_cells(self, frame_status: dict) -> None:
        """Rebuild scrollable grid: each cell shows frame index + status text."""
        try:
            scroll = self._frame_grid_scroll
        except Exception:
            return
        colors = {"pending": "#94A3B8", "claimed": "#FBBF24", "done": "#4ADE80", "failed": "#F87171", "cancelled": "#64748B"}
        labels = {"pending": "PENDING", "claimed": "CLAIMED", "done": "DONE", "failed": "FAILED", "cancelled": "CANCELLED"}
        for w in scroll.winfo_children():
            w.destroy()
        self._frame_grid_cells.clear()

        def _sort_key(x):
            try:
                return int(x)
            except (TypeError, ValueError):
                return 0

        keys = sorted(frame_status.keys(), key=_sort_key)
        cols = 8
        row_fr = None
        for j, i in enumerate(keys):
            if j % cols == 0:
                row_fr = ctk.CTkFrame(scroll, fg_color="transparent")
                row_fr.pack(fill="x", pady=2)
            st = frame_status.get(i, "pending")
            col = colors.get(st, "#94A3B8")
            cell = ctk.CTkFrame(row_fr, fg_color=col, corner_radius=6, border_width=1, border_color=COLOR_CARD_BORDER)
            cell.pack(side="left", padx=3, pady=2)
            ctk.CTkLabel(cell, text=f"F{i}", text_color="#0F172A", font=ctk.CTkFont(size=10, weight="bold")).pack(padx=6, pady=(4, 0))
            ctk.CTkLabel(cell, text=labels.get(st, st.upper()), text_color="#0F172A", font=ctk.CTkFont(size=9)).pack(padx=6, pady=(0, 4))
            self._frame_grid_cells.append(cell)

    def _on_close(self):
        try:
            if self._coordinator:
                self._coordinator.stop()
        except Exception:
            pass
        try:
            if self._worker:
                self._worker.stop()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    # region agent log
    try:
        from peerlink_video._debug_log import agent_log
        agent_log("main.py:main", "GUI main entry", {"runId": "repro"}, "H1")
    except Exception:
        pass
    # endregion
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        # region agent log
        try:
            from peerlink_video._debug_log import agent_log
            import traceback
            agent_log(
                "main.py:main",
                "GUI crash",
                {"runId": "repro", "exc_type": type(e).__name__, "traceback": traceback.format_exc()[-2000:]},
                "H1",
            )
        except Exception:
            pass
        # endregion
        raise


if __name__ == "__main__":
    main()
