"""Indux motor simulator.

Emits fake sensor windows in the shared data contract (docs/data_contract.md):
one JSON object per 2048-sample window at 3200 Hz.

    python simulator/motor_sim.py --condition unbalance --rpm 5000 --stream
    python simulator/motor_sim.py --condition bearing --rpm 3000 --record 180

While streaming, press 1-6 to switch condition live and q to quit:
    1 healthy  2 unbalance  3 looseness  4 bearing  5 overload  6 degrade

Status messages go to stderr, so stdout stays clean JSON lines you can pipe.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

FS = 3200
N = 2048
WINDOW_SEC = N / FS
BPFO_RATIO = 3.5  # outer-race fault frequency as a multiple of shaft speed

CONDITIONS = ("healthy", "unbalance", "looseness", "bearing", "overload", "degrade")
HOTKEYS = {str(i + 1): c for i, c in enumerate(CONDITIONS)}

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_FIELDS = ("ts", "source", "rpm", "current", "voltage", "temp", "fs", "condition", "severity", "vib")


class MotorSimulator:
    """Stateful generator of contract-format windows.

    Every session (every seed) draws its own noise level, harmonic amplitudes,
    phases, RPM offset and fault signatures, so a model trained on it has to
    learn the fault rather than one exact waveform.
    """

    def __init__(self, condition="healthy", rpm=5000.0, seed=None, severity=None,
                 ramp_seconds=180.0, source="sim", wall_clock=False):
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.nominal_rpm = float(rpm)
        self.fixed_severity = severity
        self.ramp_seconds = float(ramp_seconds)
        self.source = source
        self.wall_clock = wall_clock
        self._lock = threading.Lock()

        self.p = self._draw_session_params()
        self.sim_time = 0.0
        self.start_ts = time.time()
        self._theta = self.rng.uniform(0, 4 * math.pi)  # wrapped at 4*pi so the 0.5x term stays continuous
        self._impulses: list[float] = []  # bearing impact times (sim seconds)
        self.temp = self._target_temp("healthy", 0.0)  # start warmed up and healthy

        self.condition = "healthy"
        self.severity_peak = 0.0
        self.condition_start = 0.0
        self.set_condition(condition)

    # ---------------------------------------------------------------- session
    def _draw_session_params(self) -> dict:
        u = self.rng.uniform
        a1 = u(0.04, 0.08)
        return {
            "noise": u(0.02, 0.05),
            "a1": a1, "a2": a1 * u(0.2, 0.45), "a3": a1 * u(0.08, 0.2),
            "phi": u(0, 2 * math.pi, size=4),
            "rpm_offset": u(-0.015, 0.015),
            "rpm_jitter": u(0.001, 0.003),
            "current_base": u(1.2, 1.6),
            "voltage": u(11.8, 12.3),
            "ambient": u(24.0, 32.0),
            "self_heat": u(8.0, 14.0),
            "thermal_tau": u(40.0, 80.0),
            # fault signatures
            "unb_gain": u(3.0, 6.0), "unb_current": u(0.02, 0.06),
            "loose_g2": u(2.5, 4.5), "loose_g3": u(3.0, 6.0), "loose_half": u(0.3, 0.6),
            "loose_clip": u(0.15, 0.3), "loose_wobble": u(0.004, 0.01),
            "brg_amp": u(0.4, 1.0), "brg_ring": u(900.0, 1100.0), "brg_tau": u(0.0005, 0.0009),
            "brg_slip": u(0.005, 0.015), "brg_heat": u(4.0, 8.0),
            "ovl_vib": u(0.15, 0.35), "ovl_current": u(0.3, 0.6), "ovl_heat": u(12.0, 22.0),
            "ovl_drop": u(0.03, 0.05),
        }

    def set_condition(self, condition: str) -> None:
        """Switch fault live. Draws a fresh severity unless one was fixed."""
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition {condition!r}; choose from {CONDITIONS}")
        with self._lock:
            self.condition = condition
            if self.fixed_severity is not None:
                self.severity_peak = float(self.fixed_severity)
            else:
                self.severity_peak = float(self.rng.uniform(0.5, 1.0))
            self.condition_start = self.sim_time

    def severity(self) -> float:
        if self.condition == "healthy":
            return 0.0
        if self.condition == "degrade":
            frac = (self.sim_time - self.condition_start) / self.ramp_seconds
            return float(np.clip(frac, 0.0, 1.0))
        return self.severity_peak

    # ----------------------------------------------------------------- physics
    def _target_temp(self, kind: str, s: float) -> float:
        p = self.p
        extra = {"bearing": p["brg_heat"], "overload": p["ovl_heat"],
                 "unbalance": 1.0, "looseness": 1.0}.get(kind, 0.0) * s
        return p["ambient"] + p["self_heat"] * (self.nominal_rpm / 5000.0) + extra

    def _bearing_impulses(self, t, t0, f1, s):
        """Decaying ~1 kHz rings at the outer-race rate, carried across windows."""
        p = self.p
        period = 1.0 / (BPFO_RATIO * f1)
        t_end = t0 + WINDOW_SEC
        if not self._impulses:
            self._impulses.append(t0 + self.rng.uniform(0, period))
        while self._impulses[-1] < t_end:
            self._impulses.append(self._impulses[-1] + period * (1 + self.rng.normal(0, p["brg_slip"])))
        tail = 6 * p["brg_tau"]
        self._impulses = [tk for tk in self._impulses if tk > t0 - tail]

        out = np.zeros_like(t)
        span = int(tail * FS) + 1
        for tk in self._impulses:
            i0 = max(0, int(math.ceil((tk - t0) * FS)))
            if i0 >= len(t):
                continue
            seg = slice(i0, min(len(t), i0 + span))
            local = t[seg] - tk
            amp = p["brg_amp"] * s * (1 + 0.2 * self.rng.normal())
            out[seg] += amp * np.exp(-local / p["brg_tau"]) * np.sin(2 * math.pi * p["brg_ring"] * local)
        return out

    def next_window(self, include_label=False) -> dict:
        with self._lock:
            cond = self.condition
            s = self.severity()
        kind = "bearing" if cond == "degrade" else cond
        p, rng = self.p, self.rng

        # speed
        rpm = self.nominal_rpm * (1 + p["rpm_offset"])
        if kind == "overload":
            rpm *= 1 - p["ovl_drop"] * s
        wobble = p["rpm_jitter"] + (p["loose_wobble"] * s if kind == "looseness" else 0.0)
        rpm *= 1 + rng.normal(0, wobble)
        f1 = rpm / 60.0

        # continuous shaft angle across windows
        n = np.arange(N)
        theta = self._theta + 2 * math.pi * f1 * n / FS
        self._theta = (self._theta + 2 * math.pi * f1 * N / FS) % (4 * math.pi)
        t0 = self.sim_time
        t = t0 + n / FS

        a1, a2, a3 = p["a1"], p["a2"], p["a3"]
        if kind == "unbalance":
            a1 *= 1 + s * (p["unb_gain"] - 1)
        if kind == "looseness":
            a2 *= 1 + s * (p["loose_g2"] - 1)
            a3 *= 1 + s * (p["loose_g3"] - 1)
        phi = p["phi"]
        x = (a1 * np.sin(theta + phi[0]) + a2 * np.sin(2 * theta + phi[1])
             + a3 * np.sin(3 * theta + phi[2]))
        if kind == "looseness":
            x += p["loose_half"] * s * p["a1"] * np.sin(0.5 * theta + phi[3])
        x += rng.normal(0, p["noise"], N)

        if kind == "bearing":
            x += self._bearing_impulses(t, t0, f1, s)
        else:
            self._impulses = []
        if kind == "looseness":  # one-sided truncation of peaks
            x = np.minimum(x, x.max() * (1 - p["loose_clip"] * s))
        if kind == "overload":
            x *= 1 + p["ovl_vib"] * s

        # thermal (first-order lag towards target)
        target = self._target_temp(kind, s)
        self.temp += (target - self.temp) * (1 - math.exp(-WINDOW_SEC / p["thermal_tau"]))

        # electrical
        load = {"unbalance": p["unb_current"], "overload": p["ovl_current"], "bearing": 0.02}.get(kind, 0.0) * s
        base_current = p["current_base"] * (0.7 + 0.3 * self.nominal_rpm / 5000.0)
        current = base_current * (1 + load) * (1 + rng.normal(0, 0.01))
        voltage = p["voltage"] * (1 - 0.02 * load) + rng.normal(0, 0.02)

        self.sim_time += WINDOW_SEC
        rec = {
            "ts": round(time.time() if self.wall_clock else self.start_ts + t0, 3),
            "source": self.source,
            "rpm": round(rpm, 1),
            "current": round(current, 3),
            "voltage": round(voltage, 3),
            "temp": round(self.temp + rng.normal(0, 0.05), 2),
            "fs": FS,
            "vib": np.round(x, 5).tolist(),
        }
        if include_label:
            rec["label"] = {"condition": cond, "severity": round(s, 3)}
        return rec


# --------------------------------------------------------------------- CSV io
def write_recording(path, records) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_FIELDS)
        for r in records:
            lab = r.get("label", {})
            w.writerow([r["ts"], r["source"], r["rpm"], r["current"], r["voltage"], r["temp"], r["fs"],
                        lab.get("condition", ""), lab.get("severity", ""),
                        " ".join(f"{v:.5f}" for v in r["vib"])])
            count += 1
    return count


def read_recording(path):
    """Yield contract dicts (vib as np.ndarray) from a CSV made by --record."""
    def num(v):
        return float(v) if v not in ("", None) else None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rec = {k: num(row[k]) for k in ("ts", "rpm", "current", "voltage", "temp", "fs")}
            rec["source"] = row["source"]
            rec["vib"] = np.array(row["vib"].split(), dtype=float)
            if row.get("condition"):
                rec["label"] = {"condition": row["condition"], "severity": num(row["severity"])}
            yield rec


# -------------------------------------------------------------------- hotkeys
def _hotkey_loop(sim: MotorSimulator, stop: threading.Event) -> None:
    def handle(ch):
        if ch.lower() == "q":
            stop.set()
        elif ch in HOTKEYS:
            sim.set_condition(HOTKEYS[ch])
            print(f"[sim] condition -> {sim.condition} (severity {sim.severity_peak:.2f})", file=sys.stderr)

    if os.name == "nt":
        import msvcrt
        while not stop.is_set():
            if msvcrt.kbhit():
                handle(msvcrt.getwch())
            else:
                time.sleep(0.05)
        return

    if not sys.stdin.isatty():
        return
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while not stop.is_set():
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if ready:
                handle(sys.stdin.read(1))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ------------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--condition", choices=CONDITIONS, default="healthy")
    ap.add_argument("--rpm", type=float, default=5000)
    ap.add_argument("--seed", type=int, default=None, help="session seed (random if omitted)")
    ap.add_argument("--severity", type=float, default=None, help="fix fault severity 0-1 (random 0.5-1 if omitted)")
    ap.add_argument("--ramp", type=float, default=180, help="seconds for degrade mode to reach full severity")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stream", action="store_true", help="print JSON lines in real time")
    mode.add_argument("--record", type=float, metavar="SECONDS", help="generate SECONDS of data to CSV (runs instantly)")
    ap.add_argument("--out", help="CSV path for --record (default: data/sim/<auto>.csv)")
    ap.add_argument("--label", action="store_true", help="include ground-truth label in streamed JSON")
    ap.add_argument("--no-hotkeys", action="store_true")
    args = ap.parse_args(argv)

    seed = args.seed if args.seed is not None else int(np.random.SeedSequence().entropy % 2**31)

    if args.record is not None:
        sim = MotorSimulator(args.condition, args.rpm, seed, args.severity, args.ramp)
        n_windows = max(1, int(round(args.record / WINDOW_SEC)))
        out = args.out or REPO_ROOT / "data" / "sim" / f"{args.condition}_{int(args.rpm)}rpm_seed{seed}.csv"
        count = write_recording(out, (sim.next_window(include_label=True) for _ in range(n_windows)))
        print(f"[sim] wrote {count} windows ({count * WINDOW_SEC:.0f}s) to {out}", file=sys.stderr)
        return 0

    sim = MotorSimulator(args.condition, args.rpm, seed, args.severity, args.ramp, wall_clock=True)
    stop = threading.Event()
    if not args.no_hotkeys:
        threading.Thread(target=_hotkey_loop, args=(sim, stop), daemon=True).start()
        print("[sim] keys: " + "  ".join(f"{k}={c}" for k, c in HOTKEYS.items()) + "  q=quit", file=sys.stderr)
    print(f"[sim] streaming {args.condition} @ {args.rpm:.0f} rpm, seed {seed}", file=sys.stderr)

    next_tick = time.monotonic()
    try:
        while not stop.is_set():
            print(json.dumps(sim.next_window(include_label=args.label)), flush=True)
            next_tick += WINDOW_SEC
            time.sleep(max(0.0, next_tick - time.monotonic()))
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
