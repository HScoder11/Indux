"""AI maintenance report - Claude or Gemini - in English or Hindi, with an offline fallback.

Keys live ONLY in the backend .env file, never in React:
    ANTHROPIC_API_KEY=...     -> Claude
    GEMINI_API_KEY=...        -> Google Gemini
REPORT_PROVIDER picks the order: "auto" (default: Claude if its key is set, then
Gemini), "claude", "gemini" or "template". If a provider fails, the next one is
tried; if all fail (no key, no internet...), a template report is returned, so the
demo button always works.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CACHE_SECONDS = 60
MACHINE = os.getenv("INDUX_MACHINE_NAME", "BLDC Motor #1")

SYSTEM = """You are a maintenance engineer writing a short report for a factory technician.
Use ONLY the data provided. Never invent readings, part numbers, dates or costs.
If the data is not enough to say something, say so.
Write these sections with these exact headings:
1. What is wrong
2. Likely cause
3. Urgency (one of: Immediate / Within 24 hours / Next planned maintenance / No action)
4. Recommended action
5. Parts that may be needed
Keep it under 200 words, plain language, short bullet points."""

LANG_NOTE = {
    "en": "Write the report in English.",
    "hi": "Write the whole report in simple Hindi (Devanagari script). "
          "Keep technical words like RPM, bearing and FFT in English where that is clearer.",
}

_cache: dict[str, tuple[float, dict]] = {}


def _sig(v, n=3):
    """Round to n significant figures so reports don't show 821.8762."""
    if v is None or v == 0:
        return v
    from math import floor, log10
    return round(v, max(0, n - 1 - floor(log10(abs(v)))))


def build_summary(engine, lang="en") -> dict:
    """Everything the report may use - and nothing else."""
    last = engine.last or {}
    hist = list(engine.history)
    now = hist[-1]["ts"] if hist else time.time()
    past = [h for h in hist if h["ts"] >= now - 300 and h["health"] is not None]
    return {
        "machine": MACHINE,
        "data_source": engine.source.describe().get("name"),
        "current_condition": last.get("condition_label"),
        "confidence": last.get("confidence"),
        "health_score_now": last.get("health"),
        "health_5_min_ago": past[0]["health"] if past else None,
        "lowest_health_last_5_min": min((h["health"] for h in past), default=None),
        "zone": last.get("zone"),
        "top_reasons": [
            {"signal": r["label"], "value": _sig(r["value"]), "normal": _sig(r["normal"]),
             "times_normal_spread": r["z"], "direction": r["direction"]}
            for r in last.get("reasons", [])],
        "readings": {"rpm": last.get("rpm"), "current_A": last.get("current"),
                     "temperature_C": last.get("temp"), "vibration_rms_g": last.get("vib_rms")},
        "alert_active": last.get("alert"),
        "estimated_seconds_to_critical": last.get("ttf_s"),
        "recent_alerts": [
            {"time": time.strftime("%H:%M:%S", time.localtime(a["ts"])), "fault": a["label"],
             "health": a["health"], "resolved": a["resolved_ts"] is not None}
            for a in engine.store.alerts(limit=10)],
        "language": lang,
    }


def _template(s: dict, lang: str) -> str:
    cond = s["current_condition"] or "Unknown"
    healthy = cond == "Healthy" and not s["alert_active"]
    h = s["health_score_now"]
    urgent = h is not None and h < 50
    reasons = s["top_reasons"]
    if lang == "hi":
        why = "\n".join(f"- {r['signal']}: {r['value']} (सामान्य {r['normal']})" for r in reasons) or "- कोई खास संकेत नहीं"
        if healthy:
            return (f"**{s['machine']} – रखरखाव रिपोर्ट (ऑफ़लाइन)**\n\n1. क्या गलत है\n- मशीन सामान्य चल रही है।\n\n"
                    f"2. संभावित कारण\n- कोई दोष नहीं मिला।\n\n3. तात्कालिकता\n- कोई कार्रवाई नहीं\n\n"
                    f"4. सुझाई गई कार्रवाई\n- सामान्य निगरानी जारी रखें।\n\n5. आवश्यक पुर्ज़े\n- कोई नहीं\n\n"
                    f"हेल्थ स्कोर: {s['health_score_now']}")
        return (f"**{s['machine']} – रखरखाव रिपोर्ट (ऑफ़लाइन)**\n\n1. क्या गलत है\n- पहचाना गया दोष: {cond} "
                f"(विश्वास {s['confidence']})\n- हेल्थ स्कोर: {s['health_score_now']}\n\n2. संभावित कारण\n{why}\n\n"
                f"3. तात्कालिकता\n- {'तुरंत' if urgent else '24 घंटे के भीतर'}\n\n"
                f"4. सुझाई गई कार्रवाई\n- मशीन की जाँच करें और डैशबोर्ड पर दी गई कार्रवाई का पालन करें।\n\n"
                f"5. आवश्यक पुर्ज़े\n- जाँच के बाद तय करें।\n\n_यह ऑफ़लाइन टेम्पलेट रिपोर्ट है।_")
    why = "\n".join(f"- {r['signal']} is {r['direction']} than normal ({r['value']} vs {r['normal']})"
                    for r in reasons) or "- No stand-out signals"
    if healthy:
        return (f"**{s['machine']} - Maintenance report (offline)**\n\n1. What is wrong\n- Nothing: the machine is "
                f"running normally.\n\n2. Likely cause\n- No fault detected.\n\n3. Urgency\n- No action\n\n"
                f"4. Recommended action\n- Continue normal monitoring.\n\n5. Parts that may be needed\n- None\n\n"
                f"Health score: {s['health_score_now']}")
    from backend.engine import ACTIONS
    key = {"Bearing fault": "bearing", "Unknown anomaly": "anomaly"}.get(cond, cond.lower())
    return (f"**{s['machine']} - Maintenance report (offline)**\n\n1. What is wrong\n- Detected: {cond} "
            f"(confidence {s['confidence']})\n- Health score: {s['health_score_now']}\n\n2. Likely cause\n{why}\n\n"
            f"3. Urgency\n- {'Immediate' if urgent else 'Within 24 hours'}\n\n"
            f"4. Recommended action\n- {ACTIONS.get(key, ACTIONS['anomaly'])}\n\n"
            f"5. Parts that may be needed\n- Decide after inspection.\n\n"
            f"_Offline template report._")


def _claude(prompt):
    import anthropic
    client = anthropic.Anthropic(timeout=20.0, max_retries=1)
    resp = client.messages.create(model=MODEL, max_tokens=800, system=SYSTEM,
                                  messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text"), MODEL


def _gemini(prompt):
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.3},
    }
    req = urllib.request.Request(GEMINI_URL.format(model=GEMINI_MODEL), data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=25).read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:200]
        raise RuntimeError(f"HTTP {e.code} {detail}") from e
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts if not p.get("thought")), GEMINI_MODEL


PROVIDERS = {"claude": _claude, "gemini": _gemini}


def _providers():
    has = {"claude": bool(os.getenv("ANTHROPIC_API_KEY")),
           "gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))}
    choice = os.getenv("REPORT_PROVIDER", "auto").lower()
    if choice == "template":
        return []
    order = [choice] + [p for p in ("claude", "gemini") if p != choice] if choice in has else ["claude", "gemini"]
    return [p for p in order if has[p]]


def generate(engine, lang="en") -> dict:
    lang = lang if lang in LANG_NOTE else "en"
    s = build_summary(engine, lang)
    # Same situation + language within a minute -> reuse, don't pay for another call
    sig = {k: s[k] for k in ("current_condition", "alert_active", "zone", "language")}
    sig["health"] = round((s["health_score_now"] or 0) / 10)
    key = hashlib.md5(json.dumps(sig, sort_keys=True).encode()).hexdigest()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return {**hit[1], "cached": True}

    prompt = f"{LANG_NOTE[lang]}\n\nMachine data (JSON):\n{json.dumps(s, ensure_ascii=False, indent=1)}"
    result, notes = None, []
    for name in _providers():
        try:
            text, model = PROVIDERS[name](prompt)
            if text.strip():
                result = {"report": text, "engine": name, "model": model}
                break
            notes.append(f"{name}: empty reply")
        except Exception as e:  # noqa: BLE001 - any failure falls through to the next provider
            notes.append(f"{name}: {type(e).__name__}")
    if result is None:
        note = "; ".join(notes) if notes else "no ANTHROPIC_API_KEY or GEMINI_API_KEY set"
        result = {"report": _template(s, lang), "engine": "template", "note": f"AI unavailable ({note})"}
    elif notes:
        result["note"] = "fell back after " + "; ".join(notes)

    result.update(lang=lang, generated_at=time.time(), summary=s, cached=False)
    try:
        result["id"] = engine.store.save_report(result)       # keep every fresh report
    except Exception:  # noqa: BLE001 - never lose the report because saving failed
        result["id"] = None
    _cache[key] = (time.time(), result)
    return result


# ---------------------------------------------------------------- downloads
ENGINE_NAME = {"claude": "Claude", "gemini": "Gemini", "template": "Offline template"}


def _header_lines(r: dict) -> list[tuple[str, str]]:
    when = time.strftime("%d %b %Y, %H:%M:%S", time.localtime(r["ts"]))
    health = "-" if r.get("health") is None else f"{r['health']:.0f} / 100"
    by = ENGINE_NAME.get(r["engine"], r["engine"]) + (f" ({r['model']})" if r.get("model") else "")
    return [("Machine", MACHINE), ("Generated", when), ("Condition", r.get("condition") or "-"),
            ("Health score", health), ("Data source", r.get("source") or "-"),
            ("Language", "Hindi" if r["lang"] == "hi" else "English"), ("Written by", by),
            ("Report ID", f"#{r['id']}")]


def filename(r: dict, ext: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(r["ts"]))
    return f"indux_report_{r['id']}_{stamp}_{r['lang']}.{ext}"


def to_text(r: dict) -> str:
    head = "\n".join(f"{k}: {v}" for k, v in _header_lines(r))
    return f"INDUX MAINTENANCE REPORT\n{'=' * 40}\n{head}\n{'=' * 40}\n\n{r['text'].strip()}\n"


def to_markdown(r: dict) -> str:
    head = "\n".join(f"| {k} | {v} |" for k, v in _header_lines(r))
    return f"# Indux maintenance report\n\n| | |\n|---|---|\n{head}\n\n{r['text'].strip()}\n"


def _md_to_html(text: str) -> str:
    """Headings, bullets, bold, italics. Everything is HTML-escaped first."""
    import html
    import re

    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        return re.sub(r"(?<![\w])_(.+?)_(?![\w])", r"<em>\1</em>", t)

    out, in_list = [], False
    for raw in text.splitlines():
        line = raw.strip()
        bullet = re.match(r"^[-*•]\s+(.*)", line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(bullet.group(1))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if not line:
            continue
        head = re.match(r"^#{1,6}\s+(.*)", line) or re.match(r"^(\d+\.\s+.*)$", line)
        if head:
            out.append(f"<h3>{inline(head.group(1).replace('**', ''))}</h3>")
        else:
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def to_html(r: dict) -> str:
    import html
    rows = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>" for k, v in _header_lines(r))
    return f"""<!doctype html>
<html lang="{'hi' if r['lang'] == 'hi' else 'en'}"><head><meta charset="utf-8">
<title>Indux report #{r['id']}</title>
<style>
 body {{ font-family: "Segoe UI", "Nirmala UI", "Noto Sans Devanagari", system-ui, sans-serif;
        max-width: 760px; margin: 32px auto; padding: 0 20px; color: #111; line-height: 1.5; }}
 h1 {{ font-size: 24px; margin: 0 0 4px; }} .brand {{ color: #666; margin-bottom: 18px; }}
 table {{ border-collapse: collapse; width: 100%; margin: 12px 0 20px; font-size: 14px; }}
 th {{ text-align: left; width: 34%; color: #555; font-weight: 600; }}
 th, td {{ border-bottom: 1px solid #ddd; padding: 6px 8px; }}
 h3 {{ font-size: 17px; margin: 18px 0 6px; }} ul {{ margin: 4px 0; }}
 .bar {{ margin: 18px 0; }} button {{ font: inherit; padding: 8px 14px; cursor: pointer; }}
 .foot {{ color: #777; font-size: 12px; margin-top: 28px; border-top: 1px solid #ddd; padding-top: 8px; }}
 @media print {{ .bar {{ display: none; }} body {{ margin: 0 auto; }} }}
</style></head><body>
<h1>Maintenance report</h1><div class="brand">Indux predictive maintenance</div>
<div class="bar"><button onclick="window.print()">Print / Save as PDF</button></div>
<table>{rows}</table>
{_md_to_html(r['text'])}
<div class="foot">Generated automatically from sensor data. Verify on the machine before replacing parts.</div>
</body></html>"""
