"""
Indux - AI4I 2020 benchmark (milling machine, tabular sensor data).

Run from the Indux folder:
    python ml/train_ai4i.py
Needs: data/benchmark/ai4i/ai4i2020.csv
Makes: models/ai4i_rf.joblib
       docs/figures/ai4i_confusion.png
       docs/figures/ai4i_shap.png   (or ai4i_importance.png if shap is missing)
"""
import os
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.inspection import permutation_importance
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay

CSV = "data/benchmark/ai4i/ai4i2020.csv"

# Failure modes in the dataset. RNF (random failure, 0.1%) is pure noise
# by design, so it is left out - no model can predict it.
MODES = {"HDF": "Heat dissipation", "PWF": "Power", "OSF": "Overstrain", "TWF": "Tool wear"}


def load():
    df = pd.read_csv(CSV)
    df = df.rename(columns={
        "Air temperature [K]": "air_temp", "Process temperature [K]": "proc_temp",
        "Rotational speed [rpm]": "rpm", "Torque [Nm]": "torque",
        "Tool wear [min]": "tool_wear",
    })
    # One label per row: first failure mode that is set, else "No failure"
    df["label"] = "No failure"
    for code in reversed(list(MODES)):
        df.loc[df[code] == 1, "label"] = MODES[code]

    # Physics-based features (same idea as the motor: power, heat, strain)
    df["type_code"] = df["Type"].map({"L": 0, "M": 1, "H": 2})
    df["temp_diff"] = df.proc_temp - df.air_temp
    df["power_w"] = df.torque * df.rpm * 2 * np.pi / 60
    df["strain"] = df.torque * df.tool_wear
    return df


RAW = ["type_code", "air_temp", "proc_temp", "rpm", "torque", "tool_wear"]
ENGINEERED = RAW + ["temp_diff", "power_w", "strain"]
NAMES = {  # plain words for the dashboard and slides
    "type_code": "Product quality", "air_temp": "Air temperature",
    "proc_temp": "Process temperature", "rpm": "Speed", "torque": "Torque",
    "tool_wear": "Tool wear", "temp_diff": "Heat gap (process - air)",
    "power_w": "Power", "strain": "Strain (torque x wear)",
}


def main():
    os.makedirs("models", exist_ok=True)
    os.makedirs("docs/figures", exist_ok=True)
    df = load()
    print(f"{len(df)} rows")
    print(df.label.value_counts(), "\n")

    train, test = train_test_split(df, test_size=0.25, stratify=df.label, random_state=42)
    labels = ["No failure"] + list(MODES.values())

    models = {}
    for name, cols in [("Raw sensors only", RAW), ("Raw + physics features", ENGINEERED)]:
        clf = RandomForestClassifier(n_estimators=400, class_weight="balanced_subsample",
                                     min_samples_leaf=2, random_state=42, n_jobs=-1)
        clf.fit(train[cols], train.label)
        pred = clf.predict(test[cols])
        models[name] = (clf, cols, pred)
        print(f"==================== {name} ====================")
        print(classification_report(test.label, pred, labels=labels, digits=3, zero_division=0))
        is_fail, said_fail = test.label != "No failure", pred != "No failure"
        print(f"Failure DETECTED (any type): {(said_fail & is_fail).sum() / is_fail.sum():.3f}")
        print(f"False alarms on healthy rows: {(said_fail & ~is_fail).sum() / (~is_fail).sum():.4f}\n")

    clf, cols, pred = models["Raw + physics features"]
    joblib.dump({"model": clf, "features": cols, "names": NAMES}, "models/ai4i_rf.joblib")

    cm = confusion_matrix(test.label, pred, labels=labels)
    ConfusionMatrixDisplay(cm, display_labels=labels).plot(cmap="Blues", colorbar=False,
                                                            xticks_rotation=30)
    plt.title("AI4I 2020 - test set")
    plt.tight_layout()
    plt.savefig("docs/figures/ai4i_confusion.png", dpi=150)
    plt.close()

    # Explanations: SHAP if installed, otherwise permutation importance
    try:
        import shap
        fails = test[test.label != "No failure"][cols]
        sv = shap.TreeExplainer(clf).shap_values(fails)
        sv = np.array(sv)
        # mean |SHAP| over rows and classes -> one bar per feature
        axes = tuple(i for i in range(sv.ndim) if sv.shape[i] != len(cols))
        imp = pd.Series(np.abs(sv).mean(axis=axes), index=[NAMES[c] for c in cols])
        out, title = "docs/figures/ai4i_shap.png", "What drives failure predictions (mean |SHAP|)"
    except ImportError:
        r = permutation_importance(clf, test[cols], test.label, n_repeats=5, random_state=42)
        imp = pd.Series(r.importances_mean, index=[NAMES[c] for c in cols])
        out, title = "docs/figures/ai4i_importance.png", "Feature importance (permutation)"
    imp.sort_values().plot.barh(figsize=(7, 4.5))
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    print(f"Saved models/ai4i_rf.joblib, docs/figures/ai4i_confusion.png, {out}")


if __name__ == "__main__":
    main()