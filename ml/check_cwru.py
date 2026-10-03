import numpy as np
import matplotlib.pyplot as plt
from scipy.io import loadmat
from scipy.signal import welch

d = loadmat("data/benchmark/cwru/97.mat")

sig = d["X097_DE_time"].ravel()
sig = sig - sig.mean()                      # remove the 0 Hz offset
fs = 12000
f1 = float(d["X097RPM"].ravel()[0]) / 60

freqs, psd = welch(sig, fs=fs, nperseg=12000)   # 1 Hz resolution, averaged
plt.semilogy(freqs, psd)
for k in (1, 2, 3):
    plt.axvline(k * f1, color="r", ls="--", label=f"{k}x" if k == 1 else None)
plt.xlim(0, 500); plt.xlabel("Hz"); plt.ylabel("Power (log)")
plt.title("CWRU 97 — Normal (Welch, 1 Hz resolution)"); plt.legend()
plt.show()