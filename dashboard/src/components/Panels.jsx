import { useEffect, useRef, useState } from "react";
import { StatusIcon } from "./StatusIcon.jsx";

/* ---------------- status card ---------------- */
export function StatusCard({ last, conn }) {
  const [flash, setFlash] = useState(false);
  const prevAlert = useRef(false);
  const alert = !!last?.alert;

  useEffect(() => {
    if (alert && !prevAlert.current) {
      setFlash(true);
      const t = setTimeout(() => setFlash(false), 1300);
      prevAlert.current = alert;
      return () => clearTimeout(t);
    }
    prevAlert.current = alert;
  }, [alert]);

  if (conn !== "live" || !last) {
    return (
      <section className="card status">
        <h2>Status</h2>
        <div className="cond" style={{ color: "var(--muted)" }}>No data</div>
      </section>
    );
  }

  const zone = alert ? "red" : last.calibrating ? "calibrating" : last.condition === "healthy" ? "green" : "yellow";
  const title = alert ? `Fault: ${last.alert_label}` : last.condition === "healthy" ? "Healthy" : `Possible ${last.condition_label.toLowerCase()}`;
  return (
    <section className={`card status ${alert ? "alerting" : ""} ${flash ? "flash" : ""}`} aria-live="polite">
      <h2>Status</h2>
      <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
        <StatusIcon zone={zone} size={34} />
        <div>
          <div className="cond">{title}</div>
          <div className="conf">
            {Math.round(last.confidence * 100)}% confidence
            {!alert && last.condition !== "healthy" && " · confirming (needs 3 of last 5 readings)"}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ---------------- metrics row ---------------- */
function fmt(v, d = 1) {
  return v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d);
}
export function Metrics({ last }) {
  const items = [
    ["Speed", fmt(last?.rpm, 0), "rpm"],
    ["Current", fmt(last?.current, 2), "A"],
    ["Temperature", fmt(last?.temp, 1), "°C"],
    ["Vibration RMS", fmt(last?.vib_rms, 3), "g"],
  ];
  return (
    <div className="metrics">
      {items.map(([label, value, unit]) => (
        <div className="metric" key={label}>
          <div className="label">{label}</div>
          <div className="value">{value}<small>{unit}</small></div>
        </div>
      ))}
    </div>
  );
}

/* ---------------- "why?" panel ---------------- */
function sig(v) {
  if (v == null) return "–";
  const a = Math.abs(v);
  return a >= 100 ? v.toFixed(0) : a >= 1 ? v.toFixed(2) : v.toPrecision(3);
}
export function WhyPanel({ last }) {
  const reasons = last?.reasons || [];
  const max = Math.max(10, ...reasons.map((r) => Math.abs(r.z)));
  return (
    <section className="card">
      <h2>Why? — top 3 signals</h2>
      {last?.calibrating && <div className="sub">Available once the normal baseline is learned.</div>}
      {!last?.calibrating && reasons.length === 0 && <div className="sub">No data yet.</div>}
      <div className="why">
        {reasons.map((r) => {
          const mult = Math.abs(r.z);
          return (
            <div className="why-item" key={r.feature}>
              <div className="top">
                <span className="name">{r.label}</span>
                <span className="mult">
                  {mult >= 50 ? "≥50" : mult.toFixed(1)}× {r.direction === "higher" ? "↑ higher" : "↓ lower"}
                </span>
              </div>
              <div className="why-bar" role="img" aria-label={`${r.label}: ${mult.toFixed(1)} times normal spread, ${r.direction}`}>
                <div style={{ width: `${Math.min(100, (mult / max) * 100)}%` }} />
              </div>
              <div className="detail">now {sig(r.value)} · normal {sig(r.normal)}</div>
            </div>
          );
        })}
      </div>
      {!last?.calibrating && reasons.length > 0 && (
        <div className="hint">How far each signal is from this motor's learned normal, in multiples of its usual variation.</div>
      )}
    </section>
  );
}

/* ---------------- time to failure ---------------- */
function humanTime(s) {
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}
export function TtfCard({ last }) {
  const ttf = last?.ttf_s;
  let body;
  if (!last || last.calibrating) body = <div className="sub">Waiting for baseline…</div>;
  else if (last.health != null && last.health < 10) {
    body = (
      <>
        <div className="big">Critical now</div>
        <div className="sub">Health is already at the bottom of the scale — act on the alert.</div>
      </>
    );
  }
  else if (ttf == null) {
    body = (
      <>
        <div className="big">Stable</div>
        <div className="sub">No downward health trend right now.</div>
      </>
    );
  } else {
    body = (
      <>
        <div className="big">≈ {humanTime(ttf)}</div>
        <div className="sub">to critical at the current rate of decline — a rough trend estimate, not a guarantee.</div>
      </>
    );
  }
  return (
    <section className="card ttf">
      <h2>Estimated time to failure</h2>
      {body}
    </section>
  );
}
