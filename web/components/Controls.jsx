"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, FAULTS, injectFault } from "@/lib/api";
import { useLive } from "@/lib/live";
import { useToast } from "@/lib/toast";

export function Controls() {
  const { latest, clearHistory } = useLive();
  const toast = useToast();
  const [sources, setSources] = useState({ recordings: [], serial_ports: [] });
  const [kind, setKind] = useState("sim");
  const [file, setFile] = useState("");
  const [port, setPort] = useState("");
  const [rpm, setRpm] = useState(5000);
  const [severity, setSeverity] = useState(0.8);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const sevTimer = useRef(null);

  const load = useCallback((first = false) => api("/api/sources").then((s) => {
    setSources(s);
    if (first) setKind(s.current.kind);
    setFile((f) => f || s.recordings[0]?.file || "");
    setPort((p) => p || s.serial_ports[0] || "");
  }).catch(() => {}), []);
  useEffect(() => { load(true); }, [load]);

  const info = latest?.source_info;
  const isSim = info?.kind === "sim";
  const current = info?.condition;

  const apply = async () => {
    setErr(""); setBusy(true);
    try {
      const r = await api("/api/source", { kind, rpm: Number(rpm), file, port });
      clearHistory();
      toast({ zone: "calibrating", title: `Switched to ${r.source?.name || kind}`, body: "Learning this machine's normal first (~26 s)." });
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const inject = async (condition) => {
    setErr("");
    try { await injectFault(condition, Number(severity)); } catch (e) { setErr(e.message); }
  };
  // dragging severity while a fault is active re-applies it live (debounced)
  const changeSeverity = (v) => {
    setSeverity(v);
    if (!isSim || !current || current === "healthy") return;
    clearTimeout(sevTimer.current);
    sevTimer.current = setTimeout(() => injectFault(current, Number(v)).catch(() => {}), 300);
  };

  return (
    <section className="card controls">
      <h2>Demo controls</h2>
      <label htmlFor="src">Data source</label>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <select id="src" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="sim">Simulator</option>
          <option value="replay">Replay recording</option>
          <option value="serial">ESP32 (USB)</option>
        </select>
        <button className="btn primary" onClick={apply} disabled={busy}>{busy ? "Switching…" : "Switch"}</button>
      </div>
      {kind === "sim" && (
        <div style={{ marginTop: 8 }}>
          <label htmlFor="rpm">Motor speed: {rpm} rpm</label>
          <input id="rpm" type="range" min="3000" max="7000" step="500" value={rpm} onChange={(e) => setRpm(e.target.value)} />
        </div>
      )}
      {kind === "replay" && (
        <div style={{ marginTop: 8 }}>
          <label htmlFor="file">Recording</label>
          <select id="file" value={file} onChange={(e) => setFile(e.target.value)} onFocus={() => load()}>
            {sources.recordings.length === 0 && <option value="">No recordings in data/sim/</option>}
            {sources.recordings.map((r) => <option key={r.file} value={r.file}>{r.file}</option>)}
          </select>
        </div>
      )}
      {kind === "serial" && (
        <div style={{ marginTop: 8 }}>
          <label htmlFor="port">Serial port</label>
          <input id="port" type="text" value={port} placeholder="e.g. COM5 or auto" onChange={(e) => setPort(e.target.value)} list="ports" onFocus={() => load()} />
          <datalist id="ports">{sources.serial_ports.map((p) => <option key={p} value={p} />)}</datalist>
        </div>
      )}

      <div style={{ marginTop: 14 }}>
        <label>Inject a fault {isSim ? "" : "(simulator only)"}</label>
        <div className="fault-grid">
          {FAULTS.map((f) => (
            <button key={f.key} className="btn" disabled={!isSim} aria-pressed={isSim && current === f.key}
              onClick={() => inject(f.key)} title={`Shortcut: ${f.hotkey}`}>
              {f.label}<kbd>{f.hotkey}</kbd>
            </button>
          ))}
        </div>
        <label htmlFor="sev" style={{ marginTop: 10 }}>Fault severity: {Math.round(severity * 100)}%</label>
        <input id="sev" type="range" min="0.1" max="1" step="0.1" value={severity} disabled={!isSim}
          onChange={(e) => changeSeverity(e.target.value)} />
        <div className="hint">Drag while a fault is active to change it live. Current source: {info?.name || "–"}</div>
      </div>
      {err && <div className="error" role="alert">{err}</div>}
    </section>
  );
}

/* ---------------- autopilot: scripted fault sequence with detection timing ---------------- */
const SCRIPT = [
  { cond: "healthy", secs: 12, note: "Baseline" },
  { cond: "unbalance", secs: 20 },
  { cond: "healthy", secs: 12 },
  { cond: "looseness", secs: 20 },
  { cond: "healthy", secs: 12 },
  { cond: "bearing", secs: 20 },
  { cond: "healthy", secs: 12 },
  { cond: "overload", secs: 25 },
  { cond: "healthy", secs: 10, note: "Recovered" },
];
const LABEL = Object.fromEntries(FAULTS.map((f) => [f.key, f.label]));

export function Autopilot() {
  const { latest } = useLive();
  const toast = useToast();
  const [running, setRunning] = useState(false);
  const [idx, setIdx] = useState(0);
  const [stepStart, setStepStart] = useState(0);
  const [now, setNow] = useState(0);
  const [results, setResults] = useState({});
  const [finished, setFinished] = useState(false);
  const runningRef = useRef(false);

  const isSim = latest?.source_info?.kind === "sim";
  const calibrating = !!latest?.calibrating;

  const enter = useCallback((i) => {
    setIdx(i);
    setStepStart(Date.now());
    injectFault(SCRIPT[i].cond, 0.8).catch(() => {});
  }, []);

  const stop = useCallback((finished = false) => {
    runningRef.current = false;
    setRunning(false);
    setFinished(finished);
    injectFault("healthy").catch(() => {});
    if (finished) toast({ zone: "green", title: "Autopilot finished", body: "Detection times are in the Autopilot card." });
  }, [toast]);

  const start = () => {
    setResults({});
    setFinished(false);
    runningRef.current = true;
    setRunning(true);
    enter(0);
  };

  // clock + step advance (pauses while the baseline is still being learned)
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      const n = Date.now();
      setNow(n);
      if (calibrating) { setStepStart(n); return; }
      if (n - stepStart >= SCRIPT[idx].secs * 1000) {
        if (idx + 1 >= SCRIPT.length) stop(true); else enter(idx + 1);
      }
    }, 250);
    return () => clearInterval(t);
  }, [running, idx, stepStart, calibrating, enter, stop]);

  // detection timing
  useEffect(() => {
    if (!running || !latest?.alert) return;
    const step = SCRIPT[idx];
    if (step.cond === "healthy" || results[idx]) return;
    const secs = (Date.now() - stepStart) / 1000;
    setResults((r) => ({ ...r, [idx]: { secs, as: latest.alert_condition, ok: latest.alert_condition === step.cond } }));
  }, [latest, running, idx, stepStart, results]);

  // leaving the page stops the run and puts the motor back to healthy
  useEffect(() => () => { if (runningRef.current) injectFault("healthy").catch(() => {}); }, []);

  const elapsed = running ? Math.min(SCRIPT[idx].secs, (now - stepStart) / 1000) : 0;
  const faults = SCRIPT.map((s, i) => [s, i]).filter(([s]) => s.cond !== "healthy");
  const done = faults.filter(([, i]) => results[i]);

  return (
    <section className="card">
      <div className="chart-title">
        <h2>Autopilot demo</h2>
        {running
          ? <button className="btn small" onClick={() => stop(false)}>■ Stop</button>
          : <button className="btn small primary" onClick={start} disabled={!isSim}>▶ Run</button>}
      </div>
      <div className="sub">
        {isSim ? "Injects each fault in turn and times how fast the AI catches it." : "Switch to the simulator to use autopilot."}
      </div>
      <ol className="steps">
        {SCRIPT.map((s, i) => {
          const r = results[i];
          const state = finished || (running && i < idx) || (!running && results[i]) ? "done" : running && i === idx ? "active" : "";
          return (
            <li key={i} className={`step ${state}`}>
              <span className="step-name">{s.note || LABEL[s.cond]}</span>
              {i === idx && running && (
                <span className="step-bar"><span style={{ width: `${(elapsed / s.secs) * 100}%` }} /></span>
              )}
              {i === idx && running && calibrating && <span className="sub">waiting for baseline…</span>}
              {r && <span className={`step-res ${r.ok ? "ok" : "warn"}`}>{r.ok ? `✓ caught in ${r.secs.toFixed(1)} s` : `flagged as ${r.as} (${r.secs.toFixed(1)} s)`}</span>}
              {!r && s.cond !== "healthy" && (i < idx || (!running && Object.keys(results).length > 0)) && <span className="step-res warn">not confirmed</span>}
            </li>
          );
        })}
      </ol>
      {done.length > 0 && (
        <div className="hint">
          {done.filter(([, i]) => results[i].ok).length} of {faults.length} faults identified correctly · average{" "}
          {(done.reduce((a, [, i]) => a + results[i].secs, 0) / done.length).toFixed(1)} s to confirm (3 of 5 readings rule)
        </div>
      )}
    </section>
  );
}
