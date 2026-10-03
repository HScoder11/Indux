"""
Indux - train the live-demo models on simulator data, then test the full
live pipeline exactly as the backend will run it.

Run from the Indux folder:
    python ml/train_live.py            (about 3-6 minutes)
    python ml/train_live.py --quick    (smaller, for a fast check)

Makes: models/live_models.joblib        (loaded by ml/live.py -> backend)
       docs/figures/live_confusion.png
       docs/figures/live_demo_timeline.png
"""
import argparse
import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ml.features import StreamFeaturizer, FEATURE_LABELS          # noqa: E402
from simulator.motor_sim import MotorSimulator, WINDOW_SEC        # noqa: E402

FAULTS = ["unbalance", "looseness", "bearing", "overload"]
SPEEDS = [3000, 5000, 7000]
EXTRA_HEALTHY_SPEEDS = [4000, 6000]
TRAIN_SEEDS, TEST_SEEDS = [1, 2, 3, 4], [5]      # split by SESSION, never by window
SKIP = 5                                          # first windows fill the history


# ------------------------------------------------------------------ data
def record_session(condition, rpm, seed, n_windows):
    sim = MotorSimulator(condition, rpm, seed=seed * 1000 + rpm)
    feat = StreamFeaturizer()
    rows = []
    for i in range(n_windows):
        f = feat(sim.next_window())
        if i >= SKIP:
            f.update(label=condition, seed=seed, nominal_rpm=rpm)
            rows.append(f)
    return rows


def build(seeds, n_windows):
    rows = []
    for seed in seeds:
        for rpm in SPEEDS + EXTRA_HEALTHY_SPEEDS:
            conds = ["healthy"] + (FAULTS if rpm in SPEEDS else [])
            for c in conds:
                rows += record_session(c, rpm, seed, n_windows)
        print(f"  session {seed} done ({len(rows)} windows so far)")
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    n_windows = 40 if args.quick else 120          # 120 windows = ~77 s per session

    t0 = time.time()
    print("Recording simulator sessions...")
    train = build(TRAIN_SEEDS, n_windows)
    test = build(TEST_SEEDS, n_windows)
    meta = ("label", "seed", "nominal_rpm")
    features = [c for c in train.columns if c not in meta]
    print(f"{len(train)} train / {len(test)} test windows, {len(features)} features "
          f"({time.time() - t0:.0f}s)\n")

    fill = train[features].median()
    Xtr, Xte = train[features].fillna(fill), test[features].fillna(fill)

    # ---- Model 1: fault classifier
    clf = RandomForestClassifier(n_estimators=300, class_weight="balanced",
                                 min_samples_leaf=2, random_state=42, n_jobs=-1)
    clf.fit(Xtr.values, train.label)
    pred = clf.predict(Xte.values)
    labels = ["healthy"] + FAULTS
    print("=== Fault classifier (test = unseen session) ===")
    print(classification_report(test.label, pred, labels=labels, digits=3, zero_division=0))

    ConfusionMatrixDisplay(confusion_matrix(test.label, pred, labels=labels),
                           display_labels=labels).plot(cmap="Blues", colorbar=False)
    plt.title("Live classifier - unseen simulator session")
    plt.tight_layout()
    plt.savefig(ROOT / "docs" / "figures" / "live_confusion.png", dpi=150)
    plt.close()

    # "Why?" explanations use features the classifier relies on
    imp = pd.Series(clf.feature_importances_, index=features).drop(["rpm"], errors="ignore")
    explain = [k for k in imp.sort_values(ascending=False).index[:15] if k in FEATURE_LABELS]

    bundle = {"classifier": clf, "features": features, "fill_values": fill.to_dict(),
              "explain_features": explain, "distance_healthy": 1.0, "distance_alarm": 5.0}
    out = ROOT / "models" / "live_models.joblib"
    (ROOT / "models").mkdir(exist_ok=True)
    joblib.dump(bundle, out)

    # ---- Models 2 + 3: per-motor anomaly detector -> health score.
    # Each new motor (seed) learns its own normal for ~26 s, then we measure
    # how far healthy and faulty windows sit from that normal.
    from ml.live import LivePredictor, CALIB_WINDOWS
    print("=== Anomaly detector: learns each motor's normal, never sees a fault ===")
    dist = {c: [] for c in labels}
    p = LivePredictor(out)
    for seed in range(200, 200 + (6 if args.quick else 12)):
        for rpm in SPEEDS:
            for c in labels:
                p.reset()
                sim = MotorSimulator("healthy", rpm, seed=seed * 7 + rpm)
                for _ in range(CALIB_WINDOWS):          # learn normal (no classifier needed)
                    p.calib.append(p._clean(p.featurize(sim.next_window())))
                p._learn_baseline()
                sim.set_condition(c)
                for _ in range(25):
                    f = p._clean(p.featurize(sim.next_window()))
                    dist[c].append(p._distance(p._z(f)))
    d_healthy = float(np.median(dist["healthy"]))
    d_alarm = float(max(2 * d_healthy, np.percentile(dist["healthy"], 99.5) * 1.25))
    for c in labels:
        rate = (np.array(dist[c]) > d_alarm).mean()
        name = "false alarms (single window)" if c == "healthy" else "flagged"
        print(f"  {c:10s} {name}: {rate:.3f}")
    print(f"  healthy distance ~{d_healthy:.2f}, alarm line at {d_alarm:.2f}")

    bundle.update(distance_healthy=d_healthy, distance_alarm=d_alarm)
    joblib.dump(bundle, out)
    print("\nSaved models/live_models.joblib")

    # ---- Pipeline tests - exactly what the backend will do
    pipeline_tests(LivePredictor(out), quick=args.quick)
    print(f"\nTotal time {time.time() - t0:.0f}s")


def run(pred, sim, seconds, log, phase):
    for _ in range(int(seconds / WINDOW_SEC)):
        rec = sim.next_window()
        rec["ts"] = sim.sim_time
        m = pred.update(rec)
        log.append({"t": sim.sim_time, "phase": phase,
                    "health": m["health"] if m["health"] is not None else np.nan,
                    "alert": m["alert"], "alert_condition": m["alert_condition"],
                    "condition": m["condition"], "ttf": m["ttf_s"]})


def pipeline_tests(pred, quick=False):
    print("\n=== Live pipeline tests (new session, never seen in training) ===")

    # 1) Long healthy run: must give zero alerts
    minutes = 2 if quick else 10
    pred.reset()
    log = []
    run(pred, MotorSimulator("healthy", 5000, seed=777), minutes * 60, log, "healthy")
    n_alert = sum(r["alert"] for r in log)
    print(f"  {minutes}-min healthy run: {n_alert} alert windows "
          f"(min health {np.nanmin([r['health'] for r in log]):.0f})")

    # 2) Switch faults live, like pressing hotkeys during the demo
    pred.reset()
    sim = MotorSimulator("healthy", 5000, seed=888)
    log = []
    run(pred, sim, 35, log, "healthy")          # includes ~26 s learning normal
    print("  Fault injection (detected = alert with the right label):")
    for c in FAULTS:
        sim.set_condition(c)
        start = sim.sim_time
        run(pred, sim, 15, log, c)
        hit = [r for r in log if r["phase"] == c and r["alert_condition"] == c]
        delay = f"{hit[0]['t'] - start:.1f}s" if hit else "NOT detected"
        print(f"    {c:10s} severity {sim.severity_peak:.2f}: {delay}")
        sim.set_condition("healthy")
        run(pred, sim, 15, log, "healthy")
    timeline = log

    # 3) Gradual degradation: when does it warn?
    pred.reset()
    sim = MotorSimulator("healthy", 5000, seed=999, ramp_seconds=180)
    log = []
    run(pred, sim, 40, log, "healthy")
    sim.set_condition("degrade")
    start = sim.sim_time
    run(pred, sim, 200, log, "degrade")
    first = next((r for r in log if r["phase"] == "degrade" and r["alert"]), None)
    if first:
        sev = (first["t"] - start) / 180
        print(f"  Degradation (0->100% over 180 s): first alert after {first['t'] - start:.0f}s "
              f"at ~{sev * 100:.0f}% severity -> {first['alert_condition']}")
        named = next((r for r in log if r["phase"] == "degrade" and r["alert_condition"] == "bearing"), None)
        if named:
            print(f"    identified as bearing fault after {named['t'] - start:.0f}s "
                  f"(~{(named['t'] - start) / 1.8:.0f}% severity)")
    else:
        print("  Degradation: no alert")

    # timeline figure for the slides
    df = pd.DataFrame(timeline)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(df.t, df.health, color="k", lw=1.2)
    ax.axhline(50, color="r", ls="--", lw=1)
    ax.axhspan(80, 100, color="g", alpha=0.08)
    for phase, color in zip(FAULTS, ["tab:orange", "tab:purple", "tab:red", "tab:brown"]):
        seg = df[df.phase == phase]
        ax.axvspan(seg.t.min(), seg.t.max(), color=color, alpha=0.18, label=phase)
    ax.set_xlabel("Seconds")
    ax.set_ylabel("Health score")
    ax.set_title("Live demo rehearsal - faults injected one by one")
    ax.legend(loc="lower right", ncol=4)
    plt.tight_layout()
    plt.savefig(ROOT / "docs" / "figures" / "live_demo_timeline.png", dpi=150)
    print("  Saved docs/figures/live_demo_timeline.png")


if __name__ == "__main__":
    (ROOT / "docs" / "figures").mkdir(parents=True, exist_ok=True)
    main()