"""The live pipeline, running in one background thread:

    source.read()  ->  LivePredictor.update()  ->  alerts + SQLite  ->  every WebSocket client

A crash or unplugged sensor never kills the thread: the dashboard just sees
status "disconnected" and the engine keeps retrying.
"""
from __future__ import annotations

import asyncio
import threading
import time
import traceback
from collections import deque

import os

from ml.live import LivePredictor
from backend.sources import Source, SourceError, SimSource
from backend.store import Store
from backend.recorder import BlackBox, RawRecorder
from backend.notify import AlertMailer
from backend import report as report_mod

WAVE_POINTS = 256                 # downsampled waveform sent to the dashboard
HISTORY_MAX = 6000                # ~1 hour of windows kept in memory

ACTIONS = {
    "unbalance": "Stop at next break. Check rotor/disc for loose or missing weight; rebalance.",
    "looseness": "Check and tighten motor mounting bolts and bracket; inspect for cracks.",
    "bearing": "Plan bearing replacement; check lubrication. Avoid long runs until replaced.",
    "overload": "Reduce the load and check for rubbing or jamming; let the motor cool.",
    "anomaly": "Unusual behaviour not matching a known fault: inspect the machine and log it.",
}


class Engine:
    def __init__(self, source: Source, predictor: LivePredictor | None = None, store: Store | None = None):
        self.predictor = predictor or LivePredictor()
        self.store = store or Store()
        self.source = source
        self.status = "starting"
        self.error = None
        self.last = None
        self.history = deque(maxlen=HISTORY_MAX)
        self.windows = 0
        self._alert_id = None
        self._alert_cond = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._clients: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.blackbox = BlackBox()
        self.raw = RawRecorder()
        self.mailer = AlertMailer()
        self.auto_report = os.getenv("AUTO_REPORT", "1").strip().lower() not in ("0", "false", "no", "off")

    # ------------------------------------------------------------ lifecycle
    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread = threading.Thread(target=self._run, name="indux-engine", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        with self._lock:
            self.source.close()
        self.raw.close()
        self.store.close()

    def switch_source(self, new: Source):
        with self._lock:
            old, self.source = self.source, new
            self.predictor.reset()            # new machine/data -> learn its normal again
            self._close_alert(time.time())
            self.status, self.error = "starting", None
        old.close()

    # ------------------------------------------------------------ websockets
    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=20)
        self._clients.add(q)
        return q

    def unsubscribe(self, q):
        self._clients.discard(q)

    def _broadcast(self, msg):
        if not self._loop:
            return

        def push():
            for q in list(self._clients):
                if q.full():                  # slow client: drop its oldest message
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(msg)
        try:
            self._loop.call_soon_threadsafe(push)
        except RuntimeError:                  # event loop already closed (shutdown)
            pass

    # ------------------------------------------------------------ main loop
    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                source = self.source
            try:
                rec = source.read()
            except SourceError as e:
                self._set_status("disconnected", str(e))
                time.sleep(1.0)
                continue
            except Exception as e:  # noqa: BLE001
                self._set_status("error", f"{type(e).__name__}: {e}")
                traceback.print_exc()
                time.sleep(1.0)
                continue
            with self._lock:
                if source is not self.source:     # source switched while we were reading
                    continue
                try:
                    msg = self._process(rec)
                except Exception as e:  # noqa: BLE001
                    self._set_status("error", f"{type(e).__name__}: {e}")
                    traceback.print_exc()
                    continue
            self._broadcast({"type": "reading", **msg})

    def _set_status(self, status, error=None):
        changed = status != self.status or error != self.error
        self.status, self.error = status, error
        if changed:
            self._broadcast({"type": "status", "status": status, "error": error,
                             "source": self.source.describe()})

    def _process(self, rec: dict) -> dict:
        m = self.predictor.update(rec)
        self.blackbox.add(rec)
        self.raw.add(rec)
        vib = rec["vib"]
        step = max(1, len(vib) // WAVE_POINTS)
        m["wave"] = [round(float(v), 4) for v in vib[::step][:WAVE_POINTS]]
        m["status"] = "live"
        m["source_info"] = self.source.describe()
        self._track_alert(m)
        m["active_alert_id"] = self._alert_id
        self.status, self.error = "live", None
        self.last = m
        self.windows += 1
        self.history.append({k: m[k] for k in ("ts", "rpm", "current", "temp", "vib_rms",
                                                "health", "condition", "alert")})
        self.store.add_reading(m)
        return m

    def _track_alert(self, m):
        if m["alert"] and m["alert_condition"] != self._alert_cond:
            self._close_alert(m["ts"])
            action = ACTIONS.get(m["alert_condition"], ACTIONS["anomaly"])
            self._alert_id = self.store.open_alert(m, action)
            self._alert_cond = m["alert_condition"]
            self._on_new_alert(self._alert_id, m, action)
        elif not m["alert"] and self._alert_id is not None:
            self._close_alert(m["ts"])

    def _close_alert(self, ts):
        if self._alert_id is not None:
            self.store.close_alert(self._alert_id, ts)
        self._alert_id, self._alert_cond = None, None

    # ------------------------------------------------------------ alert automation
    def _on_new_alert(self, alert_id, m, action):
        """New fault or anomaly: save the black-box recording, write a report, email it."""
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(m["ts"]))
        name = f"alert_{alert_id}_{m['alert_condition']}_{stamp}.csv"
        self.blackbox.trigger(name, lambda path: self.store.update_alert(alert_id, event_file=f"events/{path.name}"))
        if self.auto_report:
            threading.Thread(target=self._alert_job, args=(alert_id, dict(m), action),
                             name="indux-alert", daemon=True).start()

    def _alert_job(self, alert_id, m, action):
        time.sleep(float(os.getenv("AUTO_REPORT_DELAY_S", "3")))    # let a few more readings arrive
        lang = os.getenv("ALERT_REPORT_LANG", "en")
        try:
            rep = report_mod.generate(self, lang)
        except Exception as e:  # noqa: BLE001
            self.store.update_alert(alert_id, email_status=f"report failed: {type(e).__name__}")
            return
        self.store.update_alert(alert_id, report_id=rep.get("id"))
        self._broadcast({"type": "alert_report", "alert_id": alert_id, "report_id": rep.get("id")})

        ok, why = self.mailer.should_send(m["alert_condition"])
        self.store.update_alert(alert_id, email_status=why)
        if not ok:
            return
        r = self.store.report(rep["id"]) if rep.get("id") else None
        subject = (f"[Indux ALERT] {m['alert_label']} on {report_mod.MACHINE} "
                   f"- health {0 if m.get('health') is None else round(m['health'])}/100")
        reasons = "\n".join(f"  - {x['label']}: {x['value']} (normal {x['normal']})" for x in m["reasons"])
        text = (f"Indux detected: {m['alert_label']} (confidence {m['confidence']:.0%})\n"
                f"Machine: {report_mod.MACHINE}\nTime: {time.strftime('%d %b %Y %H:%M:%S', time.localtime(m['ts']))}\n"
                f"Health score: {m.get('health')}\nSource: {m.get('source')}\n\nTop signals:\n{reasons}\n\n"
                f"Recommended action: {action}\n\n----- Report -----\n{rep['report']}\n")
        attachments = []
        if r:
            attachments.append((report_mod.filename(r, "html"), report_mod.to_html(r).encode("utf-8"), "text/html"))
        rows = self.store.export_readings(since_ts=m["ts"] - 180)
        if rows:
            attachments.append((f"readings_alert_{alert_id}.csv", readings_csv(rows).encode("utf-8"), "text/csv"))
        self.mailer.send_async(lambda st: self.store.update_alert(alert_id, email_status=st),
                               subject=subject, text=text,
                               html=report_mod.to_html(r) if r else None, attachments=attachments)

    # ------------------------------------------------------------ queries
    def status_dict(self) -> dict:
        last = self.last or {}
        return {
            "status": self.status, "error": self.error, "source": self.source.describe(),
            "windows": self.windows, "clients": len(self._clients),
            "calibrating": last.get("calibrating"), "health": last.get("health"),
            "condition": last.get("condition"), "alert": last.get("alert"),
        }

    def fault(self, condition, severity=None):
        with self._lock:
            if not isinstance(self.source, SimSource):
                raise ValueError("fault injection only works with the simulator source")
            self.source.set_condition(condition, severity)
            return self.source.describe()


def readings_csv(rows) -> str:
    """Saved readings -> CSV text with a readable local time column."""
    import csv
    import io
    cols = ["time", "ts", "source", "rpm", "current", "voltage", "temp", "vib_rms", "health",
            "condition", "confidence", "alert"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in rows:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
        w.writerow([t] + [r.get(c) for c in cols[1:]])
    return buf.getvalue()
