import numpy as np
import pytest

from ml.features import StreamFeaturizer
from simulator.motor_sim import FS, N, MotorSimulator, read_recording, write_recording

CONTRACT_KEYS = {"ts", "source", "rpm", "current", "voltage", "temp", "fs", "vib"}


def mean_features(condition, seed=7, rpm=5000, windows=40, severity=0.8):
    sim = MotorSimulator(condition, rpm, seed=seed, severity=severity)
    fz = StreamFeaturizer()
    rows = [fz(sim.next_window()) for _ in range(windows)]
    return {k: float(np.nanmean([r[k] for r in rows[-10:]])) for k in rows[0]}


@pytest.fixture(scope="module")
def healthy():
    return mean_features("healthy")


def test_contract_shape():
    rec = MotorSimulator(seed=1).next_window()
    assert set(rec) == CONTRACT_KEYS
    assert rec["fs"] == FS and len(rec["vib"]) == N
    assert "label" in MotorSimulator(seed=1).next_window(include_label=True)


def test_seed_reproducible():
    a = MotorSimulator("bearing", seed=3).next_window()
    b = MotorSimulator("bearing", seed=3).next_window()
    assert a["vib"] == b["vib"] and a["rpm"] == b["rpm"]


def test_unbalance_raises_1x(healthy):
    f = mean_features("unbalance")
    assert f["amp_1x"] > 2 * healthy["amp_1x"]
    assert f["current_mean"] > healthy["current_mean"]


def test_looseness_raises_harmonics_and_subharmonic(healthy):
    f = mean_features("looseness")
    assert f["amp_2x"] > 2 * healthy["amp_2x"]
    assert f["amp_3x"] > 2 * healthy["amp_3x"]
    assert f["amp_0_5x"] > 3 * healthy["amp_0_5x"]


def test_bearing_impacts(healthy):
    f = mean_features("bearing")
    assert f["kurtosis"] > healthy["kurtosis"] + 1
    assert f["env_bpfo_snr"] > 3 * healthy["env_bpfo_snr"]


def test_overload(healthy):
    f = mean_features("overload", windows=200)
    assert f["current_mean"] > 1.25 * healthy["current_mean"]
    assert f["rpm"] < 0.98 * healthy["rpm"]
    assert f["temp"] > healthy["temp"] + 3
    assert f["rms"] > healthy["rms"]


def test_degrade_severity_ramps():
    sim = MotorSimulator("degrade", seed=5, ramp_seconds=30)
    sev = [sim.next_window(include_label=True)["label"]["severity"] for _ in range(60)]
    assert sev[0] == 0.0 and sev[-1] == 1.0
    assert all(b >= a for a, b in zip(sev, sev[1:]))


def test_live_condition_switch():
    sim = MotorSimulator("healthy", seed=2)
    sim.next_window()
    sim.set_condition("unbalance")
    assert sim.next_window(include_label=True)["label"]["condition"] == "unbalance"


def test_csv_roundtrip(tmp_path):
    sim = MotorSimulator("looseness", seed=4)
    recs = [sim.next_window(include_label=True) for _ in range(3)]
    path = tmp_path / "rec.csv"
    assert write_recording(path, recs) == 3
    back = list(read_recording(path))
    assert len(back) == 3 and back[0]["label"]["condition"] == "looseness"
    np.testing.assert_allclose(back[0]["vib"], recs[0]["vib"], atol=1e-5)
