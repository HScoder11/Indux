"""Indux backend - FastAPI + WebSocket.

Run from the Indux folder:
    python -m backend                  # http://localhost:8000  (docs at /docs)
    python -m backend --source replay --file demo_scenario.csv
    python -m backend --source serial --port COM5

Endpoints
    WS   /ws/live                 one message per window (~1.6/s): readings, health, alerts...
    GET  /api/status              source, connection status, last health/condition
    GET  /api/history?minutes=10  compact readings for graphs
    GET  /api/alerts              alert history (time, fault, action, resolved)
    POST /api/source              switch source: {"kind":"sim","rpm":5000} | {"kind":"replay","file":"x.csv"}
                                  | {"kind":"serial","port":"COM5"}
    GET  /api/sources             recordings and serial ports available
    POST /api/fault               simulator only: {"condition":"unbalance","severity":0.8}
    POST /api/report              {"lang":"en"|"hi"} -> AI maintenance report (saved to history)
    GET  /api/reports             previous reports (newest first)
    GET  /api/reports/{id}        one report with its full text
    GET  /api/reports/{id}/download?format=txt|md|html[&inline=1]
    GET  /api/readings/export?minutes=60   saved sensor readings as CSV (minutes=0 -> everything)
    GET  /api/readings/stats               how many readings are saved
    GET  /api/events                       black-box recordings saved around each alert
    GET  /api/events/{file}                download one
    GET  /api/notify/status                is email configured?
    POST /api/notify/test                  send a test email
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from backend import notify, report                                # noqa: E402
from backend.engine import Engine, readings_csv                   # noqa: E402
from backend.recorder import EVENT_DIR, list_events               # noqa: E402
from backend.sources import (ReplaySource, SerialSource, SimSource, SourceError,  # noqa: E402
                             list_recordings, list_serial_ports)
from simulator.motor_sim import CONDITIONS                        # noqa: E402

SPEED = float(os.getenv("INDUX_SPEED", "1.0"))   # >1 plays faster (tests only)


def make_source(kind: str, rpm: float = 5000, file: str | None = None, port: str | None = None,
                seed: int | None = None):
    if kind == "sim":
        return SimSource(rpm=rpm, seed=seed, speed=SPEED)
    if kind == "replay":
        if not file:
            raise SourceError("replay needs a file from data/sim/")
        return ReplaySource(file, speed=SPEED)
    if kind == "serial":
        if not port:
            raise SourceError("serial needs a port, e.g. COM5")
        return SerialSource(port)
    raise SourceError(f"unknown source kind {kind!r}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    kind = os.getenv("INDUX_SOURCE", "sim")
    try:
        src = make_source(kind, rpm=float(os.getenv("INDUX_RPM", "5000")),
                          file=os.getenv("INDUX_FILE"), port=os.getenv("INDUX_PORT"))
    except SourceError as e:
        print(f"[indux] could not start {kind} source ({e}); falling back to simulator")
        src = make_source("sim")
    engine = Engine(src)
    engine.start(asyncio.get_running_loop())
    app.state.engine = engine
    print(f"[indux] live on {src.name}")
    yield
    engine.stop()


app = FastAPI(title="Indux backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def E() -> Engine:
    return app.state.engine


# ------------------------------------------------------------------ REST
class SourceReq(BaseModel):
    kind: str = "sim"
    rpm: float = 5000
    file: str | None = None
    port: str | None = None
    seed: int | None = None


class FaultReq(BaseModel):
    condition: str
    severity: float | None = None


class ReportReq(BaseModel):
    lang: str = "en"


@app.get("/api/status")
def status():
    return E().status_dict()


@app.get("/api/history")
def history(minutes: float = 10, max_points: int = 600):
    since = time.time() - minutes * 60
    pts = [h for h in E().history if h["ts"] >= since]
    if not pts:                                    # e.g. after a restart: fall back to SQLite
        return E().store.readings(since, max_points)
    step = max(1, len(pts) // max_points)
    return pts[::step]


@app.get("/api/alerts")
def alerts(limit: int = 50):
    return E().store.alerts(limit)


@app.get("/api/sources")
def sources():
    return {"current": E().source.describe(), "recordings": list_recordings(),
            "serial_ports": list_serial_ports(), "conditions": list(CONDITIONS)}


@app.post("/api/source")
def set_source(req: SourceReq):
    try:
        src = make_source(req.kind, rpm=req.rpm, file=req.file, port=req.port, seed=req.seed)
    except SourceError as e:
        raise HTTPException(400, str(e))
    E().switch_source(src)
    return {"ok": True, "source": src.describe()}


@app.post("/api/fault")
def fault(req: FaultReq):
    try:
        return {"ok": True, "source": E().fault(req.condition, req.severity)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/report")
async def make_report(req: ReportReq):
    if E().last is None:
        raise HTTPException(409, "no data yet - wait a few seconds")
    return await asyncio.to_thread(report.generate, E(), req.lang)


@app.get("/api/reports")
def list_reports(limit: int = 50):
    return E().store.reports(limit)


def _get_report(report_id: int) -> dict:
    r = E().store.report(report_id)
    if r is None:
        raise HTTPException(404, f"report #{report_id} not found")
    return r


@app.get("/api/reports/{report_id}")
def get_report(report_id: int):
    return _get_report(report_id)


@app.get("/api/reports/{report_id}/download")
def download_report(report_id: int, format: str = "txt", inline: bool = False):
    r = _get_report(report_id)
    kinds = {"txt": (report.to_text, "text/plain"), "md": (report.to_markdown, "text/markdown"),
             "html": (report.to_html, "text/html")}
    if format not in kinds:
        raise HTTPException(400, "format must be txt, md or html")
    render, mime = kinds[format]
    disp = "inline" if inline else "attachment"
    return Response(render(r), media_type=f"{mime}; charset=utf-8",
                    headers={"Content-Disposition": f'{disp}; filename="{report.filename(r, format)}"'})


@app.get("/api/readings/stats")
def readings_stats():
    st = E().store.count_readings()
    st["raw_recording"] = E().raw.enabled
    return st


@app.get("/api/readings/export")
def export_readings(minutes: float = 60):
    since = 0 if minutes <= 0 else time.time() - minutes * 60
    rows = E().store.export_readings(since_ts=since)
    label = "all" if minutes <= 0 else f"last{int(minutes)}min"
    name = f"indux_readings_{label}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(readings_csv(rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/events")
def events():
    return list_events()


@app.get("/api/events/{name}")
def event_file(name: str):
    path = (EVENT_DIR / name).resolve()
    if path.parent != EVENT_DIR.resolve() or not path.exists() or path.suffix != ".csv":
        raise HTTPException(404, "event recording not found")
    return Response(path.read_bytes(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


@app.get("/api/notify/status")
def notify_status():
    st = notify.status()
    st["auto_report"] = E().auto_report
    return st


@app.post("/api/notify/test")
async def notify_test():
    try:
        await asyncio.to_thread(
            notify.send, subject=f"[Indux] Test email from {report.MACHINE}",
            text="Email alerts are working. You will get a message like this, with the AI report "
                 "attached, whenever Indux detects a fault or anomaly.")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"{type(e).__name__}: {e}")
    return {"ok": True, "to": notify.status()["to"]}


# ------------------------------------------------------------------ WebSocket
@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    engine = E()
    q = engine.subscribe()
    try:
        await ws.send_json({"type": "status", "status": engine.status, "error": engine.error,
                            "source": engine.source.describe()})
        while True:
            await ws.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        engine.unsubscribe(q)


# ------------------------------------------------------------------ static files
# Benchmark figures for the dashboard's Benchmarks tab
from fastapi.staticfiles import StaticFiles                       # noqa: E402

FIG_DIR = ROOT / "docs" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/figures", StaticFiles(directory=FIG_DIR), name="figures")

# After `npm run build` in dashboard/, the backend serves the whole dashboard at
# http://localhost:8000 - one command on demo day. Mounted last so /api and /ws win.
DIST = ROOT / "dashboard" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
else:
    @app.get("/")
    def root():
        return {"indux": "backend running", "docs": "/docs",
                "dashboard": "run `npm run dev` in dashboard/ (http://localhost:5173) "
                             "or `npm run build` to serve it here"}
