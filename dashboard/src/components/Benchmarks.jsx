import { useState } from "react";

// Results from the team's own benchmark runs (ml/*.py). Public datasets are
// labelled as such so judges can tell them apart from the live simulator.
const TILES = [
  { tag: "CWRU bearings", value: "99.9%", label: "Unseen faults detected",
    note: "Anomaly detector trained on healthy data only; 0.8% false alarms." },
  { tag: "CWRU bearings", value: "100%", label: "Faults caught on new bearings",
    note: "0 false alarms. Fault type named correctly 69–73% of the time." },
  { tag: "NASA IMS", value: "3.2 days", label: "Warning before failure",
    note: "Outer-race signal 7–12× higher on the failing bearing than on the others." },
  { tag: "AI4I 2020", value: "86%", label: "Failures detected",
    note: "Up from 70% with raw sensors, by adding 3 physics features. 0.4% false alarms." },
];

const FIGS = [
  ["cwru_compare.png", "CWRU — each fault's envelope peak lands on its bearing-theory frequency", "Public dataset"],
  ["cwru_anomaly_health.png", "CWRU — health score from a detector that never saw a fault", "Public dataset"],
  ["ims_health.png", "NASA IMS — health of 4 bearings over 7 days until bearing 1 failed", "Public dataset"],
  ["ai4i_shap.png", "AI4I 2020 — what drives each failure prediction (SHAP)", "Public dataset"],
  ["cwru_severity_confusion.png", "CWRU — fault type on unseen bearing sizes", "Public dataset"],
  ["live_demo_timeline.png", "Live pipeline rehearsal — faults injected one by one", "Simulator"],
];

function Fig({ file, caption, tag }) {
  const [ok, setOk] = useState(true);
  return (
    <figure className="card" style={{ margin: 0 }}>
      <div className="row" style={{ marginBottom: 8 }}><span className="tag">{tag}</span></div>
      {ok ? (
        <img src={`/figures/${file}`} alt={caption} loading="lazy" onError={() => setOk(false)} />
      ) : (
        <div className="missing">{file} not found in docs/figures — run the matching ml/ script.</div>
      )}
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

export default function Benchmarks() {
  return (
    <>
      <p className="sub" style={{ marginTop: 0 }}>
        The same features and models, tested on public machine datasets. These numbers come from real
        recorded machines — the live tab runs on the simulator (and the ESP32 rig when connected).
      </p>
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
      <div className="figs">
        {FIGS.map(([f, c, t]) => <Fig key={f} file={f} caption={c} tag={t} />)}
      </div>
    </>
  );
}
