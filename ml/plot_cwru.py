"""
Indux - compare normal vs fault spectra (good slide material).

Run from the Indux folder:
    python ml/plot_cwru.py
Makes: docs/figures/cwru_compare.png
"""
import os
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import welch, hilbert, butter, sosfiltfilt
from train_cwru import load_signal, FS, BEARING, NOMINAL_RPM

CASES = [(97, "Normal"), (105, "Inner race"), (118, "Ball"), (130, "Outer race")]  # all 0 HP

os.makedirs("docs/figures", exist_ok=True)
fig, axes = plt.subplots(len(CASES), 2, figsize=(12, 9), sharex="col")

for row, (num, name) in enumerate(CASES):
    sig, rpm = load_signal(num)
    sig = sig - sig.mean()
    f1 = (rpm or NOMINAL_RPM[0]) / 60

    # Left: raw spectrum (0-5 kHz)
    f, p = welch(sig, fs=FS, nperseg=4096)
    axes[row, 0].semilogy(f, p, lw=0.8)
    axes[row, 0].set_xlim(0, 5000)
    axes[row, 0].set_ylabel(name)

    # Right: envelope spectrum (0-300 Hz) with bearing fault lines
    sos = butter(4, 1000, btype="highpass", fs=FS, output="sos")
    env = np.abs(hilbert(sosfiltfilt(sos, sig)))
    fe, pe = welch(env - env.mean(), fs=FS, nperseg=16384)
    axes[row, 1].plot(fe, pe, lw=0.8)
    axes[row, 1].set_xlim(0, 300)
    for (label, mult), color in zip(BEARING.items(), ["r", "g", "m"]):
        axes[row, 1].axvline(mult * f1, color=color, ls="--", lw=1,
                             label=label.upper() if row == 0 else None)

axes[0, 0].set_title("Vibration spectrum")
axes[0, 1].set_title("Envelope spectrum (bearing impacts)")
axes[0, 1].legend(loc="upper right")
axes[-1, 0].set_xlabel("Hz")
axes[-1, 1].set_xlabel("Hz")
plt.tight_layout()
plt.savefig("docs/figures/cwru_compare.png", dpi=150)
print("Saved docs/figures/cwru_compare.png")