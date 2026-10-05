"""Email alerts over SMTP (Gmail, Outlook, college mail...). Settings come from .env:

    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=yourteam@gmail.com
    SMTP_PASSWORD=xxxx xxxx xxxx xxxx     # Gmail: an "App password", not your normal password
    ALERT_EMAIL_TO=a@x.com, b@y.com       # one or more, comma separated
    ALERT_EMAIL_FROM=Indux <yourteam@gmail.com>   # optional, defaults to SMTP_USER
    ALERT_EMAIL_COOLDOWN_MIN=10           # optional: same fault is emailed at most once per 10 min

Sending happens in a background thread, so a slow mail server never pauses the live data.
"""
from __future__ import annotations

import html
import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_runtime_cfg: dict = {}


def _cfg():
    user = _runtime_cfg.get("user") or os.getenv("SMTP_USER") or os.getenv("GMAIL_USER") or ""
    raw_pass = _runtime_cfg.get("password") or os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD") or ""
    password = raw_pass.replace(" ", "")  # 16-character Google App Passwords often have spaces: "abcd efgh ijkl mnop"

    to_str = _runtime_cfg.get("to") or os.getenv("ALERT_EMAIL_TO") or ""
    to = [a.strip() for a in to_str.replace(";", ",").split(",") if a.strip()]

    is_gmail = "gmail" in user.lower() or _runtime_cfg.get("provider") == "gmail"
    host = _runtime_cfg.get("host") or os.getenv("SMTP_HOST") or ("smtp.gmail.com" if is_gmail else "")
    port = int(_runtime_cfg.get("port") or os.getenv("SMTP_PORT") or (587 if is_gmail else 587))

    from_addr = _runtime_cfg.get("from") or os.getenv("ALERT_EMAIL_FROM") or (f"Indux Alerts <{user}>" if user else "")
    cooldown = float(_runtime_cfg.get("cooldown") or os.getenv("ALERT_EMAIL_COOLDOWN_MIN") or 10) * 60
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "to": to,
        "from": from_addr,
        "cooldown": cooldown,
        "is_gmail": is_gmail,
    }


def _mask(addr: str) -> str:
    name, _, domain = addr.partition("@")
    return (name[:2] + "***@" + domain) if domain else "***"


def status() -> dict:
    c = _cfg()
    ok = bool(c["host"] and c["to"] and c["from"] and c["password"])
    provider = "gmail" if ("gmail" in (c["host"] or "").lower() or "gmail" in (c["user"] or "").lower()) else "smtp"
    return {
        "configured": ok,
        "provider": provider,
        "user": _mask(c["user"]) if c["user"] else None,
        "to": [_mask(a) for a in c["to"]],
        "recipients": c["to"],
        "host": c["host"] or None,
        "port": c["port"],
        "cooldown_min": round(c["cooldown"] / 60, 1),
        "missing": [k for k, v in (("host", c["host"]), ("recipients", c["to"]),
                                   ("user", c["from"]), ("password", c["password"])) if not v]
    }


def _save_to_env(updates: dict[str, str], env_path: Path | None = None):
    if env_path is None:
        env_path = ROOT / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    keys_updated = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#") and "=" in line:
            key, _, _ = line.partition("=")
            key = key.strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                keys_updated.add(key)
                continue
        new_lines.append(line)
    for key, val in updates.items():
        if key not in keys_updated:
            new_lines.append(f"{key}={val}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def configure(user: str, password: str, to: str, host: str | None = None, port: int | None = None,
              save_env: bool = True) -> dict:
    """Update email settings live in memory, and optionally save to .env."""
    user = user.strip()
    password = password.strip().replace(" ", "")
    to_clean = ", ".join(a.strip() for a in to.replace(";", ",").split(",") if a.strip())
    is_gmail = "gmail" in user.lower() or "gmail" in (host or "").lower()
    final_host = host or ("smtp.gmail.com" if is_gmail else "smtp.gmail.com")
    final_port = int(port or 587)

    global _runtime_cfg
    _runtime_cfg = {
        "user": user,
        "password": password,
        "to": to_clean,
        "host": final_host,
        "port": final_port,
        "from": f"Indux Alerts <{user}>",
        "provider": "gmail" if is_gmail else "smtp",
    }
    if save_env:
        _save_to_env({
            "SMTP_HOST": final_host,
            "SMTP_PORT": str(final_port),
            "SMTP_USER": user,
            "SMTP_PASSWORD": password,
            "ALERT_EMAIL_TO": to_clean,
            "ALERT_EMAIL_FROM": f"Indux Alerts <{user}>",
        })
    return status()


def test_connection():
    """Verify SMTP credentials with the mail server."""
    c = _cfg()
    if not (c["host"] and c["user"] and c["password"]):
        raise RuntimeError("Missing host, sender user, or password. Please provide all required fields.")
    ctx = ssl.create_default_context()
    try:
        if c["port"] == 465:
            with smtplib.SMTP_SSL(c["host"], c["port"], context=ctx, timeout=15) as s:
                s.login(c["user"], c["password"])
        else:
            with smtplib.SMTP(c["host"], c["port"], timeout=15) as s:
                s.ehlo()
                if s.has_extn("starttls"):
                    s.starttls(context=ctx)
                    s.ehlo()
                s.login(c["user"], c["password"])
    except smtplib.SMTPAuthenticationError as e:
        if "gmail" in c["host"].lower():
            raise RuntimeError(
                "Gmail authentication rejected. For Gmail, you must generate a 16-character 'App Password' "
                "(Google Account -> Security -> 2-Step Verification -> App passwords). Normal account passwords do not work."
            ) from e
        raise RuntimeError(f"Authentication failed: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Could not connect to {c['host']}:{c['port']}: {e}") from e


def build_test_html(sender: str, recipients: list[str]) -> str:
    rec_str = ", ".join(recipients)
    return f"""<!doctype html>
<html>
<body style="margin:0;padding:24px;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);">
    <div style="background:#0f172a;color:#ffffff;padding:24px;border-bottom:3px solid #22c55e;">
      <h2 style="margin:0;font-size:20px;font-weight:700;">Indux Predictive Maintenance</h2>
      <p style="margin:6px 0 0;font-size:13px;color:#94a3b8;">Real-Time Condition Monitoring & Alerts</p>
    </div>
    <div style="padding:24px;">
      <div style="display:inline-block;padding:5px 12px;background:#dcfce7;color:#15803d;font-size:12px;font-weight:700;border-radius:20px;margin-bottom:16px;">
        ✓ GMAIL ALERTS VERIFIED
      </div>
      <p style="margin:0 0 16px;font-size:15px;line-height:1.5;">
        Your Gmail notification channel has been verified successfully.
      </p>
      <div style="background:#f1f5f9;border-left:4px solid #3b82f6;padding:12px 16px;margin:16px 0;font-size:13px;line-height:1.6;">
        <strong>Sender:</strong> {html.escape(sender)}<br>
        <strong>Recipients:</strong> {html.escape(rec_str)}<br>
        <strong>Status:</strong> Active & Ready
      </div>
      <p style="margin:16px 0 0;font-size:14px;color:#475569;line-height:1.5;">
        Whenever Indux detects an unbalance, looseness, bearing fault, overload, or abnormal condition on the motor, an immediate alert email with the diagnostic report and sensor telemetry will be dispatched to this inbox.
      </p>
    </div>
    <div style="background:#f8fafc;padding:14px 24px;border-top:1px solid #e2e8f0;font-size:12px;color:#94a3b8;text-align:center;">
      Sent automatically by Indux Predictive Maintenance
    </div>
  </div>
</body>
</html>"""


def build_alert_html(m: dict, action: str, report_text: str) -> str:
    cond = m.get("alert_label") or m.get("alert_condition") or "Fault"
    health = m.get("health")
    h_str = f"{round(health)} / 100" if health is not None else "Calibrating"
    h_color = "#ef4444" if (health is not None and health < 50) else "#f59e0b" if (health is not None and health < 80) else "#22c55e"
    conf_pct = f"{round(m.get('confidence', 1.0) * 100)}%"
    ts_str = time.strftime('%d %b %Y, %H:%M:%S', time.localtime(m.get("ts", time.time())))

    reasons_html = "".join(
        f"<tr><td style='padding:6px 10px;border-bottom:1px solid #f1f5f9;'>{html.escape(r['label'])}</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #f1f5f9;font-weight:600;'>{r['value']} (normal {r['normal']})</td>"
        f"<td style='padding:6px 10px;border-bottom:1px solid #f1f5f9;color:#dc2626;'>{r['z']}x spread</td></tr>"
        for r in m.get("reasons", [])
    ) or "<tr><td colspan='3' style='padding:8px;color:#64748b;'>No individual outliers recorded.</td></tr>"

    return f"""<!doctype html>
<html>
<body style="margin:0;padding:24px;background:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
  <div style="max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;overflow:hidden;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);">
    <div style="background:#0f172a;color:#ffffff;padding:22px 24px;border-bottom:4px solid {h_color};">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
          <h2 style="margin:0;font-size:20px;font-weight:700;">[ALERT] {html.escape(cond)}</h2>
          <p style="margin:4px 0 0;font-size:13px;color:#94a3b8;">Indux Predictive Maintenance · {html.escape(ts_str)}</p>
        </div>
      </div>
    </div>
    <div style="padding:24px;">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px;">
        <div style="background:#f8fafc;padding:12px;border-radius:8px;border:1px solid #e2e8f0;">
          <div style="font-size:12px;color:#64748b;font-weight:600;">HEALTH SCORE</div>
          <div style="font-size:24px;font-weight:800;color:{h_color};">{h_str}</div>
        </div>
        <div style="background:#f8fafc;padding:12px;border-radius:8px;border:1px solid #e2e8f0;">
          <div style="font-size:12px;color:#64748b;font-weight:600;">CONFIDENCE</div>
          <div style="font-size:24px;font-weight:800;color:#0f172a;">{conf_pct}</div>
        </div>
      </div>

      <div style="background:#fffbeb;border:1px solid #fde68a;border-left:4px solid #f59e0b;padding:14px;border-radius:8px;margin-bottom:20px;">
        <div style="font-size:12px;color:#92400e;font-weight:700;margin-bottom:4px;">RECOMMENDED ACTION</div>
        <div style="font-size:14px;color:#78350f;font-weight:500;">{html.escape(action)}</div>
      </div>

      <div style="margin-bottom:20px;">
        <div style="font-size:13px;font-weight:700;color:#334155;margin-bottom:8px;">KEY ANOMALY SIGNALS</div>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead>
            <tr style="background:#f8fafc;color:#64748b;text-align:left;">
              <th style="padding:6px 10px;">Signal</th><th style="padding:6px 10px;">Value</th><th style="padding:6px 10px;">Deviation</th>
            </tr>
          </thead>
          <tbody>{reasons_html}</tbody>
        </table>
      </div>

      <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;font-size:13px;color:#475569;">
        <strong>Machine:</strong> {html.escape(m.get('source', 'Motor'))} &bull; 
        <strong>Speed:</strong> {m.get('rpm', '-')} RPM &bull; 
        <strong>Vibration RMS:</strong> {m.get('vib_rms', '-')} g
      </div>
    </div>
    <div style="background:#f8fafc;padding:12px 24px;border-top:1px solid #e2e8f0;font-size:12px;color:#94a3b8;text-align:center;">
      Detailed maintenance report and recent sensor CSV data are attached to this email.
    </div>
  </div>
</body>
</html>"""


def send(subject: str, text: str, html: str | None = None, attachments=()) -> None:
    """Send now (blocking). attachments: [(filename, bytes, mime 'type/subtype')]. Raises on failure."""
    c = _cfg()
    if not (c["host"] and c["to"] and c["from"]):
        raise RuntimeError("email not configured (SMTP_HOST / ALERT_EMAIL_TO / SMTP_USER in .env)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = c["from"]
    msg["To"] = ", ".join(c["to"])
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)

    ctx = ssl.create_default_context()
    if c["port"] == 465:
        with smtplib.SMTP_SSL(c["host"], c["port"], context=ctx, timeout=20) as s:
            if c["user"] and c["password"]:
                s.login(c["user"], c["password"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(c["host"], c["port"], timeout=20) as s:
            s.ehlo()
            if s.has_extn("starttls"):
                s.starttls(context=ctx)
                s.ehlo()
            if c["user"] and c["password"]:
                s.login(c["user"], c["password"])
            s.send_message(msg)


class AlertMailer:
    """Decides WHEN to email (cooldown per fault) and sends in the background."""

    def __init__(self):
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_send(self, condition: str) -> tuple[bool, str]:
        st = status()
        if not st["configured"]:
            return False, "email not configured"
        with self._lock:
            last = self._last_sent.get(condition, 0)
            if time.time() - last < _cfg()["cooldown"]:
                return False, f"skipped (same fault emailed {int((time.time() - last) / 60)} min ago)"
        return True, "sending"

    def send_async(self, on_done, condition: str | None = None, **kwargs):
        def run():
            try:
                send(**kwargs)
                if condition:
                    with self._lock:
                        self._last_sent[condition] = time.time()
                on_done(f"sent {time.strftime('%H:%M:%S')}")
            except Exception as e:  # noqa: BLE001
                on_done(f"failed: {type(e).__name__}: {str(e)[:120]}")
        threading.Thread(target=run, name="indux-mail", daemon=True).start()
