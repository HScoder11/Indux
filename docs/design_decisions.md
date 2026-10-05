# Indux: design decisions and limitations

This document explains **why** Indux is built the way it is. Each decision says what we chose, why, and what
the alternative would have cost. The last section lists what Indux **cannot** do yet.
Numbers come from `docs/figures/*_metrics.json` and the training scripts' output.

---

## 1. Evaluation

### Accuracy is never the headline metric
Failures are rare. In AI4I 2020 only **3.4%** of rows are failures, so a model that always answers "no failure"
is **96.6% accurate** while catching nothing. We report what matters instead:

- **Recall:** what share of real failures were caught.
- **Precision:** what share of alarms were real.
- **F2:** a combined score that weights recall twice as heavily as precision.
- **PR-AUC:** compared against the no-skill baseline, which equals the failure rate.
- **ROC-AUC:** reported as well, alongside PR-AUC.

### Misses cost more than false alarms
A missed failure means unplanned downtime, a damaged machine, sometimes a safety incident. A false alarm means
an engineer spends ten minutes checking a healthy motor. So the decision threshold is chosen to maximise
**F2**, which weights recall twice as heavily as precision. `train_ai4i.py --cost-fn` also reports the
threshold that minimises expected cost for an explicit cost ratio (10 : 1 by default). Changing the threshold
moves you along the precision-recall curve, so the plant can choose its own trade-off.

### The threshold is tuned on validation data, then tested once
AI4I is split **60 / 20 / 20** (train / validation / test), stratified by failure type. The threshold is
chosen on the validation set and applied **once** to the untouched test set. Choosing it on the test set
would quietly overstate the results. The F2 curve is flat between thresholds of about 0.3 and 0.7, so the
result does not depend on an exact threshold value. Repeating the whole procedure on 6 random splits gives
**PR-AUC 0.92 ± 0.01** and **recall 0.84 ± 0.02**, so the headline is not a lucky split.

| AI4I, raw + physics features, test set | Result |
|---|---|
| PR-AUC (no-skill baseline = 0.033) | **0.933** |
| ROC-AUC | 0.993 |
| Recall at the F2 threshold | 85% |
| Precision at the F2 threshold | 92% |
| False alarms on healthy rows | 0.26% |
| Raw sensors only, for comparison | PR-AUC 0.81 |

### Physics features beat more model
Power (torque × speed), strain (torque × tool wear) and the heat gap (process − air temperature) raise
AI4I PR-AUC from 0.81 to 0.93. We get that gain by encoding how machines fail, without a bigger model.
The same idea drives the motor features: 1×/2×/3× running-speed amplitudes, envelope-spectrum bearing
frequencies and current.

### Split by the thing that changes in the real world, never by random window
Random window splits leak: neighbouring windows from the same recording land in both train and test, and
accuracy looks near-perfect for the wrong reason. So we split by the factor that changes in the real world:

- **CWRU:** trained on 3 motor loads, tested on the 4th (leave-one-load-out); also tested on bearing defect sizes never seen in training.
- **Simulator:** trained on sessions 1–4 and tested on session 5. Each session has its own noise, amplitudes, phases, RPM offset and fault severity, so the model must learn the fault, not the session.
- **NASA IMS:** the detector learns from the first 20% of the run only, while the bearings are still healthy, and is then scored forward in time.

---

## 2. The live system

### Each motor learns its own "normal"
No two motors vibrate the same, even of the same model: mounting, load and wear all differ. So the
first **40 readings (~26 s)** after start-up are used to learn this motor's normal baseline. Health is then
the distance from that baseline: the root mean square of the 3 largest deviations, each measured in units
of that feature's normal spread. The baseline is relearned automatically after a speed change of more
than 10%, because "normal" at 3,000 rpm differs from normal at 6,000 rpm. A fixed global threshold would
either miss faults on quiet motors or raise false alarms on noisy ones.

### Two models that check each other
- The **classifier** names known faults: unbalance, looseness, bearing wear and overload.
- The **anomaly detector**, which drives the health score, needs no fault examples, so it also catches faults it was never trained on.
- **A named fault only counts if health also drops** below 80, so the classifier alone can't raise an alarm on a healthy-looking motor.
- If health drops but the classifier recognises nothing, the alert is labelled **"unknown anomaly"**.
- On CWRU, a detector trained on healthy data only caught 99.9% of fault windows, at 0.8% false alarms.

### An alert needs 3 of the last 5 readings
A single noisy reading (a knock on the bench, a cable glitch) must never page someone. Requiring 3 abnormal
readings out of the last 5 (~3 s) removes one-off spikes but still confirms real faults in about 2 seconds:
the simulator autopilot measured an average of 2.3 s, with 4 of 4 faults identified.

### One fault is one alert
While a fault continues, the classifier's label can flicker, for example between "unbalance" and
"unknown anomaly", or while a motor cools down after an overload. That flicker stays inside **one** alert,
and the label is upgraded if the fault becomes recognisable. A *different* fault must show in 3 readings in a
row before it opens a new alert, and an alert closes only after ~5 s of normal readings. Each alert gets
exactly one black-box recording, one AI report and one email. The same fault type is emailed at most once
every 10 minutes (configurable).

### Health is smoothed
Health is averaged over 10 readings (~6 s) so the gauge doesn't jitter. The cost is that it recovers a
few seconds after a fault is fixed. That delay is deliberate: a gauge that jumps between green and red is
not trusted by operators.

### One data contract for every source
The simulator, dataset replay and the ESP32 all send the same JSON line per window
([data_contract.md](data_contract.md)). Features, models, backend and dashboard never know which source is
connected, so the hardware rig plugs into the pipeline the demo already uses. The sample rate travels with
every window, so the same feature code runs on 3.2 kHz (simulator), 12 kHz (CWRU) and 20 kHz (IMS).

### The AI report never invents data
The language model (Claude, with Gemini as fallback) is only called from the backend, where the API key is
kept. It receives the measured readings, the top signals and the alert history, and is told to use only
that data. Without internet or a key, a template report is produced from the same data, so the demo never
depends on the network.

---

## 3. Limitations (stated up front)

- **The live models are trained on simulated data.** The simulator is physics-based, and each session is
  randomised, but it is still a model of a motor rather than a real one. The live demo shows the pipeline
  working end to end. The **accuracy claims come from the public datasets** (CWRU, NASA IMS, AI4I),
  never from the simulator.
- **No real-hardware data yet.** The ESP32 rig sends the same data format and the serial source is built and
  tested for reconnection, but the models have not been retrained or validated on our own motor. That is
  the next step: record healthy and faulty runs on the rig and retrain.
- **Time-to-failure is a rough trend estimate.** It extrapolates the last ~19 s of the health trend in a
  straight line. On NASA IMS the predicted time left swung between near-zero and 200+ hours while the true
  value fell steadily from ~74 hours. Treat it as "getting worse fast / slowly", not as a countdown.
- **CWRU is an easy benchmark.** Its conditions separate cleanly by RMS and kurtosis at every load
  (see `eda_cwru.png`), and its faults were machined into the bearings, not grown by wear. The 100%
  leave-one-load-out result shows the pipeline is sound, not that every real fault is that easy.
  NASA IMS is the harder, more realistic test: a fault that develops naturally over days.
- **Some failures are unpredictable by design.** AI4I tool-wear failures happen at a random tool age
  between 200 and 240 minutes: **0 of 8** were caught on the test set. Random failures (RNF) are
  excluded because no model can predict them.
- **Fault types are limited to what was trained.** The classifier knows unbalance, looseness, bearing wear
  and overload. Anything else is reported as "unknown anomaly" by the anomaly detector. It is still
  caught, but not named.
- **One motor, one sensor position.** Results are for a single accelerometer on the motor mount. A different
  mounting point, or a much larger motor, changes vibration levels and needs a fresh baseline (learned
  automatically) and, for the classifier, more data.
- **Time is not modelled explicitly in AI4I.** Each row is treated independently, as the dataset is
  published. The live system does use time: it uses history for health smoothing, the 3-of-5 rule and the trend.
