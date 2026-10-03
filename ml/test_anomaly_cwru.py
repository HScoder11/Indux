"""
Indux - "works on problems it has never seen" test.

An Isolation Forest learns ONLY what a healthy motor looks like
(CWRU normal data, loads 0-2). It is then tested on healthy load 3
and on EVERY fault file (0.007", 0.014", 0.021") - none of which it saw.

Run from the Indux folder:
    python ml/test_anomaly_cwru.py
Makes: models/cwru_iforest.joblib
       docs/figures/cwru_anomaly_health.png
"""
import os
import sys
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(__file__))
import train_cwru as tc
from test_cwru_severity import TEST_FILES, SIZE

ALL_FILES = {**tc.FILES, **TEST_FILES}


def health_from_score(score, healthy_scores):
    """Map anomaly score to 0-100. 100 = typical healthy, 50 = alarm line."""
    lo = np.percentile(healthy_scores, 1)    # alarm threshold
    mid = np.median(healthy_scores)          # typical healthy
    h = 50 + 50 * (score - lo) / (mid - lo + 1e-12)
    return np.clip(h, 0, 100)


def main():
    tc.FILES = ALL_FILES
    df = tc.build_dataset()
    size = {n: '0.007"' for n in tc.FILES}
    size.update(SIZE)
    df["size"] = [("-" if l == "normal" else size[f]) for l, f in zip(df.label, df.file)]

    cols = tc.SHAPE_FEATURES + ["rms", "env_rms"]
    train = df[(df.label == "normal") & (df.load != 3)]
    test = df.drop(train.index)

    scaler = StandardScaler().fit(np.log1p(train[cols].abs()))
    Xtr = scaler.transform(np.log1p(train[cols].abs()))
    Xte = scaler.transform(np.log1p(test[cols].abs()))

    iso = IsolationForest(n_estimators=300, contamination="auto", random_state=42).fit(Xtr)
    tr_scores = iso.decision_function(Xtr)
    threshold = np.percentile(tr_scores, 1)          # ~1% false alarms by design
    te_scores = iso.decision_function(Xte)
    test = test.assign(score=te_scores, flagged=te_scores < threshold,
                       health=health_from_score(te_scores, tr_scores))

    print("Trained on: healthy only (loads 0-2). Never saw any fault.\n")
    healthy = test[test.label == "normal"]
    print(f"False alarms on unseen healthy (load 3): {healthy.flagged.mean():.3f}  "
          f"({len(healthy)} windows)\n")
    print("Unseen faults flagged as abnormal:")
    faults = test[test.label != "normal"]
    table = faults.groupby(["label", "size"]).flagged.mean().unstack()
    print(table.round(3).to_string())
    print(f"\nOverall fault detection: {faults.flagged.mean():.3f}  ({len(faults)} windows)")
    print("\nAverage health score (100 = healthy, <50 = alarm):")
    print(test.groupby(["label", "size"]).health.mean().round(1).to_string())

    os.makedirs("models", exist_ok=True)
    joblib.dump({"model": iso, "scaler": scaler, "features": cols,
                 "threshold": threshold, "train_scores": tr_scores},
                "models/cwru_iforest.joblib")

    os.makedirs("docs/figures", exist_ok=True)
    groups = [("Healthy (unseen load)", healthy.health)] + \
             [(f"{l} {s}", g.health) for (l, s), g in faults.groupby(["label", "size"])]
    plt.figure(figsize=(9, 4.5))
    plt.boxplot([g for _, g in groups])
    plt.xticks(range(1, len(groups) + 1), [n for n, _ in groups])
    plt.axhline(50, color="r", ls="--", label="Alarm line")
    plt.axhspan(80, 100, color="g", alpha=0.08)
    plt.ylabel("Health score")
    plt.setp(plt.gca().get_xticklabels(), rotation=35, ha="right")
    plt.title("Anomaly detector trained on healthy data only")
    plt.legend()
    plt.tight_layout()
    plt.savefig("docs/figures/cwru_anomaly_health.png", dpi=150)
    print("\nSaved models/cwru_iforest.joblib and docs/figures/cwru_anomaly_health.png")


if __name__ == "__main__":
    main()