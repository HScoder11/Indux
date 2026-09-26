"""Phase 1 check: FFT of every simulator condition, with 1x/2x/3x marked.

    python simulator/plot_conditions.py            -> docs/figures/sim_fft_conditions.png
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ml.features import amplitude_spectrum, extract  # noqa: E402
from simulator.motor_sim import BPFO_RATIO, MotorSimulator  # noqa: E402

RPM = 5000
CONDS = ("healthy", "unbalance", "looseness", "bearing", "overload")


def main(out=ROOT / "docs" / "figures" / "sim_fft_conditions.png"):
    fig, axes = plt.subplots(len(CONDS) + 1, 1, figsize=(10, 14), sharex=False)
    f1 = None
    for ax, cond in zip(axes, CONDS):
        sim = MotorSimulator(cond, RPM, seed=11, severity=0.8)
        for _ in range(5):
            rec = sim.next_window()
        x, fs = np.asarray(rec["vib"]), rec["fs"]
        f1 = rec["rpm"] / 60
        freqs, amp = amplitude_spectrum(x, fs)
        feats = extract(x, fs, rec["rpm"])
        ax.plot(freqs, amp, lw=0.8)
        for k, c in ((0.5, "grey"), (1, "C3"), (2, "C2"), (3, "C1")):
            ax.axvline(k * f1, color=c, ls="--", lw=0.8, alpha=0.7)
        ax.set_xlim(0, 400)
        ax.set_ylabel("g")
        ax.set_title(f"{cond}: 1x={feats['amp_1x']:.3f} g, 2x/1x={feats['ratio_2x_1x']:.2f}, "
                     f"kurtosis={feats['kurtosis']:.1f}, current={rec['current']:.2f} A, rpm={rec['rpm']:.0f}",
                     fontsize=9, loc="left")

    # envelope spectrum: healthy vs bearing
    from scipy import signal
    ax = axes[-1]
    for cond, col in (("healthy", "C0"), ("bearing", "C3")):
        sim = MotorSimulator(cond, RPM, seed=11, severity=0.8)
        rec = sim.next_window()
        x, f1 = np.asarray(rec["vib"]), rec["rpm"] / 60
        sos = signal.butter(4, [400, 1440], btype="bandpass", fs=3200, output="sos")
        env = np.abs(signal.hilbert(signal.sosfiltfilt(sos, x - x.mean())))
        ef, ea = amplitude_spectrum(env, 3200)
        ax.plot(ef, ea, lw=0.8, color=col, label=cond)
    for k in (1, 2, 3):
        ax.axvline(k * BPFO_RATIO * f1, color="k", ls=":", lw=0.8)
    ax.set_xlim(0, 1000)
    ax.set_title("Envelope spectrum (400-1440 Hz band): dotted = BPFO harmonics", fontsize=9, loc="left")
    ax.legend(fontsize=8)
    axes[-2].set_xlabel("Hz")
    ax.set_xlabel("Hz")

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
