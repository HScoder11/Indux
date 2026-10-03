"""
Indux - harder CWRU test: train on 0.007" faults, test on NEW damaged
bearings (0.014" and 0.021"). Normal data is split by load so no normal
window is seen in both training and testing.

Run from the Indux folder:
    python ml/test_cwru_severity.py
Makes: docs/figures/cwru_severity_confusion.png
"""
import os
import sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, ConfusionMatrixDisplay

sys.path.insert(0, os.path.dirname(__file__))
import train_cwru as tc

# 0.014" and 0.021" drive-end faults, 12 kHz, outer race @6:00.
# Check these numbers against the CWRU "12k Drive End Bearing Fault Data" table.
TEST_FILES = {
    169: ("inner", 0), 170: ("inner", 1), 171: ("inner", 2), 172: ("inner", 3),
    185: ("ball", 0),  186: ("ball", 1),  187: ("ball", 2),  188: ("ball", 3),
    197: ("outer", 0), 198: ("outer", 1), 199: ("outer", 2), 200: ("outer", 3),
    209: ("inner", 0), 210: ("inner", 1), 211: ("inner", 2), 212: ("inner", 3),
    222: ("ball", 0),  223: ("ball", 1),  224: ("ball", 2),  225: ("ball", 3),
    234: ("outer", 0), 235: ("outer", 1), 236: ("outer", 2), 237: ("outer", 3),
}
SIZE = {n: ('0.014"' if n < 205 else '0.021"') for n in TEST_FILES}


def main():
    train_df = tc.build_dataset()                 # normal + 0.007" faults
    tc.FILES = TEST_FILES
    test_df = tc.build_dataset()                  # 0.014" + 0.021" faults
    if test_df.empty:
        print("No test files found. Download the numbers in TEST_FILES first.")
        return
    test_df["size"] = test_df.file.map(SIZE)

    # Normal: loads 0-2 for training, load 3 held out for testing
    normal = train_df[train_df.label == "normal"]
    train = pd.concat([train_df[train_df.label != "normal"], normal[normal.load != 3]])
    test = pd.concat([test_df, normal[normal.load == 3].assign(size="-")])

    all_cols = [c for c in train.columns if c not in ("label", "load", "file", "size")]
    labels = sorted(train.label.unique())
    print("Train: 0.007\" faults + normal loads 0-2")
    print("Test : 0.014\" and 0.021\" faults (new bearings) + normal load 3")

    results = {}
    # Physics rule: ML decides healthy vs faulty; the strongest bearing
    # frequency in the envelope decides WHICH fault.
    RULE = {"bpfi": "inner", "bpfo": "outer", "bsf": "ball"}
    snr_cols = [f"env_{n}_snr" for n in RULE]

    methods = [("All features", all_cols), ("Shape-only features", tc.SHAPE_FEATURES),
               ("ML detect + physics rule", all_cols)]
    for name, cols in methods:
        clf = RandomForestClassifier(n_estimators=300, class_weight="balanced",
                                     random_state=42, n_jobs=-1)
        clf.fit(train[cols], train.label)
        pred = clf.predict(test[cols])
        if name.startswith("ML detect"):
            strongest = test[snr_cols].values.argmax(axis=1)
            fault_type = [RULE[snr_cols[i][4:-4]] for i in strongest]
            pred = [p if p == "normal" else ft for p, ft in zip(pred, fault_type)]
        pred = pd.Series(pred, index=test.index).values
        results[name] = pred
        print(f"\n==================== {name} ({len(cols)}) ====================")
        print(classification_report(test.label, pred, labels=labels, digits=3, zero_division=0))
        t = test.assign(pred=pred)
        print("Accuracy by fault size:")
        for size, g in t.groupby("size"):
            print(f"  {size:8s} {(g.label == g.pred).mean():.3f}  ({len(g)} windows)")
        faults = t[t.label != "normal"]
        print(f"Fault DETECTED (any fault vs healthy): {(faults.pred != 'normal').mean():.3f}")
        print(f"False alarms on healthy:               {(t[t.label == 'normal'].pred != 'normal').mean():.3f}")

    os.makedirs("docs/figures", exist_ok=True)
    best = max(results, key=lambda k: (results[k] == test.label.values).mean())
    cm = confusion_matrix(test.label, results[best], labels=labels)
    ConfusionMatrixDisplay(cm, display_labels=labels).plot(cmap="Blues", colorbar=False)
    plt.title(f'Unseen fault sizes - {best}')
    plt.tight_layout()
    plt.savefig("docs/figures/cwru_severity_confusion.png", dpi=150)
    print(f"\nSaved docs/figures/cwru_severity_confusion.png ({best})")

if __name__ == "__main__":
    main()