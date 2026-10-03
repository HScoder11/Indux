"""Backend smoke tests: python -m pytest tests/test_backend.py -q

Runs the real app with the simulator at 25x speed and a throwaway database.
"""
import os
import tempfile
import time

import pytest

os.environ["INDUX_SPEED"] = "25"
os.environ["INDUX_SOURCE"] = "sim"
os.environ["INDUX_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["AUTO_REPORT_DELAY_S"] = "0.2"
os.environ["RECORD_RAW"] = "0"
# Blank (not remove) keys so the real .env can't fill them in: tests must never call
# a paid API or send real emails.
for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "SMTP_HOST", "SMTP_USER",
          "SMTP_PASSWORD", "ALERT_EMAIL_TO", "ALERT_EMAIL_FROM"):
    os.environ[k] = ""

from fastapi.testclient import TestClient          # noqa: E402

from backend.app import app                        # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def readings(ws, n):
    out = []
    while len(out) < n:
        m = ws.receive_json()
        if m["type"] == "reading":
            out.append(m)
    return out


def test_stream_and_calibration(client):
    with client.websocket_connect("/ws/live") as ws:
        first = ws.receive_json()
        assert first["type"] == "status"
        msgs = readings(ws, 60)
    assert msgs[0]["calibrating"] is True
    assert msgs[-1]["calibrating"] is False and msgs[-1]["health"] > 80
    m = msgs[-1]
    for key in ("health", "zone", "condition", "confidence", "reasons", "fft", "wave", "alert", "ttf_s"):
        assert key in m
    assert len(m["fft"]["amp"]) == 160 and len(m["wave"]) == 256


def test_fault_injection_raises_alert(client):
    with client.websocket_connect("/ws/live") as ws:
        readings(ws, 5)
        r = client.post("/api/fault", json={"condition": "unbalance", "severity": 0.8})
        assert r.status_code == 200
        msgs = readings(ws, 12)
    assert any(m["alert"] and m["alert_condition"] == "unbalance" for m in msgs)
    alerts = client.get("/api/alerts").json()
    assert alerts and alerts[0]["condition"] == "unbalance" and alerts[0]["action"]
    client.post("/api/fault", json={"condition": "healthy"})


def test_report_offline_en_and_hi(client):
    en = client.post("/api/report", json={"lang": "en"}).json()
    assert en["engine"] == "template" and "What is wrong" in en["report"]
    hi = client.post("/api/report", json={"lang": "hi"}).json()
    assert "क्या गलत है" in hi["report"]


def test_history_and_status(client):
    assert client.get("/api/history?minutes=5").json()
    s = client.get("/api/status").json()
    assert s["status"] == "live" and s["source"]["kind"] == "sim"


def test_bad_inputs(client):
    assert client.post("/api/fault", json={"condition": "banana"}).status_code == 400
    assert client.post("/api/source", json={"kind": "replay", "file": "nope.csv"}).status_code == 400
    r = client.post("/api/source", json={"kind": "serial", "port": "COM_DOES_NOT_EXIST"})
    assert r.status_code == 400
    assert client.get("/api/status").json()["status"] == "live"      # still running


def test_replay_source(client, tmp_path):
    from backend.make_demo_recording import OUT, records
    from simulator.motor_sim import write_recording
    import itertools
    name = "pytest_replay.csv"
    write_recording(OUT.parent / name, itertools.islice(records(), 30))
    try:
        assert client.post("/api/source", json={"kind": "replay", "file": name}).status_code == 200
        assert client.post("/api/fault", json={"condition": "unbalance"}).status_code == 400
        with client.websocket_connect("/ws/live") as ws:
            msgs = readings(ws, 5)
        assert all(m["source"].startswith("replay:") for m in msgs)
    finally:
        client.post("/api/source", json={"kind": "sim"})
        (OUT.parent / name).unlink(missing_ok=True)


def test_report_history_and_downloads(client):
    r = client.post("/api/report", json={"lang": "hi"}).json()
    rid = r["id"]
    assert rid
    listed = client.get("/api/reports").json()
    assert any(x["id"] == rid for x in listed)
    full = client.get(f"/api/reports/{rid}").json()
    assert full["text"] == r["report"] and full["lang"] == "hi"
    for fmt, ctype in (("txt", "text/plain"), ("md", "text/markdown"), ("html", "text/html")):
        d = client.get(f"/api/reports/{rid}/download?format={fmt}")
        assert d.status_code == 200 and d.headers["content-type"].startswith(ctype)
        assert f"indux_report_{rid}_" in d.headers["content-disposition"]
        assert "क्या गलत है" in d.text
    assert client.get(f"/api/reports/{rid}/download?format=exe").status_code == 400
    assert client.get("/api/reports/999999").status_code == 404


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def has_extn(self, name):
        return True

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        assert password == "app-pass"

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def _wait(pred, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.2)
    return None


def test_alert_auto_report_email_and_blackbox(client, monkeypatch):
    from backend import notify
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "team@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass")
    monkeypatch.setenv("ALERT_EMAIL_TO", "a@example.com, b@example.com")
    st = client.get("/api/notify/status").json()
    assert st["configured"] and st["to"] == ["a***@example.com", "b***@example.com"]

    assert client.post("/api/notify/test").status_code == 200
    assert "Test email" in FakeSMTP.sent[-1]["Subject"]

    client.post("/api/fault", json={"condition": "looseness", "severity": 0.9})
    alert = _wait(lambda: next((a for a in client.get("/api/alerts").json()
                                if a["condition"] == "looseness" and (a.get("email_status") or "").startswith("sent")), None))
    assert alert, client.get("/api/alerts").json()[:2]
    assert alert["report_id"]                                      # report written automatically
    mail = FakeSMTP.sent[-1]
    assert "Looseness" in mail["Subject"] and "a@example.com" in mail["To"]
    names = [p.get_filename() for p in mail.iter_attachments()]
    assert any(n.endswith(".html") for n in names) and any(n.endswith(".csv") for n in names)

    # black box: ~45 s of raw windows around the alert, replayable
    ev = _wait(lambda: next((a for a in client.get("/api/alerts").json()
                             if a["id"] == alert["id"] and a.get("event_file")), None))
    assert ev
    assert client.get(f"/api/{ev['event_file']}").status_code == 200
    files = [r["file"] for r in client.get("/api/sources").json()["recordings"]]
    assert ev["event_file"] in files
    client.post("/api/fault", json={"condition": "healthy"})


def test_readings_saved_and_exported(client):
    st = client.get("/api/readings/stats").json()
    assert st["count"] > 50
    csv_text = client.get("/api/readings/export?minutes=0").text
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("time,ts,source,rpm,current,voltage,temp,vib_rms,health")
    assert len(lines) - 1 == client.get("/api/readings/stats").json()["count"] or len(lines) > 50
