import { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

const AXIS = { stroke: "var(--axis)", tick: { fill: "var(--muted)", fontSize: 12 }, tickLine: false };
const GRID = { stroke: "var(--grid)", strokeDasharray: "0", vertical: false };

function Tip({ active, payload, label, unit, labelFmt, digits = 3 }) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  return (
    <div className="tt">
      <div className="v">{Number(p.value).toFixed(digits)} {unit}</div>
      <div className="k"><span className="key" />{labelFmt ? labelFmt(label) : label}</div>
    </div>
  );
}

/* ---------------- FFT ---------------- */
export function FftChart({ last }) {
  const data = useMemo(() => {
    if (!last?.fft) return [];
    return last.fft.hz.map((hz, i) => ({ hz, amp: last.fft.amp[i] }));
  }, [last]);
  const m = last?.fft?.markers;
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Vibration spectrum (FFT)</h2>
        <span className="sub">1×, 2×, 3× = running speed and its multiples</span>
      </div>
      <div style={{ height: 230 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 18, right: 12, left: 0, bottom: 4 }} barCategoryGap={1}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="hz" type="number" domain={[0, 1600]} ticks={[0, 200, 400, 600, 800, 1000, 1200, 1400, 1600]} unit=" Hz" {...AXIS} />
            <YAxis width={52} {...AXIS} tickFormatter={(v) => v.toFixed(2)} />
            <Tooltip cursor={{ fill: "var(--series-wash)" }} isAnimationActive={false}
              content={<Tip unit="g" labelFmt={(hz) => `${hz}–${hz + 10} Hz`} digits={4} />} />
            {m && ["1x", "2x", "3x"].map((k) => (
              <ReferenceLine key={k} x={m[k]} stroke="var(--muted)" strokeWidth={1}
                label={{ value: k.replace("x", "×"), position: "top", fill: "var(--ink-2)", fontSize: 12, fontWeight: 700 }} />
            ))}
            <Bar dataKey="amp" fill="var(--series)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

/* ---------------- waveform ---------------- */
export function WaveChart({ last }) {
  const data = useMemo(() => {
    if (!last?.wave) return [];
    const n = last.wave.length;
    const dtMs = (2048 / 3200) * 1000 / n;   // wave is the 0.64 s window, downsampled
    return last.wave.map((v, i) => ({ ms: Math.round(i * dtMs), v }));
  }, [last]);
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Vibration waveform</h2>
        <span className="sub">latest 0.64 s window</span>
      </div>
      <div style={{ height: 150 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="ms" unit=" ms" {...AXIS} minTickGap={40} />
            <YAxis width={52} {...AXIS} tickFormatter={(v) => v.toFixed(2)} />
            <Tooltip isAnimationActive={false} cursor={{ stroke: "var(--axis)" }}
              content={<Tip unit="g" labelFmt={(ms) => `${ms} ms`} />} />
            <Line dataKey="v" stroke="var(--series)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

/* ---------------- small multiples: one measure per chart, never two y-axes ---------------- */
function clock(t) {
  return new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function Mini({ data, dataKey, title, unit, digits, domain }) {
  const now = data.length ? data[data.length - 1][dataKey] : null;
  return (
    <div className="mini">
      <h3>{title}</h3>
      <div className="now">{now == null ? "–" : Number(now).toFixed(digits)} <span className="sub">{unit}</span></div>
      <div style={{ height: 110 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="t" hide />
            <YAxis width={44} {...AXIS} domain={domain || ["auto", "auto"]} tickCount={3}
              tickFormatter={(v) => Number(v).toFixed(digits > 1 ? 2 : digits)} />
            <Tooltip isAnimationActive={false} cursor={{ stroke: "var(--axis)" }}
              content={<Tip unit={unit} labelFmt={clock} digits={digits} />} />
            <Area dataKey={dataKey} stroke="var(--series)" strokeWidth={2} fill="var(--series-wash)"
              isAnimationActive={false} connectNulls dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* every reading is saved on the laptop (SQLite); these links download them as CSV */
function SavedReadings() {
  const [n, setN] = useState(null);
  useEffect(() => {
    const get = () => fetch("/api/readings/stats").then((r) => r.json()).then((s) => setN(s.count)).catch(() => {});
    get();
    const t = setInterval(get, 10000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="sub">
      {n != null && `${n.toLocaleString()} readings saved · `}
      CSV: <a className="link-btn" href="/api/readings/export?minutes=60" download>last hour</a>
      {" · "}<a className="link-btn" href="/api/readings/export?minutes=1440" download>24 h</a>
      {" · "}<a className="link-btn" href="/api/readings/export?minutes=0" download>all</a>
    </span>
  );
}

export function TrendCharts({ history }) {
  const [table, setTable] = useState(false);
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Trends — last ~90 seconds</h2>
        <span className="row" style={{ gap: 12 }}>
          <SavedReadings />
          <button className="link-btn" onClick={() => setTable((v) => !v)}>
            {table ? "Show charts" : "Show table"}
          </button>
        </span>
      </div>
      {table ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Health</th><th>Vibration (g)</th><th>Current (A)</th><th>Temp (°C)</th></tr></thead>
            <tbody>
              {history.slice(-20).reverse().map((h) => (
                <tr key={h.t}>
                  <td className="num">{clock(h.t)}</td>
                  <td className="num">{h.health == null ? "–" : h.health.toFixed(0)}</td>
                  <td className="num">{h.vib?.toFixed(3)}</td>
                  <td className="num">{h.current?.toFixed(2)}</td>
                  <td className="num">{h.temp?.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="small-multiples">
          <Mini data={history} dataKey="vib" title="Vibration RMS" unit="g" digits={3} />
          <Mini data={history} dataKey="current" title="Current" unit="A" digits={2} />
          <Mini data={history} dataKey="temp" title="Temperature" unit="°C" digits={1} />
        </div>
      )}
    </section>
  );
}

/* ---------------- health trend ---------------- */
export function HealthTrend({ history }) {
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Health trend</h2>
        <span className="sub">alarm 50 · healthy 80</span>
      </div>
      <div style={{ height: 140 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="t" hide />
            <YAxis width={36} domain={[0, 100]} ticks={[0, 50, 80, 100]} {...AXIS} />
            <ReferenceLine y={50} stroke="var(--critical)" strokeWidth={1} />
            <ReferenceLine y={80} stroke="var(--good)" strokeWidth={1} />
            <Tooltip isAnimationActive={false} cursor={{ stroke: "var(--axis)" }}
              content={<Tip unit="/ 100" labelFmt={clock} digits={0} />} />
            <Line dataKey="health" stroke="var(--series)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
