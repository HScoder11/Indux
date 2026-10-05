"""
Indux - AI4I 2020 benchmark (milling machine, tabular sensor data).

Run from the Indux folder:
    python ml/train_ai4i.py                    # 60/20/20 split, threshold by F2, 5 repeat splits
    python ml/train_ai4i.py --cost-fn 20       # also report the cost-optimal threshold (miss = 20 alarms)
Needs: data/benchmark/ai4i/ai4i2020.csv        (python download_data.py --only ai4i)
Makes: models/ai4i_rf.joblib                   (model + chosen threshold)
       docs/figures/ai4i_confusion.png         test set, with the chosen threshold
       docs/figures/ai4i_pr_curve.png          precision-recall vs the no-skill baseline, PR-AUC, ROC-AUC
       docs/figures/ai4i_threshold.png         how the threshold was chosen (validation set only)
       docs/figures/ai4i_shap.png              (or ai4i_importance.png if shap is missing)
       docs/figures/ai4i_metrics.json          every number quoted in the README / dashboard

Why it is evaluated this way (see docs/design_decisions.md):
  * Only 3.4% of rows are failures, so accuracy is meaningless: predicting "no failure" for
    every row scores 96.6%. We report precision, recall, F2, PR-AUC and ROC-AUC instead.
  * The decision threshold is a design choice, so it is tuned on a VALIDATION split and then
    applied once to an untouched TEST split. Tuning on the test set would overstate results.
  * The threshold maximises F2 (recall weighted 2x precision): a missed failure costs far more
    than a false alarm. A cost-based threshold is reported alongside for comparison.
"""
import argparse
import json
import os

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.inspection import permutation_importance  # noqa: E402
from sklearn.metrics import (ConfusionMatrixDisplay, average_precision_score, confusion_matrix,  # noqa: E402
                             precision_recall_curve, roc_auc_score)
from sklearn.model_selection import train_test_split  # noqa: E402

CSV = "data/benchmark/ai4i/ai4i2020.csv"
FIG = "docs/figures"

# Failure modes in the dataset. RNF (random failure, 0.1%) is pure noise
# by design, so it is left out - no model can predict it.
MODES = {"HDF": "Heat dissipation", "PWF": "Power", "OSF": "Overstrain", "TWF": "Tool wear"}
NO = "No failure"
BETA = 2.0          # F-beta: recall counts BETA times as much as precision


def load():
    df = pd.read_csv(CSV)
    df = df.rename(columns={
        "Air temperature [K]": "air_temp", "Process temperature [K]": "proc_temp",
        "Rotational speed [rpm]": "rpm", "Torque [Nm]": "torque",
        "Tool wear [min]": "tool_wear",
    })
    # One label per row: first failure mode that is set, else "No failure"
    df["label"] = NO
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


# ------------------------------------------------------------------ helpers
def split(df, seed):
    """60 / 20 / 20, stratified by failure type so every split has every type."""
    train, rest = train_test_split(df, test_size=0.4, stratify=df.label, random_state=seed)
    val, test = train_test_split(rest, test_size=0.5, stratify=rest.label, random_state=seed)
    return train, val, test


def fit(train, cols, seed):
    clf = RandomForestClassifier(n_estimators=400, class_weight="balanced_subsample",
                                 min_samples_leaf=2, random_state=seed, n_jobs=-1)
    return clf.fit(train[cols], train.label)


def p_fail(clf, X):
    """Probability of ANY failure = 1 - P(no failure)."""
    proba = clf.predict_proba(X)
    return 1.0 - proba[:, list(clf.classes_).index(NO)], proba


def fbeta(prec, rec, beta=BETA):
    b2 = beta * beta
    return np.where(prec + rec > 0, (1 + b2) * prec * rec / np.maximum(b2 * prec + rec, 1e-12), 0.0)


def sweep(y, score, cost_fn, cost_fp):
    """Precision, recall, F2 and expected cost for every candidate threshold."""
    ts = np.round(np.arange(0.02, 0.99, 0.01), 2)
    rows = []
    for t in ts:
        pred = score >= t
        tp = int((pred & y).sum()); fp = int((pred & ~y).sum()); fn = int((~pred & y).sum())
        prec = tp / (tp + fp) if tp + fp else 1.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        rows.append({"t": float(t), "precision": prec, "recall": rec,
                     "f2": float(fbeta(np.array(prec), np.array(rec))),
                     "cost": (fn * cost_fn + fp * cost_fp) / len(y)})
    return pd.DataFrame(rows)


def binary_report(y, pred):
    tp = int((pred & y).sum()); fp = int((pred & ~y).sum())
    fn = int((~pred & y).sum()); tn = int((~pred & ~y).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(prec, 4), "recall": round(rec, 4),
            "f2": round(float(fbeta(np.array(prec), np.array(rec))), 4),
            "false_alarm_rate": round(fp / (fp + tn), 5) if fp + tn else 0.0}


def typed_prediction(clf, proba, score, t):
    """Flag a failure when P(any failure) >= t, then name the most likely failure type."""
    classes = list(clf.classes_)
    fail_idx = [i for i, c in enumerate(classes) if c != NO]
    best = np.array(classes)[fail_idx][np.argmax(proba[:, fail_idx], axis=1)]
    return np.where(score >= t, best, NO)


def evaluate(df, cols, seed, cost_fn, cost_fp):
    train, val, test = split(df, seed)
    clf = fit(train, cols, seed)
    yv = (val.label != NO).values
    sv, _ = p_fail(clf, val[cols])
    curve = sweep(yv, sv, cost_fn, cost_fp)
    t_f2 = float(curve.loc[curve.f2.idxmax(), "t"])
    t_cost = float(curve.loc[curve.cost.idxmin(), "t"])

    yt = (test.label != NO).values
    st, proba = p_fail(clf, test[cols])
    default_pred = clf.predict(test[cols]) != NO           # the usual argmax rule, for comparison
    res = {
        "seed": seed, "threshold_f2": t_f2, "threshold_cost": t_cost,
        "test_prevalence": round(float(yt.mean()), 4),
        "pr_auc": round(float(average_precision_score(yt, st)), 4),
        "roc_auc": round(float(roc_auc_score(yt, st)), 4),
        "at_f2_threshold": binary_report(yt, st >= t_f2),
        "at_cost_threshold": binary_report(yt, st >= t_cost),
        "default_argmax_rule": binary_report(yt, default_pred),
        "accuracy_always_no_failure": round(float((~yt).mean()), 4),
    }
    return res, (clf, train, val, test, curve, st, proba, t_f2, t_cost)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--repeats", type=int, default=5, help="extra random splits to show the spread")
    ap.add_argument("--cost-fn", type=float, default=10.0, help="cost of a missed failure (in false alarms)")
    ap.add_argument("--cost-fp", type=float, default=1.0, help="cost of a false alarm")
    args = ap.parse_args()

    os.makedirs("models", exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    df = load()
    print(f"{len(df)} rows, {100 * (df.label != NO).mean():.2f}% failures (RNF excluded as unpredictable)")
    print(df.label.value_counts().to_string(), "\n")

    metrics = {"split": "60/20/20 train/validation/test, stratified by failure type",
               "threshold_rule": f"maximise F{BETA:g} on validation, applied once to test",
               "cost_assumption": {"missed_failure": args.cost_fn, "false_alarm": args.cost_fp},
               "models": {}}
    keep = {}
    for name, cols in [("Raw sensors only", RAW), ("Raw + physics features", ENGINEERED)]:
        res, extra = evaluate(df, cols, args.seed, args.cost_fn, args.cost_fp)
        keep[name] = extra
        # stability: the same procedure on other random splits
        reps = [evaluate(df, cols, args.seed + k, args.cost_fn, args.cost_fp)[0] for k in range(1, args.repeats + 1)]
        allr = [res] + reps
        spread = {k: {"mean": round(float(np.mean(v)), 4), "sd": round(float(np.std(v)), 4)} for k, v in {
            "pr_auc": [r["pr_auc"] for r in allr], "roc_auc": [r["roc_auc"] for r in allr],
            "recall_at_f2": [r["at_f2_threshold"]["recall"] for r in allr],
            "precision_at_f2": [r["at_f2_threshold"]["precision"] for r in allr]}.items()}
        res["over_splits"] = {"n_splits": len(allr), **spread}
        metrics["models"][name] = res

        a, d = res["at_f2_threshold"], res["default_argmax_rule"]
        print(f"==================== {name} ====================")
        print(f"  PR-AUC {res['pr_auc']:.3f}  (no-skill baseline = prevalence {res['test_prevalence']:.3f})"
              f"   ROC-AUC {res['roc_auc']:.3f}")
        print(f"  Threshold chosen on validation by F2: {res['threshold_f2']:.2f}")
        print(f"  TEST at that threshold:  recall {a['recall']:.3f}  precision {a['precision']:.3f}  "
              f"F2 {a['f2']:.3f}  false alarms {100 * a['false_alarm_rate']:.2f}% of healthy rows")
        print(f"  TEST with default rule:  recall {d['recall']:.3f}  precision {d['precision']:.3f}  F2 {d['f2']:.3f}")
        c = res["at_cost_threshold"]
        print(f"  Cost-optimal threshold ({args.cost_fn:g}:{args.cost_fp:g}): {res['threshold_cost']:.2f} -> "
              f"recall {c['recall']:.3f}, precision {c['precision']:.3f}")
        o = res["over_splits"]
        print(f"  Over {o['n_splits']} random splits: PR-AUC {o['pr_auc']['mean']:.3f} +/- {o['pr_auc']['sd']:.3f}, "
              f"recall {o['recall_at_f2']['mean']:.3f} +/- {o['recall_at_f2']['sd']:.3f}")
        print(f"  (Accuracy of always saying 'no failure': {100 * res['accuracy_always_no_failure']:.1f}% - why accuracy is not used)\n")

    # ---------------- the deployed model: raw + physics features, with its threshold
    clf, train, val, test, curve, st, proba, t_f2, t_cost = keep["Raw + physics features"]
    joblib.dump({"model": clf, "features": ENGINEERED, "names": NAMES, "threshold": t_f2,
                 "threshold_rule": metrics["threshold_rule"]}, "models/ai4i_rf.joblib")

    # per-type results on the test set with the chosen threshold
    labels = [NO] + list(MODES.values())
    pred = typed_prediction(clf, proba, st, t_f2)
    per_type = {}
    for lab in MODES.values():
        m = test.label.values == lab
        per_type[lab] = {"n": int(m.sum()),
                         "detected": round(float((pred[m] != NO).mean()), 3) if m.any() else None,
                         "detected_and_named": round(float((pred[m] == lab).mean()), 3) if m.any() else None}
    metrics["per_type_test"] = per_type
    print("Per failure type on TEST (detected = flagged as any failure; named = right type):")
    for lab, r in per_type.items():
        print(f"  {lab:18s} n={r['n']:3d}  detected {r['detected']:.2f}  named {r['detected_and_named']:.2f}")

    cm = confusion_matrix(test.label, pred, labels=labels)
    ConfusionMatrixDisplay(cm, display_labels=labels).plot(cmap="Blues", colorbar=False, xticks_rotation=30)
    plt.title(f"AI4I 2020 - test set (threshold {t_f2:.2f}, chosen on validation)")
    plt.tight_layout(); plt.savefig(f"{FIG}/ai4i_confusion.png", dpi=150); plt.close()

    # ---------------- precision-recall curve vs no-skill baseline (test set)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.6))
    for name, color in (("Raw sensors only", "#9aa0a6"), ("Raw + physics features", "#2a78d6")):
        c_clf, c_test = keep[name][0], keep[name][3]
        cols = RAW if name == "Raw sensors only" else ENGINEERED
        y = (c_test.label != NO).values
        s, _ = p_fail(c_clf, c_test[cols])
        p, r, _ = precision_recall_curve(y, s)
        ax[0].plot(r, p, color=color, lw=2,
                   label=f"{name}: PR-AUC {metrics['models'][name]['pr_auc']:.3f}, ROC-AUC {metrics['models'][name]['roc_auc']:.3f}")
    prev = metrics["models"]["Raw + physics features"]["test_prevalence"]
    ax[0].axhline(prev, color="#d03b3b", ls="--", lw=1.2, label=f"No-skill baseline ({prev:.3f})")
    op = metrics["models"]["Raw + physics features"]["at_f2_threshold"]
    ax[0].plot(op["recall"], op["precision"], "o", color="#0b0b0b", ms=8,
               label=f"Chosen operating point (t={t_f2:.2f})")
    ax[0].set_xlabel("Recall (failures caught)"); ax[0].set_ylabel("Precision (alarms that were real)")
    ax[0].set_ylim(0, 1.03); ax[0].set_xlim(0, 1.0); ax[0].legend(fontsize=8, loc="lower left")
    ax[0].set_title("Test set: precision-recall")

    # ---------------- how the threshold was chosen (validation only)
    ax[1].plot(curve.t, curve.precision, label="Precision", color="#9aa0a6")
    ax[1].plot(curve.t, curve.recall, label="Recall", color="#2a78d6")
    ax[1].plot(curve.t, curve.f2, label="F2 (recall x2)", color="#0b0b0b", lw=2)
    ax[1].axvline(t_f2, color="#0b0b0b", ls=":", lw=1)
    ax[1].text(t_f2 + 0.01, 0.05, f"chosen t={t_f2:.2f}", fontsize=8)
    ax2 = ax[1].twinx()
    ax2.plot(curve.t, curve.cost, color="#e29a00", ls="--", lw=1.2, label=f"Expected cost ({args.cost_fn:g}:{args.cost_fp:g})")
    ax2.set_ylabel("Expected cost per row", color="#e29a00")
    ax[1].set_xlabel("Threshold on P(any failure)"); ax[1].set_ylim(0, 1.03)
    ax[1].set_title("Validation set: choosing the threshold")
    h1, l1 = ax[1].get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax[1].legend(h1 + h2, l1 + l2, fontsize=8, loc="center right")
    fig.tight_layout(); fig.savefig(f"{FIG}/ai4i_pr_curve.png", dpi=150); plt.close(fig)

    fig, axx = plt.subplots(figsize=(6.5, 4))
    axx.plot(curve.t, curve.f2, color="#0b0b0b", lw=2, label="F2")
    axx.plot(curve.t, curve.recall, color="#2a78d6", label="Recall")
    axx.plot(curve.t, curve.precision, color="#9aa0a6", label="Precision")
    axx.axvline(t_f2, ls=":", color="#0b0b0b"); axx.set_xlabel("Threshold"); axx.legend()
    axx.set_title("Validation: threshold sweep (F2 picks the operating point)")
    fig.tight_layout(); fig.savefig(f"{FIG}/ai4i_threshold.png", dpi=150); plt.close(fig)

    # ---------------- explanations: SHAP if installed, otherwise permutation importance
    cols = ENGINEERED
    try:
        import shap
        fails = test[test.label != NO][cols]
        sv = np.array(shap.TreeExplainer(clf).shap_values(fails))
        axes = tuple(i for i in range(sv.ndim) if sv.shape[i] != len(cols))
        imp = pd.Series(np.abs(sv).mean(axis=axes), index=[NAMES[c] for c in cols])
        out, title = f"{FIG}/ai4i_shap.png", "What drives failure predictions (mean |SHAP|)"
    except ImportError:
        r = permutation_importance(clf, test[cols], test.label, n_repeats=5, random_state=42)
        imp = pd.Series(r.importances_mean, index=[NAMES[c] for c in cols])
        out, title = f"{FIG}/ai4i_importance.png", "Feature importance (permutation)"
    imp.sort_values().plot.barh(figsize=(7, 4.5))
    plt.title(title); plt.tight_layout(); plt.savefig(out, dpi=150); plt.close()

    with open(f"{FIG}/ai4i_metrics.json", "w") as f:
        json.dump(metrics, f, indent=1)
    print(f"\nSaved models/ai4i_rf.joblib, {FIG}/ai4i_confusion.png, ai4i_pr_curve.png, "
          f"ai4i_threshold.png, ai4i_metrics.json, {os.path.basename(out)}")


if __name__ == "__main__":
    main()
