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


def test_report_formatting_keys_on_live_dict(client):
    from backend import report as report_mod
    r = client.post("/api/report", json={"lang": "en"}).json()
    assert "report" in r and "text" in r
    assert "generated_at" in r and "ts" in r
    # Direct calls to renderers must not raise KeyError: 'text' or 'ts'
    html = report_mod.to_html(r)
    text = report_mod.to_text(r)
    md = report_mod.to_markdown(r)
    assert "Maintenance report" in html
    assert "INDUX MAINTENANCE REPORT" in text
    assert "# Indux maintenance report" in md


def test_mailer_cooldown_not_locked_on_failure(monkeypatch):
    from backend import notify
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "team@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-pass")
    monkeypatch.setenv("ALERT_EMAIL_TO", "a@example.com")

    def fail_send(*a, **kw):
        raise ConnectionError("SMTP down")

    monkeypatch.setattr(notify, "send", fail_send)
    mailer = notify.AlertMailer()
    ok, _ = mailer.should_send("unbalance")
    assert ok is True

    done_msg = []
    mailer.send_async(lambda st: done_msg.append(st), condition="unbalance", subject="test", text="test")
    time.sleep(0.3)
    assert any("failed" in m for m in done_msg)
    # Crucial test: failed send MUST NOT lock the cooldown!
    ok2, _ = mailer.should_send("unbalance")
    assert ok2 is True


def test_live_predictor_edge_cases():
    from ml.live import LivePredictor
    p = LivePredictor()
    # 1. Zero RPM shouldn't divide by zero
    p.base = (dict.fromkeys(p.z_features, 0.05), dict.fromkeys(p.z_features, 0.01), 0.0)
    fake_rec = {"rpm": 0.0, "fs": 3200, "vib": [0.0] * 2048, "ts": time.time()}
    res = p.update(fake_rec)
    assert res is not None

    # 2. Degenerate timestamps for TTF shouldn't raise LinAlgError
    p.trend.clear()
    for _ in range(35):
        p.trend.append((100.0, 70.0))  # identical timestamp
    assert p._ttf() is None

    # 3. Calibration guard: known fault with high confidence is not learned into normal baseline
    p.reset()
    assert len(p.calib) == 0


def test_store_prune():
    from backend.store import Store
    import tempfile
    s = Store(os.path.join(tempfile.mkdtemp(), "prune.db"), retention_days=1)
    old_ts = time.time() - 200000  # >2 days old
    s.add_reading({"ts": old_ts, "source": "sim", "rpm": 5000, "vib_rms": 0.05,
                   "condition": "healthy", "confidence": 1.0, "alert": 0})
    s.add_reading({"ts": time.time(), "source": "sim", "rpm": 5000, "vib_rms": 0.05,
                   "condition": "healthy", "confidence": 1.0, "alert": 0})
    s.db.commit()
    assert s.count_readings()["count"] == 2
    s.prune_old_readings(days=1)
    assert s.count_readings()["count"] == 1


def test_gmail_notification_config_and_html(monkeypatch, tmp_path):
    from backend import notify
    fake_env = tmp_path / ".env"
    monkeypatch.setattr(notify, "ROOT", tmp_path)

    # 1. Test space stripping and Gmail auto-detection
    st = notify.configure(
        user="test.engineer@gmail.com",
        password="abcd efgh ijkl mnop",
        to="ops@plant.com, alerts@plant.com",
        save_env=True,
    )
    assert st["configured"] is True
    assert st["provider"] == "gmail"
    assert st["host"] == "smtp.gmail.com"
    assert st["port"] == 587
    assert len(st["to"]) == 2
    assert "te***@gmail.com" in st["user"]

    # Verify password was stripped in internal config
    cfg = notify._cfg()
    assert cfg["password"] == "abcdefghijklmnop"

    # Verify persisted to .env
    env_content = fake_env.read_text(encoding="utf-8")
    assert "SMTP_USER=test.engineer@gmail.com" in env_content
    assert "SMTP_PASSWORD=abcdefghijklmnop" in env_content

    # 2. Test HTML builder for verification
    test_html = notify.build_test_html("test.engineer@gmail.com", ["ops@plant.com"])
    assert "GMAIL ALERTS VERIFIED" in test_html
    assert "test.engineer@gmail.com" in test_html

    # 3. Test HTML builder for machine alerts
    alert_html = notify.build_alert_html(
        m={
            "alert_label": "Unbalance Fault",
            "health": 35,
            "confidence": 0.95,
            "ts": time.time(),
            "source": "sim",
            "rpm": 5000,
            "vib_rms": 0.32,
            "reasons": [{"feature": "1x", "label": "1x Rotor Speed", "value": "0.30g", "normal": "0.05g", "z": 5.2}],
        },
        action="Check rotor for loose weights.",
        report_text="Diagnostic findings...",
    )
    assert "[ALERT] Unbalance Fault" in alert_html
    assert "35 / 100" in alert_html
    assert "Check rotor for loose weights." in alert_html
    assert "1x Rotor Speed" in alert_html


def test_notify_endpoints(client, monkeypatch):
    from backend import notify

    # Mock test_connection and send so no actual network call is made
    called_test = []
    called_send = []

    def mock_test_connection():
        called_test.append(True)

    def mock_send(*args, **kwargs):
        called_send.append(kwargs)

    monkeypatch.setattr(notify, "test_connection", mock_test_connection)
    monkeypatch.setattr(notify, "send", mock_send)

    # 1. Validation error on missing fields
    bad_res = client.post("/api/notify/config", json={
        "user": "", "password": "", "to": "", "provider": "gmail", "test_now": False
    })
    assert bad_res.status_code == 400

    # 2. Configure with valid Gmail credentials and test_now=True
    res = client.post("/api/notify/config", json={
        "user": "maintenance@gmail.com",
        "password": "wxyz 1234 5678 abcd",
        "to": "supervisor@plant.com",
        "provider": "gmail",
        "test_now": True,
        "save_env": False,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["configured"] is True
    assert data["provider"] == "gmail"
    assert len(called_test) == 1
    assert len(called_send) == 1
    assert "supervisor@plant.com" in str(called_send[0]["html"])

    # 3. GET /api/notify/status
    st_res = client.get("/api/notify/status")
    assert st_res.status_code == 200
    st_data = st_res.json()
    assert st_data["configured"] is True
    assert "ma***@gmail.com" in st_data["user"]

    # 4. POST /api/notify/test
    test_res = client.post("/api/notify/test")
    assert test_res.status_code == 200
    assert test_res.json()["ok"] is True
    assert len(called_send) == 2


def _replay(tmp_path, name, per_reading):
    """Feed recorded per-reading labels through the predictor's 3-of-5 alert rule and the engine's
    alert tracker; return the alerts it opened (oldest first)."""
    from collections import Counter, deque

    from backend.engine import CLEAR_READINGS, Engine
    from backend.store import Store
    from ml.live import ALERT_NEED, ALERT_OF

    eng = Engine(source=None, predictor=object(), store=Store(tmp_path / name))
    eng.auto_report = False
    eng.blackbox.trigger = lambda *a, **k: None
    recent = deque(maxlen=ALERT_OF)
    for i, cond in enumerate(per_reading + ["healthy"] * (ALERT_OF + CLEAR_READINGS)):
        recent.append(cond)
        abnormal = [c for c in recent if c != "healthy"]
        alert = len(abnormal) >= ALERT_NEED
        ac = Counter(abnormal).most_common(1)[0][0] if alert else None
        eng._track_alert({"ts": 1000.0 + i * 0.64, "source": "sim", "alert": alert, "alert_condition": ac,
                          "alert_label": ac, "health": 30.0, "confidence": 0.9, "reasons": []})
    return list(reversed(eng.store.alerts(50)))


def test_overload_recovery_is_one_alert(tmp_path):
    """4 Oct 21:25: overload, then back to healthy. Current/speed recover at once but the motor is
    still hot and health recovers slowly, so the classifier says anomaly / unbalance for a few
    seconds. That must stay ONE overload alert (it made 4 alerts before)."""
    o, u, a, h = "overload", "unbalance", "anomaly", "healthy"
    seq = [o] * 20 + [u, u, h, a, h, a, h, a, u, h, h, h, u, h, h, h, h, u, h, h, h, h, h, u,
                      h, h, h, h, h, h, h, h, u, h, h, h, u, h, h, h, u, h, u, h, h]
    alerts = _replay(tmp_path, "rec.db", seq)
    assert [x["condition"] for x in alerts] == ["overload"]
    assert alerts[0]["resolved_ts"]


def test_one_continuous_fault_is_one_alert(tmp_path):
    """4 Oct 21:14: the label flipped unbalance <-> anomaly during one fault and flickered as it
    cleared, opening 12 alerts in 2 minutes. Now: no alert per flicker."""
    o, u, a, h = "overload", "unbalance", "anomaly", "healthy"
    seq = ([o] * 5 + [u, u] + [a] * 5 + [u] + [a] * 8 + [u, a, u] + [a] * 8
           + [u, a, u, u, a, a, u, a, u, h, h, a, h, h, h, u, h, a, u, h, h, u, h, u, u, u])
    alerts = _replay(tmp_path, "flip.db", seq)
    assert len(alerts) <= 2
    assert all(x["resolved_ts"] for x in alerts)


def test_anomaly_upgraded_to_known_fault_in_place(tmp_path):
    from backend.engine import Engine
    from backend.store import Store

    eng = Engine(source=None, predictor=object(), store=Store(tmp_path / "b.db"))
    eng.auto_report = False
    eng.blackbox.trigger = lambda *a, **k: None
    for i, cond in enumerate(["anomaly", "anomaly", "bearing", "anomaly", "bearing"]):
        eng._track_alert({"ts": 1000.0 + i, "source": "sim", "alert": True, "alert_condition": cond,
                          "alert_label": cond.title(), "health": 20.0, "confidence": 0.8, "reasons": []})
    alerts = eng.store.alerts(10)
    assert len(alerts) == 1 and alerts[0]["condition"] == "bearing" and alerts[0]["label"] == "Bearing"
