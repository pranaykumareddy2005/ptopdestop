"""SQLite local database for worker activity."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path


class WorkerDB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self.path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_id TEXT,
                        uploader_name TEXT,
                        status TEXT,
                        frames_processed INTEGER,
                        date TEXT,
                        time TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS stats (
                        key TEXT PRIMARY KEY,
                        value INTEGER
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def add_job(self, job_id: str, uploader_name: str, status: str, frames_processed: int) -> None:
        now = datetime.now()
        with self._lock:
            conn = sqlite3.connect(self.path)
            try:
                conn.execute(
                    "INSERT INTO jobs (job_id, uploader_name, status, frames_processed, date, time) VALUES (?,?,?,?,?,?)",
                    (job_id, uploader_name, status, frames_processed, now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")),
                )
                conn.commit()
            finally:
                conn.close()

    def increment_stat(self, key: str, delta: int = 1) -> None:
        with self._lock:
            conn = sqlite3.connect(self.path)
            try:
                conn.execute(
                    "INSERT INTO stats (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value = value + ?",
                    (key, delta, delta),
                )
                conn.commit()
            finally:
                conn.close()

    def get_stat(self, key: str) -> int:
        with self._lock:
            conn = sqlite3.connect(self.path)
            try:
                r = conn.execute("SELECT value FROM stats WHERE key = ?", (key,)).fetchone()
                return int(r[0]) if r else 0
            finally:
                conn.close()

    def export_csv(self, out_path: str | Path) -> int:
        """Write job_history to CSV; returns row count written."""
        import csv

        rows = self.job_history(limit=10_000)
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["job_id", "uploader_name", "status", "frames_processed", "date", "time"])
            for r in rows:
                w.writerow(r)
        return len(rows)

    def job_history(self, limit: int = 100) -> list[tuple]:
        with self._lock:
            conn = sqlite3.connect(self.path)
            try:
                return conn.execute(
                    "SELECT job_id, uploader_name, status, frames_processed, date, time FROM jobs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            finally:
                conn.close()
