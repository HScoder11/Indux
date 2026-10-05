"""Raw sensor recording.

BlackBox        always on. Keeps the last ~30 s of full-resolution windows in memory.
                When an alert starts, it saves those 30 s plus the next ~15 s to
                data/events/alert_<id>_<fault>_<time>.csv - exactly what the sensor saw
                around the fault. The files replay in the dashboard like any recording.
RawRecorder     optional (RECORD_RAW=1 in .env). Saves EVERY window to hourly files in
                data/recordings/. About 60-100 MB per hour, so it is off by default;
                compact readings are always saved to SQLite either way.
Both write the same CSV format as the simulator's --record, so read_recording() reads them.
"""
from __future__ import annotations

import csv
import os
import threading
import time
from collections import deque
from pathlib import Path

from simulator.motor_sim import CSV_FIELDS, WINDOW_SEC

ROOT = Path(__file__).resolve().parent.parent
EVENT_DIR = ROOT / "data" / "events"
RAW_DIR = ROOT / "data" / "recordings"


def _row(rec: dict) -> list:
    return [rec.get("ts"), rec.get("source", "?"), rec.get("rpm"), rec.get("current"), rec.get("voltage"),
            rec.get("temp"), rec.get("fs"), "", "", " ".join(f"{float(v):.5f}" for v in rec["vib"])]


class BlackBox:
    def __init__(self, before_s: float = 30, after_s: float = 15):
        self.before = deque(maxlen=max(1, int(before_s / WINDOW_SEC)))
        self.after_n = max(1, int(after_s / WINDOW_SEC))
        self._pending: list[dict] = []          # events still collecting "after" windows
        self._lock = threading.Lock()

    def add(self, rec: dict):
        with self._lock:
            self.before.append(rec)
            done = []
            for ev in self._pending:
                ev["rows"].append(rec)
                ev["left"] -= 1
                if ev["left"] <= 0:
                    done.append(ev)
            for ev in done:
                self._pending.remove(ev)
        for ev in done:
            threading.Thread(target=self._write, args=(ev,), name="indux-blackbox", daemon=True).start()

    def trigger(self, name: str, on_saved=None):
        """Start an event file: everything in memory now + the next after_s seconds."""
        with self._lock:
            self._pending.append({"name": name, "rows": list(self.before), "left": self.after_n,
                                  "cb": on_saved})

    def _write(self, ev):
        EVENT_DIR.mkdir(parents=True, exist_ok=True)
        path = EVENT_DIR / ev["name"]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(CSV_FIELDS)
            for rec in ev["rows"]:
                w.writerow(_row(rec))
        if ev["cb"]:
            ev["cb"](path)


class RawRecorder:
    def __init__(self):
        self.enabled = os.getenv("RECORD_RAW", "0").strip().lower() in ("1", "true", "yes", "on")
        self._file = None
        self._writer = None
        self._hour = None

    def add(self, rec: dict):
        if not self.enabled:
            return
        hour = time.strftime("%Y-%m-%d_%H", time.localtime(rec.get("ts") or time.time()))
        if hour != self._hour:
            self.close()
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            path = RAW_DIR / f"{hour}h_{str(rec.get('source', 'src')).replace(':', '-')}.csv"
            new = not path.exists()
            self._file = open(path, "a", newline="")
            self._writer = csv.writer(self._file)
            if new:
                self._writer.writerow(CSV_FIELDS)
            self._hour = hour
        self._writer.writerow(_row(rec))
        self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
        self._file, self._writer, self._hour = None, None, None


def list_events() -> list[dict]:
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    return [{"file": p.name, "size_kb": round(p.stat().st_size / 1024), "ts": p.stat().st_mtime}
            for p in sorted(EVENT_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)]
