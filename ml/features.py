"""Shared feature extraction for Indux.

One function, `extract`, turns one vibration window (plus optional electrical,
thermal and speed readings) into a flat dict of features. The same code serves
the simulator (3.2 kHz), CWRU (12 kHz) and NASA IMS (20.48 kHz), so the sample
rate is always passed in and never assumed.

Missing inputs (CWRU and IMS have no current or temperature) come out as NaN, so
every call returns the same keys.
"""
from __future__ import annotations

from collections import deque

import numpy as np
from scipy import signal, stats

# Bearing defect frequencies as multiples of shaft speed. "bsf" is the ball
# impact rate (2x ball spin), which is what a ball defect shows in the envelope.
SIM_BEARING = {"bpfo": 3.5}
# CWRU drive-end bearing, SKF 6205-2RS JEM (values published by the CWRU bearing data centre).
CWRU_6205_DE = {"bpfo": 3.5848, "bpfi": 5.4152, "bsf": 4.7135, "ftf": 0.3983}
# NASA IMS, Rexnord ZA-2115: 16 rollers, Bd 0.331", Pd 2.815", contact angle 15.17 deg.
IMS_ZA2115 = {"bpfo": 7.0922, "bpfi": 8.9078, "bsf": 8.3954, "ftf": 0.4433}

# Absolute bands in Hz, reported as a fraction of total spectral energy.
BANDS_HZ = (("band_0_250", 0, 250), ("band_250_500", 250, 500), ("band_500_1k", 500, 1000),
            ("band_1k_2k", 1000, 2000), ("band_2k_up", 2000, np.inf))

ELECTRICAL_FEATURES = ("current_mean", "current_std", "power", "temp", "temp_delta", "rpm", "rpm_var_pct")

FEATURE_LABELS = {
    "rms": "Overall vibration level",
    "peak": "Largest vibration spike",
    "p2p": "Vibration peak-to-peak",
    "std": "Vibration spread",
    "kurtosis": "Vibration spikiness (impacts)",
    "skewness": "Vibration asymmetry",
    "crest": "Spike height vs. average (crest factor)",
    "amp_0_5x": "Vibration at half running speed",
    "amp_1x": "Vibration at running speed",
    "amp_2x": "Vibration at twice running speed",
    "amp_3x": "Vibration at 3x running speed",
    "ratio_2x_1x": "2x vs 1x vibration ratio",
    "ratio_3x_1x": "3x vs 1x vibration ratio",
    "band_0_250": "Low-frequency energy (0-250 Hz)",
    "band_250_500": "Energy 250-500 Hz",
    "band_500_1k": "Energy 500-1000 Hz",
    "band_1k_2k": "High-frequency energy (1-2 kHz)",
    "band_2k_up": "Very high-frequency energy (>2 kHz)",
    "spectral_centroid": "Centre of vibration frequency",
    "env_bpfo": "Bearing outer-race fault signal",
    "env_bpfo_snr": "Bearing outer-race fault strength",
    "env_bpfi": "Bearing inner-race fault signal",
    "env_bpfi_snr": "Bearing inner-race fault strength",
    "env_bsf": "Bearing ball fault signal",
    "env_bsf_snr": "Bearing ball fault strength",
    "env_ftf": "Bearing cage fault signal",
    "env_ftf_snr": "Bearing cage fault strength",
    "current_mean": "Motor current",
    "current_std": "Current fluctuation",
    "power": "Electrical power",
    "temp": "Motor temperature",
    "temp_delta": "Temperature change",
    "rpm": "Motor speed",
    "rpm_var_pct": "Speed fluctuation",
}

_EPS = 1e-12
_PAD = 4  # zero-padding factor: keeps Hann scalloping loss around 1%


def amplitude_spectrum(x, fs, pad=_PAD):
    """Single-sided amplitude spectrum: a sine of amplitude A gives a peak of ~A."""
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    w = signal.windows.hann(len(x), sym=False)
    spec = np.fft.rfft(x * w, n=pad * len(x))
    amp = 2.0 * np.abs(spec) / w.sum()
    amp[0] /= 2.0
    freqs = np.fft.rfftfreq(pad * len(x), 1.0 / fs)
    return freqs, amp


def peak_near(freqs, amp, f, tol):
    """Largest amplitude within +/- tol Hz of f (0 if f is outside the spectrum)."""
    if f <= 0 or f - tol >= freqs[-1]:
        return 0.0
    mask = np.abs(freqs - f) <= tol
    return float(amp[mask].max()) if mask.any() else 0.0


def extract(window, fs, rpm, current=None, voltage=None, temp=None, prev_temp=None,
            rpm_history=None, bearing=None, env_band=None) -> dict:
    """Features for one vibration window.

    window      1-D vibration samples (g)
    fs          sample rate in Hz
    rpm         shaft speed for this window
    current     scalar or recent samples/window means (A); std is taken across them
    voltage     supply voltage (V)
    temp        temperature now; prev_temp is an earlier reading for temp_delta
    rpm_history recent rpm readings, for speed fluctuation
    bearing     {"bpfo": ratio, ...} defect frequencies as multiples of shaft speed
    env_band    (lo, hi) Hz band-pass before the envelope; default 25%-90% of Nyquist
    """
    x = np.asarray(window, dtype=float)
    if x.ndim != 1 or len(x) < 64:
        raise ValueError("window must be a 1-D array of at least 64 samples")
    fs = float(fs)
    nyq = fs / 2.0
    f1 = float(rpm) / 60.0
    tol = max(2.0, 1.5 * fs / len(x))  # at least 1.5 real FFT bins, so 12 kHz data still hits a bin
    bearing = SIM_BEARING if bearing is None else bearing
    feats: dict[str, float] = {}

    # ---- time domain (AC part: accelerometers can carry a DC/gravity offset)
    xc = x - x.mean()
    rms = float(np.sqrt(np.mean(xc ** 2)))
    peak = float(np.max(np.abs(xc)))
    feats["rms"] = rms
    feats["peak"] = peak
    feats["p2p"] = float(x.max() - x.min())
    x_std = float(x.std())
    feats["std"] = x_std
    feats["kurtosis"] = float(stats.kurtosis(x, fisher=False)) if x_std > 1e-9 else 3.0
    feats["skewness"] = float(stats.skew(x)) if x_std > 1e-9 else 0.0
    feats["crest"] = peak / (rms + _EPS)

    # ---- frequency domain
    freqs, amp = amplitude_spectrum(x, fs)
    for name, order in (("amp_0_5x", 0.5), ("amp_1x", 1), ("amp_2x", 2), ("amp_3x", 3)):
        feats[name] = peak_near(freqs, amp, order * f1, tol)
    feats["ratio_2x_1x"] = feats["amp_2x"] / (feats["amp_1x"] + _EPS)
    feats["ratio_3x_1x"] = feats["amp_3x"] / (feats["amp_1x"] + _EPS)

    power = amp ** 2
    total = power[1:].sum() + _EPS
    for name, lo, hi in BANDS_HZ:
        feats[name] = float(power[(freqs >= lo) & (freqs < hi)].sum() / total)
    feats["spectral_centroid"] = float((freqs * power).sum() / total)

    # ---- envelope spectrum (bearing faults)
    lo, hi = env_band if env_band is not None else (0.25 * nyq, 0.9 * nyq)
    hi = min(hi, 0.99 * nyq)
    lo = max(1.0, min(lo, hi - 10.0))
    sos = signal.butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
    env = np.abs(signal.hilbert(signal.sosfiltfilt(sos, xc)))
    ef, ea = amplitude_spectrum(env, fs)
    top = 3.0 * max(bearing.values(), default=1.0) * f1
    band_mask = (ef > 1.0) & (ef <= max(top, 10.0))
    floor = float(np.median(ea[band_mask])) if band_mask.any() else (float(np.median(ea)) if len(ea) > 0 else 0.0)
    for name, ratio in bearing.items():
        v = peak_near(ef, ea, ratio * f1, tol)
        feats[f"env_{name}"] = v
        feats[f"env_{name}_snr"] = v / (floor + _EPS)

    # ---- electrical, thermal, speed
    if current is None:
        feats["current_mean"] = feats["current_std"] = np.nan
    else:
        c = np.atleast_1d(np.asarray(current, dtype=float))
        feats["current_mean"] = float(c.mean())
        feats["current_std"] = float(c.std())
    feats["power"] = (float(voltage) * feats["current_mean"]
                      if voltage is not None and current is not None else np.nan)
    feats["temp"] = float(temp) if temp is not None else np.nan
    feats["temp_delta"] = (float(temp) - float(prev_temp)
                           if temp is not None and prev_temp is not None else np.nan)
    feats["rpm"] = float(rpm)
    if rpm_history is not None and len(rpm_history) > 1:
        r = np.asarray(rpm_history, dtype=float)
        feats["rpm_var_pct"] = float(100.0 * r.std() / (r.mean() + _EPS))
    else:
        feats["rpm_var_pct"] = np.nan
    return feats


class StreamFeaturizer:
    """Keeps the short history that `extract` needs for a live stream of contract records.

    current_std, temp_delta and rpm_var_pct are taken over the last `history` windows.
    """

    def __init__(self, history=5, bearing=None, env_band=None):
        self.bearing = bearing
        self.env_band = env_band
        self._rpm = deque(maxlen=history)
        self._current = deque(maxlen=history)
        self._temp = deque(maxlen=history)

    def __call__(self, rec: dict) -> dict:
        self._rpm.append(rec["rpm"])
        if rec.get("current") is not None:
            self._current.append(rec["current"])
        else:
            self._current.clear()

        temp = rec.get("temp")
        prev_temp = self._temp[0] if self._temp else None
        if temp is not None:
            self._temp.append(temp)
        else:
            self._temp.clear()
            prev_temp = None

        return extract(rec["vib"], rec["fs"], rec["rpm"],
                       current=list(self._current) or None, voltage=rec.get("voltage"),
                       temp=temp, prev_temp=prev_temp, rpm_history=list(self._rpm),
                       bearing=self.bearing, env_band=self.env_band)
