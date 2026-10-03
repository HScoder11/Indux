"""Indux live predictor - one contract record in, one dashboard message out.

The backend only needs:

    from ml.live import LivePredictor
    predictor = LivePredictor()              # loads models/live_models.joblib
    msg = predictor.update(record)           # record = one data-contract dict
    # send msg over the WebSocket

Three models run on every window:
  1. Fault classifier   - trained offline on simulator data (which fault?)
  2. Anomaly detector   - learns THIS motor's normal during the first ~25 s,
                          then scores how far each window is from it
                          (catches problems the classifier never saw)
  3. Health score 0-100 - from the anomaly distance, smoothed, with a
                          time-to-critical trend

Works the same for the simulator, replayed CSVs and (later) the ESP32,
because they all speak the same data contract.
"""
from __future__ import annotations

from collections import Counter, deque
from pathlib import Path

import joblib
import numpy as np

from ml.features import FEATURE_LABELS, StreamFeaturizer, amplitude_spectrum

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "live_models.joblib"

CALIB_WINDOWS = 40            # ~26 s of healthy running to learn "normal"
RECALIB_RPM_CHANGE = 0.10     # speed change >10% -> learn normal again
TOP_K = 3                     # anomaly distance = RMS of the 3 largest z-scores
HEALTH_SMOOTH = 10            # windows (~6 s) in the health moving average
ALERT_NEED, ALERT_OF = 3, 5   # alert when 3 of the last 5 windows are abnormal
AGREE_HEALTH = 80             # a named fault only counts if health is also below this...
CALIB_MIN_CONF = 0.7          # ...or, while still learning normal, if the classifier is this sure
TTF_LOOKBACK = 30             # windows (~19 s) used for the health trend
FFT_MAX_HZ, FFT_BARS = 1600, 160
PRETTY = {"healthy": "Healthy", "unbalance": "Unbalance", "looseness": "Looseness",
          "bearing": "Bearing fault", "overload": "Overload", "anomaly": "Unknown anomaly"}


class LivePredictor:
    def __init__(self, model_path=MODEL_PATH):
        b = joblib.load(model_path)
        self.clf = b["classifier"]
        self.features = b["features"]
        self.fill = b["fill_values"]
        self.explain = b["explain_features"]
        self.z_features = [k for k in self.features if k != "rpm"]
        self.d_healthy = b["distance_healthy"]     # typical healthy distance
        self.d_alarm = b["distance_alarm"]         # distance that maps to health 50
        self.reset()

    def reset(self):
        """Call when the data source changes (sim -> replay -> ESP32)."""
        self.featurize = StreamFeaturizer()
        self.calib = []
        self.base = None                            # (median, scale, rpm)
        self.health_hist = deque(maxlen=HEALTH_SMOOTH)
        self.trend = deque(maxlen=TTF_LOOKBACK)
        self.recent = deque(maxlen=ALERT_OF)

    # ------------------------------------------------------------------ helpers
    def _clean(self, f):
        return {k: (f[k] if np.isfinite(f[k]) else self.fill[k]) for k in self.features}

    def _learn_baseline(self):
        rows = np.array([[c[k] for k in self.z_features] for c in self.calib])
        med = np.median(rows, axis=0)
        mad = 1.4826 * np.median(np.abs(rows - med), axis=0)
        # floor: 2% of the level, so a very steady signal can't cause huge z-scores
        scale = np.maximum.reduce([mad, 0.02 * np.abs(med), np.full_like(med, 1e-6)])
        rpm = float(np.median([c["rpm"] for c in self.calib]))
        self.base = (dict(zip(self.z_features, med)), dict(zip(self.z_features, scale)), rpm)

    def _z(self, f):
        med, scale, _ = self.base
        return {k: float(np.clip((f[k] - med[k]) / scale[k], -50, 50)) for k in self.z_features}

    def _distance(self, z):
        top = np.sort(np.abs(list(z.values())))[-TOP_K:]
        return float(np.sqrt(np.mean(top ** 2)))

    def _health(self, d):
        h = 100 - 50 * (d - self.d_healthy) / (self.d_alarm - self.d_healthy)
        return float(np.clip(h, 0, 100))

    def _reasons(self, f, z, n=3):
        if z is None:
            return []
        med = self.base[0]
        keys = [k for k in self.explain if k in z]
        top = sorted(keys, key=lambda k: -abs(z[k]))[:n]
        return [{"feature": k, "label": FEATURE_LABELS.get(k, k),
                 "value": round(float(f[k]), 4), "normal": round(float(med[k]), 4),
                 "z": round(z[k], 1), "direction": "higher" if z[k] > 0 else "lower"}
                for k in top]

    def _fft_bars(self, rec):
        freqs, amp = amplitude_spectrum(np.asarray(rec["vib"], float), rec["fs"])
        edges = np.linspace(0, FFT_MAX_HZ, FFT_BARS + 1)
        idx = np.digitize(freqs, edges) - 1
        bars = np.zeros(FFT_BARS)
        ok = (idx >= 0) & (idx < FFT_BARS)
        np.maximum.at(bars, idx[ok], amp[ok])
        f1 = rec["rpm"] / 60.0
        return {"hz": [round(float(e), 1) for e in edges[:-1]],
                "amp": [round(float(a), 5) for a in bars],
                "markers": {"1x": round(f1, 1), "2x": round(2 * f1, 1), "3x": round(3 * f1, 1)}}

    def _ttf(self):
        if len(self.trend) < TTF_LOOKBACK:
            return None
        t = np.array([p[0] for p in self.trend])
        h = np.array([p[1] for p in self.trend])
        slope = np.polyfit(t - t[0], h, 1)[0]          # health points per second
        if slope >= -0.05 or h[-1] >= 80:
            return None
        return round(float(h[-1] / -slope), 1)          # rough seconds until health hits 0

    # ------------------------------------------------------------------ main
    def update(self, rec: dict) -> dict:
        f = self._clean(self.featurize(rec))

        # Model 1: which fault?
        probs = self.clf.predict_proba(np.array([[f[k] for k in self.features]]))[0]
        classes = list(self.clf.classes_)
        cond = classes[int(np.argmax(probs))]
        conf = float(np.max(probs))

        # Relearn normal if the operator changed speed a lot
        if self.base and abs(f["rpm"] - self.base[2]) / self.base[2] > RECALIB_RPM_CHANGE:
            self.calib, self.base = [], None
            self.health_hist.clear()
            self.trend.clear()

        # Models 2 + 3: distance from this motor's normal -> health
        z, health, h_raw = None, None, None
        if self.base is None:
            self.calib.append(f)
            if len(self.calib) >= CALIB_WINDOWS:
                self._learn_baseline()
        else:
            z = self._z(f)
            h_raw = self._health(self._distance(z))
            self.health_hist.append(h_raw)
            health = float(np.mean(self.health_hist))
            self.trend.append((rec["ts"], health))
            if cond == "healthy" and h_raw < 50:        # classifier missed it
                cond, conf = "anomaly", 1.0 - h_raw / 50.0

        # Both models must agree before a window counts as a fault: a named fault
        # from the classifier alone (motor still close to its learned normal) is
        # treated as healthy. This removes one-off false alarms on unusual motors.
        if cond not in ("healthy", "anomaly"):
            weak = (h_raw is not None and h_raw >= AGREE_HEALTH) or \
                   (h_raw is None and conf < CALIB_MIN_CONF)
            if weak:
                cond = "healthy"
                conf = float(probs[classes.index("healthy")]) if "healthy" in classes else 1.0 - conf

        self.recent.append(cond)
        abnormal = [c for c in self.recent if c != "healthy"]
        alert = len(abnormal) >= ALERT_NEED
        alert_cond = Counter(abnormal).most_common(1)[0][0] if alert else None

        if health is None:
            zone = "calibrating"
        else:
            zone = "green" if health >= 80 else "yellow" if health >= 50 else "red"
        return {
            "ts": rec["ts"],
            "source": rec.get("source", "?"),
            "rpm": rec["rpm"],
            "current": rec.get("current"),
            "voltage": rec.get("voltage"),
            "temp": rec.get("temp"),
            "vib_rms": round(f["rms"], 5),
            "fft": self._fft_bars(rec),
            "condition": cond,
            "condition_label": PRETTY.get(cond, cond),
            "confidence": round(conf, 3),
            "probs": {c: round(float(p), 3) for c, p in zip(classes, probs)},
            "calibrating": health is None,
            "calib_progress": min(1.0, len(self.calib) / CALIB_WINDOWS) if health is None else 1.0,
            "health": None if health is None else round(health, 1),
            "health_raw": None if h_raw is None else round(h_raw, 1),
            "zone": zone,
            "reasons": self._reasons(f, z),
            "alert": alert,
            "alert_condition": alert_cond,
            "alert_label": PRETTY.get(alert_cond) if alert_cond else None,
            "ttf_s": self._ttf(),
        }