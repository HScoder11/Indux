"use client";
import { useEffect, useState } from "react";

// Results from the team's own benchmark runs (ml/*.py). Public datasets are
// labelled as such so judges can tell them apart from the live simulator.
const TILES = [
  { tag: "CWRU bearings", value: "99.9%", label: "Unseen faults detected",
    note: "Anomaly detector trained on healthy data only; 0.8% false alarms." },
  { tag: "CWRU bearings", value: "100%", label: "Faults caught on new bearings",
    note: "0 false alarms. Fault type named correctly 69–73% of the time." },
  { tag: "NASA IMS", value: "3.2 days", label: "Warning before failure",
    note: "Outer-race signal 7–12× higher on the failing bearing than on the others." },
  { tag: "AI4I 2020", value: "0.93", label: "PR-AUC (no-skill baseline 0.03)",
    note: "85% of failures caught, 92% of alarms real, on an untouched test set. Threshold chosen on a separate validation set by F2. Raw sensors alone: 0.81." },
];

const FIGS = [
  { file: "eda_cwru.png", caption: "CWRU: what the data looks like (raw signals, RMS and kurtosis by condition and load)", tag: "Public dataset", group: "cwru" },
  { file: "cwru_compare.png", caption: "CWRU: each fault's envelope peak lands on its bearing-theory frequency", tag: "Public dataset", group: "cwru" },
  { file: "cwru_anomaly_health.png", caption: "CWRU: health score from a detector that never saw a fault", tag: "Public dataset", group: "cwru" },
  { file: "cwru_confusion.png", caption: "CWRU: fault type, trained on 3 loads and tested on the 4th", tag: "Public dataset", group: "cwru" },
  { file: "cwru_severity_confusion.png", caption: "CWRU: fault type on unseen bearing sizes", tag: "Public dataset", group: "cwru" },
  { file: "eda_ims.png", caption: "NASA IMS: what the data looks like (RMS, kurtosis, outer-race signal over 7 days)", tag: "Public dataset", group: "ims" },
  { file: "ims_health.png", caption: "NASA IMS: health of 4 bearings over 7 days until bearing 1 failed", tag: "Public dataset", group: "ims" },
  { file: "eda_ai4i.png", caption: "AI4I 2020: what the data looks like (failure rate, failed vs normal, correlations)", tag: "Public dataset", group: "ai4i" },
  { file: "ai4i_pr_curve.png", caption: "AI4I 2020: precision-recall vs the no-skill baseline, and how the threshold was chosen", tag: "Public dataset", group: "ai4i" },
  { file: "ai4i_shap.png", caption: "AI4I 2020: what drives each failure prediction (SHAP)", tag: "Public dataset", group: "ai4i" },
  { file: "ai4i_confusion.png", caption: "AI4I 2020: failure type on the test set (tool-wear failures are random by design: 0 of 8 caught)", tag: "Public dataset", group: "ai4i" },
  { file: "live_confusion.png", caption: "Live classifier on an unseen simulator session", tag: "Simulator", group: "sim" },
  { file: "live_demo_timeline.png", caption: "Live pipeline rehearsal: faults injected one by one", tag: "Simulator", group: "sim" },
  { file: "sim_fft_conditions.png", caption: "Simulator: FFT signature of every condition", tag: "Simulator", group: "sim" },
];
// Said up front, so nobody has to ask (details: docs/design_decisions.md)
const LIMITATIONS = [
  ["Live demo = simulated data", "Accuracy claims above come only from public datasets, never from the simulator."],
  ["No real-hardware data yet", "The ESP32 rig uses the same data format, but the models haven't been retrained on our motor."],
  ["Time-to-failure is rough", "A straight-line trend of recent health: \"declining fast or slowly\", not a countdown."],
  ["CWRU is an easy benchmark", "Its classes separate cleanly. NASA IMS (a fault growing over days) is the realistic test."],
  ["Some failures are random", "AI4I tool-wear failures happen at a random tool age by design: 0 of 8 caught."],
  ["4 named fault types", "Unbalance, looseness, bearing, overload. Anything else is still flagged, as \"unknown anomaly\"."],
];

const GROUPS = [["all", "All"], ["cwru", "CWRU"], ["ims", "NASA IMS"], ["ai4i", "AI4I"], ["sim", "Simulator"]];

function Lightbox({ figs, index, onClose, onMove }) {
  useEffect(() => {
    const k = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") onMove(1);
      if (e.key === "ArrowLeft") onMove(-1);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, onMove]);
  const f = figs[index];
  return (
    <div className="overlay lightbox" onClick={onClose} role="dialog" aria-modal="true" aria-label={f.caption}>
      <button className="icon-btn lb-prev" onClick={(e) => { e.stopPropagation(); onMove(-1); }} aria-label="Previous">‹</button>
      <figure onClick={(e) => e.stopPropagation()}>
        <img src={`/figures/${f.file}`} alt={f.caption} />
        <figcaption><span className="tag">{f.tag}</span> {f.caption} <span className="sub">({index + 1}/{figs.length} · ← → · Esc)</span></figcaption>
      </figure>
      <button className="icon-btn lb-next" onClick={(e) => { e.stopPropagation(); onMove(1); }} aria-label="Next">›</button>
    </div>
  );
}

function Fig({ f, onOpen }) {
  const [ok, setOk] = useState(true);
  return (
    <figure className="card fig" style={{ margin: 0 }}>
      <div className="row" style={{ marginBottom: 8 }}><span className="tag">{f.tag}</span></div>
      {ok ? (
        <button className="fig-btn" onClick={onOpen} aria-label={`Enlarge: ${f.caption}`}>
          <img src={`/figures/${f.file}`} alt={f.caption} loading="lazy" onError={() => setOk(false)} />
        </button>
      ) : (
        <div className="missing">{f.file} not found in docs/figures. Run the matching ml/ script.</div>
      )}
      <figcaption>{f.caption}</figcaption>
    </figure>
  );
}

export default function BenchmarksPage() {
  const [group, setGroup] = useState("all");
  const [open, setOpen] = useState(null);
  const figs = FIGS.filter((f) => group === "all" || f.group === group);
  return (
    <>
      <div className="page-head">
        <h1>Benchmarks</h1>
        <span className="sub">
          The same features and models, tested on public machine datasets. These numbers come from real recorded
          machines. The Live page runs on the simulator (and the ESP32 rig when connected).
        </span>
      </div>
      <div className="tiles">
        {TILES.map((t) => (
          <section className="card tile" key={t.label}>
            <span className="tag">{t.tag}</span>
            <div className="value">{t.value}</div>
            <div className="label">{t.label}</div>
            <div className="note">{t.note}</div>
          </section>
        ))}
      </div>
      <section className="card limits">
        <h2>Limitations</h2>
        <ul>
          {LIMITATIONS.map(([title, text]) => <li key={title}><strong>{title}.</strong> {text}</li>)}
        </ul>
      </section>
      <div className="seg" role="group" aria-label="Dataset" style={{ marginBottom: 12 }}>
        {GROUPS.map(([k, l]) => <button key={k} aria-pressed={group === k} onClick={() => setGroup(k)}>{l}</button>)}
      </div>
      <div className="figs">
        {figs.map((f, i) => <Fig key={f.file} f={f} onOpen={() => setOpen(i)} />)}
      </div>
      {open != null && figs[open] && (
        <Lightbox figs={figs} index={open} onClose={() => setOpen(null)}
          onMove={(d) => setOpen((i) => (i + d + figs.length) % figs.length)} />
      )}
    </>
  );
}
