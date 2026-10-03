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

import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage


def _cfg():
    to = [a.strip() for a in os.getenv("ALERT_EMAIL_TO", "").replace(";", ",").split(",") if a.strip()]
    user = os.getenv("SMTP_USER", "")
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "587") or 587),
        "user": user,
        "password": os.getenv("SMTP_PASSWORD", ""),
        "to": to,
        "from": os.getenv("ALERT_EMAIL_FROM", "") or user,
        "cooldown": float(os.getenv("ALERT_EMAIL_COOLDOWN_MIN", "10") or 10) * 60,
    }


def _mask(addr: str) -> str:
    name, _, domain = addr.partition("@")
    return (name[:2] + "***@" + domain) if domain else "***"


def status() -> dict:
    c = _cfg()
    ok = bool(c["host"] and c["to"] and c["from"])
    return {"configured": ok, "to": [_mask(a) for a in c["to"]], "host": c["host"] or None,
            "cooldown_min": round(c["cooldown"] / 60, 1),
            "missing": [k for k, v in (("SMTP_HOST", c["host"]), ("ALERT_EMAIL_TO", c["to"]),
                                       ("SMTP_USER", c["from"])) if not v]}


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
            self._last_sent[condition] = time.time()
        return True, "sending"

    def send_async(self, on_done, **kwargs):
        def run():
            try:
                send(**kwargs)
                on_done(f"sent {time.strftime('%H:%M:%S')}")
            except Exception as e:  # noqa: BLE001
                on_done(f"failed: {type(e).__name__}: {str(e)[:120]}")
        threading.Thread(target=run, name="indux-mail", daemon=True).start()
