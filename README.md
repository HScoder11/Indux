# Indux: predictive maintenance for small motors

```
[Simulator / Dataset replay / (later) ESP32] → ml/features.py → 3 models → FastAPI WebSocket → Next.js dashboard → Claude report
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

## Backend

```bash
python ml/train_live.py                         # once: trains models/live_models.joblib
python -m backend.make_demo_recording           # once: data/sim/demo_scenario.csv (replay safety net)
python -m backend                               # simulator, http://localhost:8000/docs
python -m backend --source replay --file demo_scenario.csv
python -m backend --source serial --port COM5   # ESP32
python -m pytest tests -q
```

The AI report uses Claude (`ANTHROPIC_API_KEY`) or Google Gemini (`GEMINI_API_KEY`) from a `.env` file (copy `.env.example`). With both set, Claude is tried first and Gemini is the fallback (`REPORT_PROVIDER=gemini` flips it). Without a key or internet, `/api/report` returns an offline template report.

| Endpoint | What it does |
|---|---|
| `WS /ws/live` | one message per window: health, zone, condition, confidence, top-3 reasons, FFT bars, waveform, alert, time-to-critical |
| `GET /api/status` | source, connection status, last health and condition |
| `GET /api/history?minutes=10` | compact readings for graphs |
| `GET /api/alerts` | alert history with recommended action |
| `GET /api/sources` | recordings in `data/sim/` and serial ports |
| `POST /api/source` | `{"kind":"sim","rpm":5000}`, `{"kind":"replay","file":"demo_scenario.csv"}` or `{"kind":"serial","port":"COM5"}` |
| `POST /api/fault` | simulator only: `{"condition":"unbalance","severity":0.8}` |
| `POST /api/report` | `{"lang":"en"}` or `{"lang":"hi"}` - every new report is saved |
| `GET /api/reports` | previous reports, newest first |
| `GET /api/reports/{id}/download?format=txt\|md\|html` | download a report; `html&inline=1` opens a printable page (Print → Save as PDF) |

The health gauge shows `calibrating: true` for the first ~26 s while the motor's normal is learned, and again after a speed change of more than 10%.

## Dashboard (Next.js, `web/`)

Needs Node.js 18.18+ (https://nodejs.org).

```bash
cd web
npm install          # once
npm run dev          # http://localhost:3000 - live-reloading, talks to the backend on :8000
npm run build        # makes web/out - then `python -m backend` serves it at http://localhost:8000
```

Demo day: build once, then only `python -m backend` is needed; open http://localhost:8000.

| Page | What you can do |
|---|---|
| Live (`/`) | Health, status, AI probabilities, "why", FFT (zoom 0–400 Hz), trends, waveform. **Pause / rewind**: drag the timeline or click any trend chart to see every panel at that moment. Inject faults, drag severity live, **Autopilot** runs every fault in turn and times detection. |
| Alerts (`/alerts`) | Filter by fault type / state / text, click a row for details, AI report and **Replay this event** (plays the black-box recording back through the pipeline). |
| Reports (`/reports`) | Generate English / Hindi reports, browse the library, download PDF / TXT / MD. |
| Benchmarks (`/benchmarks`) | Result tiles and figures from `docs/figures/` - click to enlarge, ← → to flip. |

Keyboard: `1`–`6` inject faults (simulator), `Space` pause/resume, `←` `→` step, `L` live, `G` then `A`/`R`/`B`/`L` switch page, `?` help.
Toasts pop up when an alert starts, clears, or its AI report is ready; the 🔔 button adds a beep.

The older Vite dashboard is still in `dashboard/`; the backend serves `web/out` first and falls back to `dashboard/dist`.

## Alerts: automatic report, email, saved data

When a fault or unknown anomaly is confirmed (3 of the last 5 readings), the backend automatically:

1. saves a **black-box recording** - raw sensor data from 30 s before to 15 s after the alert - to `data/events/` (downloadable from the alert row, and replayable as a data source);
2. writes an **AI report** (Claude or Gemini, else the offline template) and links it to the alert;
3. **emails** it, with the printable report and the last 3 minutes of readings attached - at most once per fault type every 10 minutes.

Every reading (speed, current, voltage, temperature, vibration RMS, health, condition) is saved to `data/indux.db`. Download it as CSV from the Trends card or `GET /api/readings/export?minutes=60` (`minutes=0` = everything). Set `RECORD_RAW=1` to also keep every raw vibration window (`data/recordings/`, large).

With the ESP32 (`--port auto` picks the first USB serial port), the backend keeps reading as long as the sensor sends data; if the cable is pulled it shows "disconnected" and reconnects by itself when the board is back.

**Email setup (Gmail):** turn on 2-Step Verification for the Google account, create an *App password* (Google Account → Security → App passwords), then in `.env` set `SMTP_USER` (the Gmail address), `SMTP_PASSWORD` (the 16-character app password) and `ALERT_EMAIL_TO` (comma-separated recipients). Restart the backend and press **Send test email** in the Alert history card.

## Soak test (before demo day)

With the backend running (`python -m backend`), in a second terminal:

```bash
python tests/soak.py --minutes 60
```

It injects a random fault every ~70 s, measures detection time, counts false alerts and stalls, and prints PASS/FAIL. Results go to `data/soak_results.csv`.
