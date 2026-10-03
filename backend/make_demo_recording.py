"""Record a scripted demo run to data/sim/demo_scenario.csv - the replay safety net.

    python -m backend.make_demo_recording          (runs instantly)

Timeline (5000 rpm): healthy 60 s (includes ~26 s learning normal) -> unbalance 20 s
-> healthy 20 s -> looseness 20 s -> healthy 20 s -> overload 25 s -> healthy 20 s
-> bearing wear ramping 0->100% over 90 s. About 4.6 minutes, then it loops.
"""
from pathlib import Path

from simulator.motor_sim import WINDOW_SEC, MotorSimulator, write_recording

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sim" / "demo_scenario.csv"

SCRIPT = [("healthy", 60), ("unbalance", 20), ("healthy", 20), ("looseness", 20),
          ("healthy", 20), ("overload", 25), ("healthy", 20), ("degrade", 90)]


def records(seed=2026, rpm=5000):
    sim = MotorSimulator("healthy", rpm, seed=seed, severity=0.8, ramp_seconds=90)
    for cond, seconds in SCRIPT:
        sim.set_condition(cond)
        for _ in range(int(round(seconds / WINDOW_SEC))):
            yield sim.next_window(include_label=True)


if __name__ == "__main__":
    n = write_recording(OUT, records())
    print(f"wrote {n} windows ({n * WINDOW_SEC / 60:.1f} min) to {OUT}")
