"""
Indux - exploratory data analysis: what the benchmark data looks like, before any model.

Run from the Indux folder:
    python ml/eda.py                 # all datasets that are present
    python ml/eda.py --only ai4i
Needs: whatever `python download_data.py` fetched
Makes: docs/figures/eda_ai4i.png    failure rate overall and by machine type, failed-vs-normal
                                    distributions per sensor, correlation heatmap
       docs/figures/eda_cwru.png    raw vibration per condition, RMS / kurtosis per condition and load
       docs/figures/eda_ims.png     RMS / kurtosis / outer-race signal of 4 bearings over the 7-day run
       docs/figures/eda_summary.txt the numbers behind the figures
"""
import argparse
import os
import re
import sys

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIG = os.path.join(ROOT, "docs", "figures")
BENCH = os.path.join(ROOT, "data", "benchmark")
BLUE, GREY, RED = "#2a78d6", "#9aa0a6", "#d03b3b"
summary: list[str] = []


def say(line=""):
    print(line)
    summary.append(line)


# ------------------------------------------------------------------ AI4I
def eda_ai4i():
    path = os.path.join(BENCH, "ai4i", "ai4i2020.csv")
    if not os.path.exists(path):
        say("AI4I: not found - run `python download_data.py --only ai4i`"); return
    from ml.train_ai4i import MODES, NAMES, load
    df = load()
    df["failed"] = (df["Machine failure"] == 1).astype(int)
    rate = df.failed.mean()
    say(f"AI4I 2020: {len(df)} rows, {df.failed.sum()} failures ({100 * rate:.2f}%).")
    say(f"  A model that always says 'no failure' is {100 * (1 - rate):.1f}% accurate - accuracy is useless here.")
    by_type = df.groupby("Type").failed.agg(["mean", "sum", "count"]).reindex(["L", "M", "H"])
    for t, r in by_type.iterrows():
        say(f"  Type {t}: {100 * r['mean']:.2f}% failures ({int(r['sum'])} of {int(r['count'])})")
    modes = {MODES[c]: int(df[c].sum()) for c in MODES} | {"Random (RNF)": int(df["RNF"].sum())}
    say("  Failure modes: " + ", ".join(f"{k} {v}" for k, v in modes.items()))

    sensors = ["air_temp", "proc_temp", "rpm", "torque", "tool_wear", "temp_diff", "power_w", "strain"]
    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(3, 5, height_ratios=[1, 1, 1.25])

    ax = fig.add_subplot(gs[0, 0])
    labels = ["All"] + list(by_type.index)
    vals = [100 * rate] + list(100 * by_type["mean"])
    ax.bar(labels, vals, color=[BLUE] + [GREY] * 3)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.05, f"{v:.1f}%", ha="center", fontsize=9)
    ax.set_title("Failure rate: all / by type L, M, H", fontsize=10); ax.set_ylabel("% of rows")

    ax = fig.add_subplot(gs[0, 1])
    ax.barh(list(modes), list(modes.values()), color=BLUE)
    ax.set_title("Failures by mode (rows can have >1)", fontsize=10)

    positions = [(0, 2), (0, 3), (0, 4), (1, 0), (1, 1), (1, 2), (1, 3), (1, 4)]
    for col, (r, c) in zip(sensors, positions):
        ax = fig.add_subplot(gs[r, c])
        ok, bad = df.loc[df.failed == 0, col], df.loc[df.failed == 1, col]
        bins = np.linspace(df[col].min(), df[col].max(), 40)
        ax.hist(ok, bins=bins, density=True, color=GREY, alpha=0.7, label="Normal")
        ax.hist(bad, bins=bins, density=True, color=RED, alpha=0.6, label="Failed")
        ax.set_title(NAMES.get(col, col), fontsize=10); ax.set_yticks([])
        if (r, c) == (0, 2):
            ax.legend(fontsize=8)
        say(f"  {NAMES.get(col, col):26s} normal median {ok.median():9.1f} | failed median {bad.median():9.1f}")

    ax = fig.add_subplot(gs[2, :3])
    cols = sensors + ["failed"]
    corr = df[cols].corr().values
    im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
    names = [NAMES.get(c, c).split(" (")[0] for c in sensors] + ["FAILED"]
    ax.set_xticks(range(len(cols)), names, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(len(cols)), names, fontsize=8)
    for i in range(len(cols)):
        for j in range(len(cols)):
            ax.text(j, i, f"{corr[i, j]:.2f}", ha="center", va="center", fontsize=7,
                    color="white" if abs(corr[i, j]) > 0.6 else "black")
    fig.colorbar(im, ax=ax, fraction=0.03)
    ax.set_title("Correlation: no single sensor predicts failure (|r| <= 0.19)", fontsize=10)

    ax = fig.add_subplot(gs[2, 3:])
    ax.scatter(df.loc[df.failed == 0, "rpm"], df.loc[df.failed == 0, "torque"], s=3, color=GREY, alpha=0.3, label="Normal")
    ax.scatter(df.loc[df.failed == 1, "rpm"], df.loc[df.failed == 1, "torque"], s=10, color=RED, label="Failed")
    ax.set_xlabel("Speed (rpm)"); ax.set_ylabel("Torque (Nm)"); ax.legend(fontsize=8)
    ax.set_title("Failures sit at the speed x torque extremes", fontsize=10)
    fails_corr = df[sensors].corrwith(df.failed).abs().sort_values(ascending=False)
    say("  |correlation with failure|: " + ", ".join(f"{NAMES[k].split(' (')[0]} {v:.2f}" for k, v in fails_corr.items()))

    fig.suptitle("AI4I 2020 - what the data looks like (public dataset, 10,000 rows)", fontsize=13, y=0.995)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "eda_ai4i.png"), dpi=130); plt.close(fig)
    say("  -> docs/figures/eda_ai4i.png\n")


# ------------------------------------------------------------------ CWRU
def eda_cwru():
    d = os.path.join(BENCH, "cwru")
    from ml.train_cwru import FILES
    have = {n: v for n, v in FILES.items() if os.path.exists(os.path.join(d, f"{n}.mat"))}
    if not have:
        say("CWRU: not found - run `python download_data.py --only cwru`"); return
    from scipy.io import loadmat
    from scipy.stats import kurtosis

    fs, win = 12000, 4096
    rows, snippets = [], {}
    for num, (cond, load) in have.items():
        m = loadmat(os.path.join(d, f"{num}.mat"))
        key = next(k for k in m if re.search(r"DE_time$", k))
        x = m[key].ravel()
        if load == 0:
            snippets[cond] = x[: int(0.1 * fs)]
        for i in range(0, len(x) - win, win):
            w = x[i:i + win]
            rows.append({"condition": cond, "load": load, "rms": np.sqrt(np.mean((w - w.mean()) ** 2)),
                         "kurtosis": kurtosis(w, fisher=False)})
    df = pd.DataFrame(rows)
    order = [c for c in ("normal", "inner", "ball", "outer") if c in set(df.condition)]
    counts = df.groupby("condition").size().reindex(order)
    say(f"CWRU (12 kHz drive end, 0.007\" faults): {len(have)} files, {len(df)} windows of {win} samples")
    say("  windows per condition: " + ", ".join(f"{c} {n}" for c, n in counts.items()))
    say("  (normal has more data than each fault - classes are imbalanced, so class weights are used)")

    fig, ax = plt.subplots(2, 4, figsize=(15, 6.5))
    for i, c in enumerate(order):
        s = snippets.get(c)
        if s is not None:
            ax[0, i].plot(np.arange(len(s)) / fs * 1000, s, lw=0.6, color=RED if c != "normal" else BLUE)
        ax[0, i].set_title(f"{c} - raw signal, 0 HP", fontsize=10); ax[0, i].set_xlabel("ms")
    ax[0, 0].set_ylabel("acceleration (g)")
    for j, metric in enumerate(("rms", "kurtosis")):
        a = ax[1, j * 2]
        data = [df.loc[df.condition == c, metric] for c in order]
        a.boxplot(data, tick_labels=order, showfliers=False)
        a.set_title(f"{metric.upper()} per condition (all loads)", fontsize=10)
        a2 = ax[1, j * 2 + 1]
        for c in order:
            g = df[df.condition == c].groupby("load")[metric].median()
            a2.plot(g.index, g.values, "o-", label=c)
        a2.set_xlabel("motor load (HP)"); a2.set_title(f"median {metric.upper()} vs load", fontsize=10)
        a2.legend(fontsize=8)
        say(f"  median {metric}: " + ", ".join(f"{c} {df.loc[df.condition == c, metric].median():.3f}" for c in order))
    fig.suptitle("CWRU bearings - what the data looks like (public dataset). Conditions separate cleanly at every "
                 "load (CWRU is an easy benchmark);\nball faults look normal in kurtosis, so they are caught by "
                 "energy (RMS) and the envelope spectrum instead", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "eda_cwru.png"), dpi=130); plt.close(fig)
    say("  -> docs/figures/eda_cwru.png\n")


# ------------------------------------------------------------------ NASA IMS
def eda_ims():
    cache = os.path.join(BENCH, "ims", "ims_features.csv")
    raw = os.path.join(BENCH, "ims", "2nd_test")
    if not os.path.exists(cache):
        if os.path.isdir(raw):
            say("IMS: run `python ml/train_ims.py` once first (it builds the feature cache this uses)")
        else:
            say("IMS: not found - run `python download_data.py --only ims`")
        return
    df = pd.read_csv(cache, parse_dates=["time"])
    days = (df.time.max() - df.time.min()).total_seconds() / 86400
    say(f"NASA IMS test 2: {df.time.nunique()} snapshots over {days:.1f} days, 4 bearings; bearing 1 fails (outer race)")
    first = df[df.time < df.time.min() + (df.time.max() - df.time.min()) * 0.2]
    last = df[df.time > df.time.max() - pd.Timedelta(hours=12)]
    for b in sorted(df.bearing.unique()):
        f, l = first[first.bearing == b], last[last.bearing == b]
        say(f"  bearing {b}: RMS {f.rms.median():.3f} -> {l.rms.median():.3f} g, "
            f"kurtosis {f['kurtosis'].median():.1f} -> {l['kurtosis'].median():.1f} (first 20% vs last 12 h)")

    fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    colors = {1: RED, 2: GREY, 3: "#b0b6bc", 4: "#c9cdd1"}
    for b in sorted(df.bearing.unique()):
        g = df[df.bearing == b].sort_values("time")
        kw = {"color": colors.get(b, GREY), "lw": 1.6 if b == 1 else 0.9,
              "label": f"Bearing {b}" + (" (fails)" if b == 1 else "")}
        ax[0].plot(g.time, g.rms.rolling(5, min_periods=1).median(), **kw)
        ax[1].plot(g.time, g["kurtosis"].rolling(5, min_periods=1).median(), **kw)
        ax[2].plot(g.time, g.env_bpfo_snr.rolling(5, min_periods=1).median(), **kw)
    ax[0].set_ylabel("RMS (g)"); ax[1].set_ylabel("kurtosis"); ax[2].set_ylabel("outer-race signal\n(envelope SNR)")
    ax[0].legend(fontsize=8, ncol=4)
    cutoff = df.time.min() + (df.time.max() - df.time.min()) * 0.2
    for a in ax:
        a.axvspan(df.time.min(), cutoff, color=BLUE, alpha=0.06)
    ax[0].text(df.time.min(), ax[0].get_ylim()[1] * 0.92, "  first 20%: 'healthy' training period", fontsize=8, color=BLUE)
    ax[0].set_title("NASA IMS - what the data looks like (public dataset). Bearing 1 degrades over the last ~3 days; "
                    "the others stay comparatively flat", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "eda_ims.png"), dpi=130); plt.close(fig)
    say("  -> docs/figures/eda_ims.png\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=["ai4i", "cwru", "ims"])
    args = ap.parse_args()
    os.makedirs(FIG, exist_ok=True)
    for name, fn in (("ai4i", eda_ai4i), ("cwru", eda_cwru), ("ims", eda_ims)):
        if not args.only or name in args.only:
            fn()
    with open(os.path.join(FIG, "eda_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(summary) + "\n")


if __name__ == "__main__":
    main()
