"""
Indux - NASA IMS run-to-failure benchmark: health score, early warning,
time-to-failure.

2nd test: 4 bearings on one shaft, 2000 RPM, one 1-second recording
every 10 minutes for ~7 days, until bearing 1 failed (outer race).

Each bearing gets its own anomaly detector trained ONLY on its first
20% of life ("learn this machine's normal"), exactly as a real
deployment would do.

Run from the Indux folder:
    python ml/train_ims.py
Needs: data/benchmark/ims/2nd_test/   (files named like 2004.02.12.10.32.39)
Makes: data/benchmark/ims/ims_features.csv   (cache - delete to recompute)
       docs/figures/ims_health.png
       models/ims_iforest.joblib
"""
import os
import sys
from datetime import datetime
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ml.features import extract, IMS_ZA2115  # noqa: E402

DATA_DIR = os.path.join(ROOT, "data", "benchmark", "ims", "2nd_test")
CACHE = os.path.join(ROOT, "data", "benchmark", "ims", "ims_features.csv")
FS, RPM = 20480, 2000
BEARINGS = 4
BASELINE_FRAC = 0.20          # first 20% of life = "healthy" training data
CRITICAL_X = 4.0              # "critical" = RMS at 4x its healthy level
SMOOTH = 6                    # 6 files = 1 hour moving average
FEATS = ["rms", "kurtosis", "crest", "spectral_centroid", "band_1k_2k", "band_2k_up",
         "env_bpfo_snr", "env_bpfi_snr", "env_bsf_snr", "env_ftf_snr"]


# ---------------------------------------------------------------- features
def build_features():
    if os.path.exists(CACHE):
        print(f"Using cached features: {CACHE}")
        return pd.read_csv(CACHE, parse_dates=["time"])
    files = sorted(f for f in os.listdir(DATA_DIR) if not f.startswith("."))
    if not files:
        raise SystemExit(f"No files in {DATA_DIR}")
    rows = []
    for i, name in enumerate(files):
        t = datetime.strptime(name, "%Y.%m.%d.%H.%M.%S")
        data = pd.read_csv(os.path.join(DATA_DIR, name), sep=r"\s+", header=None).values
        for b in range(BEARINGS):
            f = extract(data[:, b], FS, RPM, bearing=IMS_ZA2115)
            rows.append({"time": t, "bearing": b + 1, **{k: f[k] for k in FEATS}})
        if i % 100 == 0:
            print(f"  {i}/{len(files)} files")
    df = pd.DataFrame(rows)
    df.to_csv(CACHE, index=False)
    return df


# ---------------------------------------------------------------- helpers
def to_X(d):
    return np.log1p(d[FEATS].clip(lower=0).values)


def health_from_score(score, base_scores):
    lo, mid = np.percentile(base_scores, 1), np.median(base_scores)
    return np.clip(50 + 50 * (score - lo) / (mid - lo + 1e-12), 0, 100)


def first_alert(flags, times, need=3, of=5):
    """Time of the first window where `need` of the last `of` are flagged."""
    s = pd.Series(flags.astype(int)).rolling(of, min_periods=of).sum()
    hit = np.where(s.values >= need)[0]
    return times[hit[0]] if len(hit) else None


def time_to_critical(hours, rms, critical, lookback=12):
    """Hours until RMS reaches `critical`, from an exponential trend
    (straight line on log RMS) fitted to the last `lookback` recordings."""
    log_r = np.log(pd.Series(rms).rolling(SMOOTH, min_periods=1).mean().values)
    out = np.full(len(rms), np.nan)
    for i in range(lookback, len(rms)):
        slope, icpt = np.polyfit(hours[i - lookback:i + 1], log_r[i - lookback:i + 1], 1)
        if slope > 1e-6 and log_r[i] < np.log(critical):
            out[i] = (np.log(critical) - log_r[i]) / slope
    return out


# ---------------------------------------------------------------- main
def main():
    os.makedirs(os.path.join(ROOT, "docs", "figures"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "models"), exist_ok=True)
    df = build_features().sort_values(["bearing", "time"]).reset_index(drop=True)
    end = df.time.max()
    print(f"\nRun: {df.time.min()}  ->  {end}  ({(end - df.time.min()).total_seconds() / 86400:.1f} days, "
          f"{df.time.nunique()} recordings)\n")

    saved, results = {}, {}
    for b in range(1, BEARINGS + 1):
        d = df[df.bearing == b].copy()
        n_base = int(len(d) * BASELINE_FRAC)
        base = d.iloc[:n_base]

        scaler = StandardScaler().fit(to_X(base))
        iso = IsolationForest(n_estimators=300, random_state=42).fit(scaler.transform(to_X(base)))
        base_scores = iso.decision_function(scaler.transform(to_X(base)))
        scores = iso.decision_function(scaler.transform(to_X(d)))
        d["health"] = health_from_score(scores, base_scores)
        d["health_smooth"] = d.health.rolling(SMOOTH, min_periods=1).mean()
        times = d.time.values

        # AI alert: health < 50 in 3 of last 5 recordings
        ai_alert = first_alert(d.health.values < 50, times)
        # Classic baseline: RMS above mean + 3 sigma of the healthy period
        thr = base["rms"].mean() + 3 * base["rms"].std()
        rms_alert = first_alert(d["rms"].values > thr, times)
        results[b] = (d, ai_alert, rms_alert)
        saved[b] = {"model": iso, "scaler": scaler, "features": FEATS, "base_scores": base_scores}

        def fmt(a):
            if a is None:
                return "no alert"
            lead = (end - pd.Timestamp(a)).total_seconds() / 3600
            return f"{pd.Timestamp(a):%b %d %H:%M}  ({lead:.1f} h before end)"
        print(f"Bearing {b}:  AI alert: {fmt(ai_alert):40s} RMS-threshold alert: {fmt(rms_alert)}")

    joblib.dump(saved, os.path.join(ROOT, "models", "ims_iforest.joblib"))

    # ---- time-to-critical check on the failing bearing (1)
    d1, ai1, _ = results[1]
    hours = (d1.time - d1.time.min()).dt.total_seconds().values / 3600
    n_base = int(len(d1) * BASELINE_FRAC)
    critical = CRITICAL_X * d1["rms"].iloc[:n_base].mean()
    ttc = time_to_critical(hours, d1["rms"].values, critical)
    smooth_rms = d1["rms"].rolling(SMOOTH, min_periods=1).mean().values
    crossed = np.where(smooth_rms >= critical)[0]
    after = np.zeros(len(d1), bool)
    if crossed.size and ai1 is not None:
        t_crit = hours[crossed[0]]
        actual = t_crit - hours
        after = (~np.isnan(ttc)) & (d1.time.values >= ai1) & (actual > 0)
        print(f"\nBearing 1 reached critical ({CRITICAL_X:.0f}x healthy RMS) at "
              f"{d1.time.iloc[crossed[0]]:%b %d %H:%M}")
        if after.any():
            err = np.abs(ttc[after] - actual[after])
            print(f"Time-to-critical after the alert: median error {np.median(err):.1f} h "
                  f"over {after.sum()} estimates")
    else:
        actual = np.full(len(d1), np.nan)
        print(f"\nBearing 1 never reached {CRITICAL_X:.0f}x healthy RMS - lower CRITICAL_X")

    # ---- figure
    fig, ax = plt.subplots(3, 1, figsize=(11, 11), sharex=True)
    for b, (d, ai, _) in results.items():
        ax[0].plot(d.time, d.health_smooth, lw=1.5 if b == 1 else 1,
                   label=f"Bearing {b}" + (" (failed)" if b == 1 else ""))
    ax[0].axhline(50, color="r", ls="--", lw=1)
    ax[0].axhspan(80, 100, color="g", alpha=0.07)
    if ai1 is not None:
        ax[0].axvline(ai1, color="orange", lw=2, label="AI alert (bearing 1)")
    ax[0].set_ylabel("Health score")
    ax[0].set_title("NASA IMS - health score over the bearings' life")
    ax[0].legend(loc="lower left")

    ax[1].plot(d1.time, d1["rms"], label="RMS")
    ax[1].axhline(critical, color="k", ls=":", lw=1)
    ax[1].set_ylabel("RMS (g)")
    ax2 = ax[1].twinx()
    ax2.plot(d1.time, d1["kurtosis"], color="tab:red", alpha=0.6, label="Kurtosis")
    ax2.set_ylabel("Kurtosis")
    ax[1].set_title("Bearing 1 - raw indicators")

    ax[2].plot(d1.time[after], actual[after], "k--", label="Actual time left")
    ax[2].plot(d1.time[after], ttc[after], color="tab:purple", label="Predicted time left")
    if after.any():
        ax[2].set_ylim(0, 3 * np.nanmax(actual[after]))
    ax[2].set_ylabel("Hours")
    ax[2].set_title(f"Bearing 1 - time to critical ({CRITICAL_X:.0f}x healthy RMS), after the alert")
    ax[2].legend()
    plt.tight_layout()
    out = os.path.join(ROOT, "docs", "figures", "ims_health.png")
    plt.savefig(out, dpi=150)
    print(f"\nSaved {out} and models/ims_iforest.joblib")


if __name__ == "__main__":
    main()