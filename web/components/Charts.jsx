"use client";
import { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { clock } from "@/lib/api";

const AXIS = { stroke: "var(--axis)", tick: { fill: "var(--muted)", fontSize: 12 }, tickLine: false };
const GRID = { stroke: "var(--grid)", strokeDasharray: "0", vertical: false };

function Tip({ active, payload, label, unit, labelFmt, digits = 3, hint }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tt">
      <div className="v">{Number(payload[0].value).toFixed(digits)} {unit}</div>
      <div className="k"><span className="key" />{labelFmt ? labelFmt(label) : label}</div>
      {hint && <div className="k">{hint}</div>}
    </div>
  );
}

const onPick = (inspect) => (e) => { if (e?.activeLabel != null) inspect(e.activeLabel); };

/** Shaded spans where an alert was active, so you can see (and click) when faults happened. */
function alertSpans(history) {
  const spans = [];
  let start = null;
  history.forEach((h, i) => {
    if (h.alert && start == null) start = h.t;
    if ((!h.alert || i === history.length - 1) && start != null) {
      spans.push([start, h.t]);
      start = null;
    }
  });
  return spans;
}

/* ---------------- FFT ---------------- */
const RANGES = { low: [0, 400], full: [0, 1600] };

export function FftChart({ last }) {
  const [range, setRange] = useState("full");
  const [lo, hi] = RANGES[range];
  const data = useMemo(() => {
    if (!last?.fft) return [];
    return last.fft.hz.map((hz, i) => ({ hz, amp: last.fft.amp[i] })).filter((d) => d.hz >= lo && d.hz < hi);
  }, [last, lo, hi]);
  const m = last?.fft?.markers;
  const ticks = range === "low" ? [0, 100, 200, 300, 400] : [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600];
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Vibration spectrum (FFT)</h2>
        <div className="seg" role="group" aria-label="Frequency range">
          <button aria-pressed={range === "low"} onClick={() => setRange("low")}>Zoom 0–400 Hz</button>
          <button aria-pressed={range === "full"} onClick={() => setRange("full")}>Full</button>
        </div>
      </div>
      <div className="sub" style={{ marginBottom: 4 }}>
        1×, 2×, 3× = running speed and its multiples.
        {range === "full" && " Bearing impacts ring around 1 kHz."}
      </div>
      <div style={{ height: 230 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 18, right: 12, left: 0, bottom: 4 }} barCategoryGap={1}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="hz" type="number" domain={[lo, hi]} ticks={ticks} unit=" Hz" {...AXIS} />
            <YAxis width={52} {...AXIS} tickFormatter={(v) => v.toFixed(2)} />
            <Tooltip cursor={{ fill: "var(--series-wash)" }} isAnimationActive={false}
              content={<Tip unit="g" labelFmt={(hz) => `${hz}–${hz + 10} Hz`} digits={4} />} />
            {range === "full" && <ReferenceArea x1={900} x2={1100} fill="var(--warning)" fillOpacity={0.08} />}
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
    const dtMs = ((2048 / 3200) * 1000) / last.wave.length;   // wave = the 0.64 s window, downsampled
    return last.wave.map((v, i) => ({ ms: Math.round(i * dtMs), v }));
  }, [last]);
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Vibration waveform</h2>
        <span className="sub">0.64 s window{last ? ` · ${clock(last.ts)}` : ""}</span>
      </div>
      <div style={{ height: 150 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="ms" unit=" ms" {...AXIS} minTickGap={40} />
            <YAxis width={52} {...AXIS} tickFormatter={(v) => v.toFixed(2)} />
            <Tooltip isAnimationActive={false} cursor={{ stroke: "var(--axis)" }} content={<Tip unit="g" labelFmt={(ms) => `${ms} ms`} />} />
            <Line dataKey="v" stroke="var(--series)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

/* ---------------- small multiples: one measure per chart, never two y-axes ---------------- */
function Mini({ data, dataKey, title, unit, digits, cursor, inspect, spans }) {
  const shown = cursor != null ? data.find((d) => d.t === cursor) : data[data.length - 1];
  const v = shown?.[dataKey];
  return (
    <div className="mini">
      <h3>{title}</h3>
      <div className="now">{v == null ? "–" : Number(v).toFixed(digits)} <span className="sub">{unit}</span></div>
      <div style={{ height: 110 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 6, right: 6, left: 0, bottom: 0 }} onClick={onPick(inspect)} style={{ cursor: "pointer" }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
            <YAxis width={44} {...AXIS} domain={["auto", "auto"]} tickCount={3} tickFormatter={(x) => Number(x).toFixed(digits > 1 ? 2 : digits)} />
            {spans.map(([a, b]) => <ReferenceArea key={a} x1={a} x2={b} fill="var(--critical)" fillOpacity={0.08} />)}
            {cursor != null && <ReferenceLine x={cursor} stroke="var(--ink)" strokeDasharray="3 3" />}
            <Tooltip isAnimationActive={false} cursor={{ stroke: "var(--axis)" }}
              content={<Tip unit={unit} labelFmt={clock} digits={digits} hint="click to inspect" />} />
            <Area dataKey={dataKey} stroke="var(--series)" strokeWidth={2} fill="var(--series-wash)" isAnimationActive={false} connectNulls dot={false} />
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

export function TrendCharts({ history, cursor, inspect }) {
  const [table, setTable] = useState(false);
  const spans = useMemo(() => alertSpans(history), [history]);
  const props = { data: history, cursor, inspect, spans };
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Trends</h2>
        <span className="row" style={{ gap: 12 }}>
          <SavedReadings />
          <button className="link-btn" onClick={() => setTable((v) => !v)}>{table ? "Show charts" : "Show table"}</button>
        </span>
      </div>
      {table ? (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Health</th><th>Vibration (g)</th><th>Current (A)</th><th>Temp (°C)</th></tr></thead>
            <tbody>
              {history.slice(-30).reverse().map((h) => (
                <tr key={h.t} onClick={() => inspect(h.t)} className="clickable" aria-current={cursor === h.t ? "true" : undefined}>
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
          <Mini {...props} dataKey="vib" title="Vibration RMS" unit="g" digits={3} />
          <Mini {...props} dataKey="current" title="Current" unit="A" digits={2} />
          <Mini {...props} dataKey="temp" title="Temperature" unit="°C" digits={1} />
        </div>
      )}
    </section>
  );
}

/* ---------------- health trend ---------------- */
export function HealthTrend({ history, cursor, inspect }) {
  const spans = useMemo(() => alertSpans(history), [history]);
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Health trend</h2>
        <span className="sub">click to rewind · alarm 50 · healthy 80</span>
      </div>
      <div style={{ height: 140 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history} margin={{ top: 6, right: 12, left: 0, bottom: 0 }} onClick={onPick(inspect)} style={{ cursor: "pointer" }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
            <YAxis width={36} domain={[0, 100]} ticks={[0, 50, 80, 100]} {...AXIS} />
            {spans.map(([a, b]) => <ReferenceArea key={a} x1={a} x2={b} fill="var(--critical)" fillOpacity={0.1} />)}
            <ReferenceLine y={50} stroke="var(--critical)" strokeWidth={1} />
            <ReferenceLine y={80} stroke="var(--good)" strokeWidth={1} />
            {cursor != null && <ReferenceLine x={cursor} stroke="var(--ink)" strokeDasharray="3 3" />}
            <Tooltip isAnimationActive={false} cursor={{ stroke: "var(--axis)" }}
              content={<Tip unit="/ 100" labelFmt={clock} digits={0} hint="click to inspect" />} />
            <Line dataKey="health" stroke="var(--series)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
