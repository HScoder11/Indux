# Indux: predictive maintenance for small motors

```
[Simulator / Dataset replay / (later) ESP32] → ml/features.py → 3 models → FastAPI WebSocket → React dashboard → Claude report
```

All data sources share one JSON-lines format: see [docs/data_contract.md](docs/data_contract.md).

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
pytest
```

## Simulator

```bash
python simulator/motor_sim.py --condition unbalance --rpm 5000 --stream      # live JSON lines; keys 1-6 switch fault, q quits
python simulator/motor_sim.py --condition bearing --rpm 3000 --record 180    # 3 min to data/sim/*.csv (instant)
python simulator/motor_sim.py --condition degrade --ramp 120 --stream        # severity 0→1 over 2 minutes
python simulator/plot_conditions.py                                          # docs/figures/sim_fft_conditions.png
```

Conditions: `healthy`, `unbalance`, `looseness`, `bearing`, `overload`, `degrade`. Each `--seed` draws its own noise, amplitudes, phases, RPM offset and fault signatures.

## Features

`ml.features.extract(window, fs, rpm, current=..., temp=..., ...)` returns a flat dict of time-domain, spectral, envelope (bearing) and electrical/thermal features. `fs` is always passed in (sim 3.2 kHz, CWRU 12 kHz, IMS 20.48 kHz). Use `bearing=CWRU_6205_DE` or `IMS_ZA2115` for the benchmark datasets. `StreamFeaturizer` wraps it for live contract records.

## Datasets (not committed)

| Folder | Source | What to get |
|---|---|---|
| `data/benchmark/cwru/` | CWRU Bearing Data Center | 12 kHz drive-end: normal, inner race, outer race and ball faults (0.007"), loads 0–3 HP |
| `data/benchmark/ims/` | NASA IMS bearing dataset | Test 2 (bearing 1 outer-race failure) |
| `data/benchmark/ai4i/` | UCI AI4I 2020 | `ai4i2020.csv` |
