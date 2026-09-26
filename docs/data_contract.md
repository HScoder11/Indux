# Data contract

Every data source (simulator, dataset replay, and later the ESP32) sends **one JSON object per line, one line per window**.
The backend, `ml/features.py` and the models only depend on this format, so swapping the source changes nothing downstream.

```json
{"ts": 1727340000.12, "source": "sim", "rpm": 5000, "current": 1.42, "voltage": 12.1,
 "temp": 38.4, "fs": 3200, "vib": [0.013, -0.021, "... 2048 floats, in g"]}
```

| Field     | Type          | Unit    | Notes |
|-----------|---------------|---------|-------|
| `ts`      | float         | s       | Unix time of the window start |
| `source`  | string        | –       | `sim`, `replay:<name>`, `esp32` |
| `rpm`     | float         | rev/min | Measured shaft speed for this window |
| `current` | float \| null | A       | Mean motor current over the window. `null` if not measured (CWRU, IMS) |
| `voltage` | float \| null | V       | Supply voltage. `null` if not measured |
| `temp`    | float \| null | °C      | Motor or bearing housing temperature. `null` if not measured |
| `fs`      | float         | Hz      | Vibration sample rate: sim 3200, CWRU 12000, IMS 20480 |
| `vib`     | float[]       | g       | Accelerometer samples, normally 2048 of them |

Rules

- Consumers **must ignore unknown keys**. Recordings add a `label` object (`{"condition": ..., "severity": ...}`) that holds the ground truth. It is used for training and scoring only, never as a model input.
- `fs` is always sent. Nothing downstream may assume 3200 Hz.
- ESP32 firmware: sample the accelerometer at `fs`, and after each 2048-sample block print one line in this format over serial at 921600 baud.
