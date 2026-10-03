"""
Indux soak test - run the live system for a long time and check it stays healthy.

1. Start the backend in one terminal:      python -m backend
2. Run this in a second terminal:          python tests/soak.py --minutes 60

Every cycle it runs the motor healthy, injects a random fault through the API,
then returns to healthy. It measures:
  - detection time and whether the alert names the right fault
  - false alerts while healthy
  - stalls (no reading for > 3 s) and backend errors
Writes data/soak_results.csv and prints PASS/FAIL at the end.
"""
import argparse
import asyncio
import csv
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

try:
    import websockets
except ImportError:
    sys.exit("pip install websockets   (it comes with uvicorn[standard])")

ROOT = Path(__file__).resolve().parent.parent
FAULTS = ["unbalance", "looseness", "bearing", "overload"]
DETECT_LIMIT_S = {"unbalance": 5, "looseness": 5, "bearing": 5, "overload": 15}  # overload heats slowly
SETTLE_S = 8          # after returning to healthy, alerts may take a few windows to clear


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def get(base, path):
    return json.loads(urllib.request.urlopen(base + path, timeout=10).read())


class Monitor:
    """Reads the WebSocket in the background and remembers what it saw."""

    def __init__(self):
        self.last = None
        self.last_time = time.monotonic()
        self.max_gap = 0.0
        self.readings = 0
        self.errors = []

    async def run(self, url):
        while True:
            try:
                async with websockets.connect(url, max_size=2 ** 22) as ws:
                    async for raw in ws:
                        m = json.loads(raw)
                        now = time.monotonic()
                        if m.get("type") == "status":
                            if m.get("status") in ("error", "disconnected"):
                                self.errors.append(f"{time.strftime('%H:%M:%S')} {m.get('status')}: {m.get('error')}")
                            continue
                        self.max_gap = max(self.max_gap, now - self.last_time)
                        self.last_time = now
                        self.last = m
                        self.readings += 1
            except Exception as e:  # noqa: BLE001 - reconnect on any drop
                self.errors.append(f"{time.strftime('%H:%M:%S')} websocket dropped: {type(e).__name__}")
                await asyncio.sleep(1)


async def wait_until(pred, timeout, step=0.1):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if pred():
            return time.monotonic() - t0
        await asyncio.sleep(step)
    return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--healthy", type=float, default=45, help="seconds healthy per cycle")
    ap.add_argument("--fault", type=float, default=25, help="seconds of fault per cycle")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    random.seed(args.seed)
    base = args.url.rstrip("/")
    ws_url = base.replace("http", "ws", 1) + "/ws/live"

    try:
        status = get(base, "/api/status")
    except Exception:  # noqa: BLE001
        sys.exit(f"Backend not reachable at {base}. Start it first: python -m backend")
    if status["source"]["kind"] != "sim":
        post(base, "/api/source", {"kind": "sim", "rpm": 5000})
    post(base, "/api/fault", {"condition": "healthy"})

    try:
        ns = get(base, "/api/notify/status")
        if ns.get("configured") and ns.get("auto_report"):
            print(f"NOTE: email alerts are ON ({', '.join(ns['to'])}). Each new fault type sends at most one "
                  f"email per {ns['cooldown_min']:.0f} min. Set AUTO_REPORT=0 in .env to test without emails.")
    except Exception:  # noqa: BLE001
        pass

    mon = Monitor()
    task = asyncio.create_task(mon.run(ws_url))
    print("Waiting for the baseline to be learned...")
    if await wait_until(lambda: mon.last and not mon.last["calibrating"], 90) is None:
        sys.exit("Never finished calibrating - is the backend running the simulator?")

    results, false_alerts, healthy_windows = [], 0, 0
    end = time.monotonic() + args.minutes * 60
    cycle = 0
    while time.monotonic() < end:
        cycle += 1
        # ---- healthy phase: count false alerts (after the settle time)
        post(base, "/api/fault", {"condition": "healthy"})
        await asyncio.sleep(SETTLE_S)
        seen = mon.readings
        t_end = time.monotonic() + max(0, args.healthy - SETTLE_S)
        while time.monotonic() < t_end:
            before = mon.readings
            await asyncio.sleep(0.5)
            if mon.readings > before and mon.last["alert"]:
                false_alerts += 1
        healthy_windows += mon.readings - seen

        # ---- fault phase
        fault = random.choice(FAULTS)
        sev = round(random.uniform(0.5, 1.0), 2)
        post(base, "/api/fault", {"condition": fault, "severity": sev})
        dt = await wait_until(lambda: mon.last["alert"] and mon.last["alert_condition"] == fault, args.fault)
        any_alert = mon.last["alert"]
        results.append({"cycle": cycle, "time": time.strftime("%H:%M:%S"), "fault": fault, "severity": sev,
                        "detect_s": None if dt is None else round(dt, 1),
                        "correct": dt is not None, "alerted_as": mon.last["alert_condition"] if any_alert else ""})
        r = results[-1]
        state = f"{r['detect_s']} s" if r["correct"] else f"MISSED (alert: {r['alerted_as'] or 'none'})"
        left = max(0, (end - time.monotonic()) / 60)
        print(f"[{r['time']}] cycle {cycle:3d}  {fault:10s} sev {sev:.2f} -> {state:28s} "
              f"false alerts so far {false_alerts}  ({left:.0f} min left)")
        if dt is not None:
            await asyncio.sleep(max(0, args.fault - dt))

    post(base, "/api/fault", {"condition": "healthy"})
    task.cancel()

    # ---- report
    out = ROOT / "data" / "soak_results.csv"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)

    print("\n================ SOAK TEST SUMMARY ================")
    print(f"Duration: {args.minutes:.0f} min, {mon.readings} readings, {cycle} fault cycles")
    ok = True
    for fault in FAULTS:
        rs = [r for r in results if r["fault"] == fault]
        if not rs:
            continue
        hits = [r for r in rs if r["correct"]]
        times = sorted(r["detect_s"] for r in hits)
        slow = [t for t in times if t > DETECT_LIMIT_S[fault]]
        med = times[len(times) // 2] if times else None
        good = len(hits) == len(rs) and not slow
        ok &= good
        print(f"  {fault:10s} detected {len(hits)}/{len(rs)}  median {med} s  "
              f"slowest {times[-1] if times else '-'} s  (limit {DETECT_LIMIT_S[fault]} s)  {'OK' if good else 'CHECK'}")
    fa_rate = false_alerts / max(1, healthy_windows)
    print(f"  False alerts while healthy: {false_alerts} checks  ({fa_rate:.2%} of healthy windows)")
    print(f"  Longest gap between readings: {mon.max_gap:.1f} s  (limit 3 s)")
    print(f"  Backend / connection errors: {len(mon.errors)}")
    for e in mon.errors[:10]:
        print("     ", e)
    ok &= false_alerts == 0 and mon.max_gap <= 3.0 and not mon.errors
    print(f"\nRESULT: {'PASS' if ok else 'FAIL - see lines marked CHECK above'}")
    print(f"Details saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
