import { STATUS, StatusIcon } from "./StatusIcon.jsx";

// Semicircle meter: the unfilled track is neutral; the fill carries the zone.
function arc(frac) {
  const a = Math.PI * (1 - frac);
  const r = 90, cx = 110, cy = 110;
  return `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r * Math.cos(a)} ${cy - r * Math.sin(a)}`;
}

export default function HealthGauge({ last, conn }) {
  const offline = conn !== "live" || !last;
  const calibrating = !offline && last.calibrating;
  const zone = offline ? "offline" : calibrating ? "calibrating" : last.zone;
  const health = offline || calibrating ? null : last.health;
  const frac = health == null ? 0 : Math.max(0.005, health / 100);
  const s = STATUS[zone];

  return (
    <section className="card gauge" aria-label="Machine health">
      <h2>Health score</h2>
      <svg viewBox="0 0 220 125" role="img" aria-label={health == null ? s.label : `Health ${health} of 100`}>
        <path d={arc(1)} stroke="var(--surface-2)" strokeWidth="18" fill="none" strokeLinecap="round" />
        {/* zone boundaries at 50 and 80 */}
        {[0.5, 0.8].map((f) => {
          const a = Math.PI * (1 - f);
          return (
            <line key={f} x1={110 + 76 * Math.cos(a)} y1={110 - 76 * Math.sin(a)}
              x2={110 + 104 * Math.cos(a)} y2={110 - 104 * Math.sin(a)} stroke="var(--axis)" strokeWidth="2" />
          );
        })}
        {health != null && (
          <path d={arc(frac)} stroke={s.color} strokeWidth="18" fill="none" strokeLinecap="round"
            style={{ transition: "d 0.5s" }} />
        )}
      </svg>
      <div className="hero">
        {health == null ? "–" : Math.round(health)}
        {health != null && <small>/100</small>}
      </div>
      <div className="zone-label" style={{ color: "var(--ink)" }}>
        <StatusIcon zone={zone} size={22} />
        {s.label}
      </div>
      {calibrating && (
        <>
          <div className="calib-bar" aria-hidden="true">
            <div style={{ width: `${Math.round((last.calib_progress || 0) * 100)}%` }} />
          </div>
          <div className="sub">
            Learning this motor's normal behaviour… {Math.round((last.calib_progress || 0) * 100)}%
          </div>
        </>
      )}
      {!offline && !calibrating && (
        <div className="sub" style={{ marginTop: 8 }}>80–100 healthy · 50–80 watch · below 50 critical</div>
      )}
      {offline && <div className="sub" style={{ marginTop: 8 }}>Waiting for the backend…</div>}
    </section>
  );
}
