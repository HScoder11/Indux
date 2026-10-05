import numpy as np
import pytest

from ml.features import FEATURE_LABELS, StreamFeaturizer, extract


def sine(freq, fs, n=2048, amp=1.0, phase=0.3):
    t = np.arange(n) / fs
    return amp * np.sin(2 * np.pi * freq * t + phase)


@pytest.mark.parametrize("fs", [3200, 12000, 20480])
@pytest.mark.parametrize("freq", [50.0, 50.37])  # on-bin-ish and deliberately off-bin
def test_pure_sine_1x_amplitude(fs, freq):
    f = extract(sine(freq, fs), fs, rpm=freq * 60)
    assert f["amp_1x"] == pytest.approx(1.0, rel=0.02)
    assert f["amp_2x"] < 0.01 and f["amp_3x"] < 0.01
    assert f["rms"] == pytest.approx(1 / np.sqrt(2), rel=0.01)
    assert f["crest"] == pytest.approx(np.sqrt(2), rel=0.05)  # 12 kHz window holds only ~8.5 cycles
    assert f["kurtosis"] == pytest.approx(1.5, abs=0.05)


def test_harmonic_ratios():
    fs, f1 = 3200, 83.3
    x = sine(f1, fs, amp=1.0) + sine(2 * f1, fs, amp=0.5) + sine(3 * f1, fs, amp=0.25)
    f = extract(x, fs, rpm=f1 * 60)
    assert f["ratio_2x_1x"] == pytest.approx(0.5, rel=0.03)
    assert f["ratio_3x_1x"] == pytest.approx(0.25, rel=0.03)


def test_dc_offset_ignored():
    fs = 3200
    a = extract(sine(50, fs), fs, rpm=3000)
    b = extract(sine(50, fs) + 1.0, fs, rpm=3000)  # 1 g gravity offset
    for k in ("rms", "peak", "amp_1x", "crest"):
        assert b[k] == pytest.approx(a[k], rel=1e-6)


def test_envelope_finds_bearing_impacts():
    fs, rpm = 3200, 3000
    f1, bpfo = rpm / 60, 3.5 * rpm / 60
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.05, 2048)
    t = np.arange(2048) / fs
    impacts = np.zeros(2048)
    for tk in np.arange(0.001, t[-1], 1 / bpfo):
        local = t - tk
        m = local >= 0
        impacts[m] += 0.5 * np.exp(-local[m] / 0.0006) * np.sin(2 * np.pi * 1000 * local[m])
    healthy = extract(noise + sine(f1, fs, amp=0.05), fs, rpm)
    faulty = extract(noise + sine(f1, fs, amp=0.05) + impacts, fs, rpm)
    assert faulty["env_bpfo_snr"] > 5 * healthy["env_bpfo_snr"]
    assert faulty["kurtosis"] > healthy["kurtosis"] + 1


def test_missing_electrical_is_nan_and_keys_stable():
    x = sine(50, 12000)
    bare = extract(x, 12000, rpm=1797)
    full = extract(x, 12000, rpm=1797, current=[1.4, 1.5], voltage=12.0, temp=40, prev_temp=39,
                   rpm_history=[1797, 1800])
    assert set(bare) == set(full)
    for k in ("current_mean", "current_std", "power", "temp", "temp_delta", "rpm_var_pct"):
        assert np.isnan(bare[k])
    assert full["power"] == pytest.approx(12.0 * 1.45)
    assert full["temp_delta"] == pytest.approx(1.0)


def test_every_feature_has_a_label():
    f = extract(sine(50, 3200), 3200, rpm=3000)
    assert not set(f) - set(FEATURE_LABELS)


def test_stream_featurizer_history():
    fz = StreamFeaturizer(history=3)
    rec = {"rpm": 3000, "fs": 3200, "current": 1.0, "voltage": 12, "temp": 30.0, "vib": sine(50, 3200)}
    out = None
    for i in range(4):
        out = fz({**rec, "temp": 30.0 + i, "current": 1.0 + 0.1 * i})
    assert out["temp_delta"] == pytest.approx(3.0)  # 33 now vs 30 three windows back
    assert out["current_mean"] == pytest.approx(1.2)


def test_flatline_no_nans():
    zeros = np.zeros(2048)
    f = extract(zeros, 3200, rpm=3000)
    assert not np.isnan(f["kurtosis"])
    assert not np.isnan(f["skewness"])
    assert f["rms"] == 0.0
    assert f["std"] == 0.0


def test_stream_featurizer_drops_stale_data():
    fz = StreamFeaturizer(history=3)
    rec = {"rpm": 3000, "fs": 3200, "current": 1.0, "temp": 30.0, "vib": sine(50, 3200)}
    fz(rec)
    rec_drop = {"rpm": 3000, "fs": 3200, "vib": sine(50, 3200)}
    out = fz(rec_drop)
    assert np.isnan(out["current_mean"])
    assert np.isnan(out["temp"])
