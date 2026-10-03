"""SQLite history: every reading (compact) and every alert. No setup needed."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("INDUX_DB", ROOT / "data" / "indux.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    ts REAL, source TEXT, rpm REAL, current REAL, temp REAL, vib_rms REAL,
    health REAL, condition TEXT, confidence REAL, alert INTEGER
);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, source TEXT, condition TEXT, label TEXT, health REAL,
    confidence REAL, reasons TEXT, action TEXT, resolved_ts REAL
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, lang TEXT, engine TEXT, model TEXT, source TEXT,
    condition TEXT, health REAL, alert INTEGER, text TEXT, summary TEXT
);
"""


class Store:
    def __init__(self, path=DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(SCHEMA)
            # upgrade databases made by older versions (adding a column twice just fails)
            for sql in ("ALTER TABLE readings ADD COLUMN voltage REAL",
                        "ALTER TABLE alerts ADD COLUMN report_id INTEGER",
                        "ALTER TABLE alerts ADD COLUMN email_status TEXT",
                        "ALTER TABLE alerts ADD COLUMN event_file TEXT"):
                try:
                    self.db.execute(sql)
                except sqlite3.OperationalError:
                    pass
            self.db.commit()
        self._pending = 0

    def add_reading(self, m: dict):
        with self.lock:
            self.db.execute(
                "INSERT INTO readings (ts, source, rpm, current, voltage, temp, vib_rms, health,"
                " condition, confidence, alert) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (m["ts"], m["source"], m["rpm"], m.get("current"), m.get("voltage"), m.get("temp"),
                 m["vib_rms"], m.get("health"), m["condition"], m["confidence"], int(m["alert"])))
            self._pending += 1
            if self._pending >= 20:          # commit in small batches
                self.db.commit()
                self._pending = 0

    def open_alert(self, m: dict, action: str) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO alerts (ts, source, condition, label, health, confidence, reasons, action)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (m["ts"], m["source"], m["alert_condition"], m["alert_label"], m.get("health"),
                 m["confidence"], json.dumps(m["reasons"]), action))
            self.db.commit()
            return cur.lastrowid

    def close_alert(self, alert_id: int, ts: float):
        with self.lock:
            self.db.execute("UPDATE alerts SET resolved_ts=? WHERE id=?", (ts, alert_id))
            self.db.commit()

    def alerts(self, limit=50) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"] or "[]")
            out.append(d)
        return out

    def update_alert(self, alert_id: int, **fields):
        allowed = {"report_id", "email_status", "event_file"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        with self.lock:
            self.db.execute(f"UPDATE alerts SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                            (*sets.values(), alert_id))
            self.db.commit()

    def export_readings(self, since_ts: float = 0, until_ts: float | None = None):
        """All saved sensor readings in a time range, oldest first (for CSV download)."""
        until_ts = until_ts or 1e12
        with self.lock:
            self.db.commit()
            rows = self.db.execute(
                "SELECT ts, source, rpm, current, voltage, temp, vib_rms, health, condition, confidence, alert"
                " FROM readings WHERE ts >= ? AND ts <= ? ORDER BY ts", (since_ts, until_ts)).fetchall()
        return [dict(r) for r in rows]

    def count_readings(self) -> dict:
        with self.lock:
            n, first, last = self.db.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM readings").fetchone()
        return {"count": n, "first_ts": first, "last_ts": last}

    # ---------------- reports ----------------
    def save_report(self, r: dict) -> int:
        s = r.get("summary", {})
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO reports (ts, lang, engine, model, source, condition, health, alert, text, summary)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (r["generated_at"], r["lang"], r["engine"], r.get("model"), s.get("data_source"),
                 s.get("current_condition"), s.get("health_score_now"), int(bool(s.get("alert_active"))),
                 r["report"], json.dumps(s, ensure_ascii=False)))
            self.db.commit()
            return cur.lastrowid

    def reports(self, limit=50) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT id, ts, lang, engine, model, source, condition, health, alert"
                " FROM reports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def report(self, report_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["summary"] = json.loads(d["summary"] or "{}")
        return d

    def readings(self, since_ts: float, max_points=600) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT ts, rpm, current, temp, vib_rms, health, condition, alert"
                " FROM readings WHERE ts >= ? ORDER BY ts", (since_ts,)).fetchall()
        step = max(1, len(rows) // max_points)
        return [dict(r) for r in rows[::step]]

    def close(self):
        with self.lock:
            self.db.commit()
            self.db.close()
