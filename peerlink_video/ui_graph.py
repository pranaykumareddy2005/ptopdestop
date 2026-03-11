"""Matplotlib bar chart — bright colours to match app."""
from __future__ import annotations

import tkinter as tk

BG = "#E0F2FE"
CARD = "#FFFFFF"
BAR = "#9333EA"       # bright purple
BAR_EDGE = "#A855F7"
TEXT = "#0C4A6E"
MUTED = "#0369A1"
GRID = "#7DD3FC"


def show_contribution_graph(workers: dict[str, dict], parent=None):
    try:
        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    except Exception:
        return None
    names = list(workers.keys())
    if not names:
        return None
    done = []
    for n in names:
        w = workers.get(n)
        if isinstance(w, dict):
            done.append(int(w.get("done", 0) or 0))
        else:
            done.append(0)
    fig = Figure(figsize=(6, 3.5), dpi=100, facecolor=CARD)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG)
    ax.bar(names, done, color=BAR, edgecolor=BAR_EDGE, linewidth=1.5)
    ax.set_ylabel("Frames processed", color=TEXT, fontsize=11, fontweight="bold")
    ax.set_title("Worker contribution", color=TEXT, fontsize=14, fontweight="bold")
    ax.tick_params(colors=MUTED)
    ax.spines["bottom"].set_color(GRID)
    ax.spines["left"].set_color(GRID)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    win = tk.Toplevel(parent) if parent else tk.Tk()
    win.title("Worker contribution")
    win.configure(bg=BG)
    canvas = FigureCanvasTkAgg(fig, master=win)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
    return win
