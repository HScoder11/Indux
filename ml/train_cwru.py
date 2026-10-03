"""
Indux - CWRU bearing fault classifier (benchmark).

Run from the Indux folder:
    python ml/train_cwru.py

Needs: data/benchmark/cwru/{97..100,105..108,118..121,130..133}.mat
Makes: models/cwru_rf.joblib
       docs/figures/cwru_confusion.png
       docs/figures/cwru_importance.png
"""
import os
import re
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.io import loadmat
from scipy.signal import hilbert, butter, sosfiltfilt
from scipy.stats import kurtosis, skew
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (classification_report, confusion_matrix,
                             ConfusionMatrixDisplay, accuracy_score)

DATA_DIR = "data/benchmark/cwru"
FS = 12000            # 12 kHz drive-end data
WIN = 4096            # ~0.34 s per window, ~2.9 Hz resolution
HOP = 2048            # 50% overlap

# file number -> (condition, load in HP)
# Check these against the CWRU "Normal Baseline" and "12k Drive End" tables.
FILES = {
    97: ("normal", 0), 98: ("normal", 1), 99: ("normal", 2), 100: ("normal", 3),
    105: ("inner", 0), 106: ("inner", 1), 107: ("inner", 2), 108: ("inner", 3),
    118: ("ball", 0),  119: ("ball", 1),  120: ("ball", 2),  121: ("ball", 3),
    130: ("outer", 0), 131: ("outer", 1), 132: ("outer", 2), 133: ("outer", 3),
}
NOMINAL_RPM = {0: 1797, 1: 1772, 2: 1750, 3: 1730}

# Bearing fault frequencies as multiples of shaft speed (CWRU drive-end SKF 6205)
BEARING = {"bpfo": 3.5848, "bpfi": 5.4152, "bsf": 2.3570}


# ---------------------------------------------------------------- features
def _peak_near(freqs, spec, target, tol):
    m = (freqs >= target - tol) & (freqs <= target + tol)
    return float(spec[m].max()) if m.any() else 0.0


def _band_energy(freqs, spec, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    return float(np.sum(spec[m] ** 2)) if m.any() else 0.0


def extract_features(x, fs, rpm):
    """Vibration features for one window. Same function will be used live."""
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    n = len(x)
    f1 = rpm / 60.0

    rms = np.sqrt(np.mean(x ** 2))
    peak = np.max(np.abs(x))
    feats = {
        "rms": rms,
        "peak": peak,
        "p2p": np.ptp(x),
        "std": np.std(x),
        "kurtosis": kurtosis(x),
        "skewness": skew(x),
        "crest": peak / rms if rms > 0 else 0.0,
    }

    # FFT (amplitude spectrum)
    spec = np.abs(np.fft.rfft(x * np.hanning(n))) * 2 / n
    freqs = np.fft.rfftfreq(n, 1 / fs)
    df = fs / n
    tol = max(2.0, 1.5 * df)

    for k in (1, 2, 3):
        feats[f"amp_{k}x"] = _peak_near(freqs, spec, k * f1, tol)
    a1 = feats["amp_1x"] + 1e-12
    feats["ratio_2x_1x"] = feats["amp_2x"] / a1
    feats["ratio_3x_1x"] = feats["amp_3x"] / a1

    nyq = fs / 2
    for lo, hi in [(0, 500), (500, 1000), (1000, 1600), (1600, nyq)]:
        feats[f"band_{lo}_{int(hi) if hi != nyq else 'nyq'}"] = _band_energy(freqs, spec, lo, hi)
    feats["spec_centroid"] = float(np.sum(freqs * spec) / (np.sum(spec) + 1e-12))

    # Envelope spectrum - finds bearing impacts hidden in high frequencies
    hp = min(1000.0, 0.3 * nyq)
    sos = butter(4, hp, btype="highpass", fs=fs, output="sos")
    env = np.abs(hilbert(sosfiltfilt(sos, x)))
    env = env - env.mean()
    env_spec = np.abs(np.fft.rfft(env * np.hanning(n))) * 2 / n
    for name, mult in BEARING.items():
        feats[f"env_{name}"] = _peak_near(freqs, env_spec, mult * f1, tol)
    feats["env_rms"] = float(np.sqrt(np.mean(env ** 2)))

    # Scale-free envelope features: WHICH fault frequency stands out,
    # not how big it is. These carry over to new bearings and fault sizes.
    band = (freqs >= 10) & (freqs <= 500)
    floor = float(np.median(env_spec[band])) + 1e-12
    strength = {}
    for name, mult in BEARING.items():
        s = sum(_peak_near(freqs, env_spec, h * mult * f1, tol) for h in (1, 2))
        strength[name] = s
        feats[f"env_{name}_snr"] = np.log1p(s / floor)
    total = sum(strength.values()) + 1e-12
    for name in BEARING:
        feats[f"env_{name}_share"] = strength[name] / total
    return feats


# Features that do not depend on signal size - use these to generalise
SHAPE_FEATURES = ["kurtosis", "skewness", "crest", "ratio_2x_1x", "ratio_3x_1x",
                  "spec_centroid"] + \
                 [f"env_{n}_snr" for n in BEARING] + [f"env_{n}_share" for n in BEARING]


# ---------------------------------------------------------------- loading
def load_signal(num):
    d = loadmat(os.path.join(DATA_DIR, f"{num}.mat"))
    key = f"X{num:03d}_DE_time"
    if key not in d:  # some CWRU files use odd names
        de_keys = [k for k in d if k.endswith("_DE_time")]
        if not de_keys:
            raise KeyError(f"{num}.mat has no drive-end signal. Keys: {list(d)}")
        key = de_keys[0]
    sig = d[key].ravel()
    rpm_keys = [k for k in d if re.match(r"X\d+RPM", k)]
    rpm = float(d[rpm_keys[0]].ravel()[0]) if rpm_keys else None
    return sig, rpm


def build_dataset():
    rows = []
    missing = []
    for num, (label, load) in FILES.items():
        path = os.path.join(DATA_DIR, f"{num}.mat")
        if not os.path.exists(path):
            missing.append(num)
            continue
        sig, rpm = load_signal(num)
        rpm = rpm or NOMINAL_RPM[load]
        for start in range(0, len(sig) - WIN + 1, HOP):
            f = extract_features(sig[start:start + WIN], FS, rpm)
            f.update(label=label, load=load, file=num)
            rows.append(f)
    if missing:
        print("WARNING - missing files:", missing)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- training
def main():
    os.makedirs("models", exist_ok=True)
    os.makedirs("docs/figures", exist_ok=True)

    df = build_dataset()
    feature_cols = [c for c in df.columns if c not in ("label", "load", "file")]
    print(f"{len(df)} windows, {len(feature_cols)} features")
    print(df.groupby(["label", "load"]).size().unstack(fill_value=0), "\n")

    # Honest test: train on 3 loads, test on the 4th (no window leakage)
    labels = sorted(df.label.unique())
    all_true, all_pred = [], []
    for test_load in sorted(df.load.unique()):
        tr, te = df[df.load != test_load], df[df.load == test_load]
        clf = RandomForestClassifier(n_estimators=300, class_weight="balanced",
                                     random_state=42, n_jobs=-1)
        clf.fit(tr[feature_cols], tr.label)
        pred = clf.predict(te[feature_cols])
        print(f"Test on load {test_load} HP: accuracy = {accuracy_score(te.label, pred):.3f}")
        all_true += list(te.label)
        all_pred += list(pred)

    print("\nLeave-one-load-out, all folds combined:")
    print(classification_report(all_true, all_pred, labels=labels, digits=3))

    cm = confusion_matrix(all_true, all_pred, labels=labels)
    ConfusionMatrixDisplay(cm, display_labels=labels).plot(cmap="Blues", colorbar=False)
    plt.title("CWRU - leave-one-load-out")
    plt.tight_layout()
    plt.savefig("docs/figures/cwru_confusion.png", dpi=150)
    plt.close()

    # Final model on all data
    clf = RandomForestClassifier(n_estimators=300, class_weight="balanced",
                                 random_state=42, n_jobs=-1)
    clf.fit(df[feature_cols], df.label)
    joblib.dump({"model": clf, "features": feature_cols, "fs": FS, "win": WIN},
                "models/cwru_rf.joblib")

    imp = pd.Series(clf.feature_importances_, index=feature_cols).sort_values()
    imp.tail(12).plot.barh(figsize=(7, 5))
    plt.title("Top features - CWRU classifier")
    plt.tight_layout()
    plt.savefig("docs/figures/cwru_importance.png", dpi=150)
    plt.close()

    print("Saved models/cwru_rf.joblib and figures in docs/figures/")


if __name__ == "__main__":
    main()