import { useCallback, useEffect, useState } from "react";
import { api } from "../useLive.js";

/* ---------------- source + fault controls ---------------- */
const FAULTS = [
  ["healthy", "Healthy"], ["unbalance", "Unbalance"], ["looseness", "Looseness"],
  ["bearing", "Bearing"], ["overload", "Overload"], ["degrade", "Gradual wear"],
];

export function Controls({ last, onSourceChange }) {
  const [sources, setSources] = useState({ recordings: [], serial_ports: [] });
  const [kind, setKind] = useState("sim");
  const [file, setFile] = useState("");
  const [port, setPort] = useState("");
  const [rpm, setRpm] = useState(5000);
  const [severity, setSeverity] = useState(0.8);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api("/api/sources").then((s) => {
    setSources(s);
    setKind(s.current.kind);
    if (!file && s.recordings[0]) setFile(s.recordings[0].file);
    if (!port && s.serial_ports[0]) setPort(s.serial_ports[0]);
  }).catch(() => {}), [file, port]);
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const info = last?.source_info;
  const isSim = info?.kind === "sim";
  const current = info?.condition;

  const apply = async () => {
    setErr(""); setBusy(true);
    try {
      await api("/api/source", { kind, rpm: Number(rpm), file, port });
      onSourceChange?.();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const inject = async (condition) => {
    setErr("");
    try { await api("/api/fault", { condition, severity: Number(severity) }); } catch (e) { setErr(e.message); }
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
        <button className="btn primary" onClick={apply} disabled={busy}>Switch</button>
      </div>
      {kind === "sim" && (
        <div style={{ marginTop: 8 }}>
          <label htmlFor="rpm">Motor speed: {rpm} rpm</label>
          <input id="rpm" type="range" min="3000" max="7000" step="500" value={rpm}
            onChange={(e) => setRpm(e.target.value)} style={{ width: "100%" }} />
        </div>
      )}
      {kind === "replay" && (
        <div style={{ marginTop: 8 }}>
          <label htmlFor="file">Recording</label>
          <select id="file" value={file} onChange={(e) => setFile(e.target.value)} onFocus={load}>
            {sources.recordings.length === 0 && <option value="">No recordings in data/sim/</option>}
            {sources.recordings.map((r) => <option key={r.file} value={r.file}>{r.file}</option>)}
          </select>
        </div>
      )}
      {kind === "serial" && (
        <div style={{ marginTop: 8 }}>
          <label htmlFor="port">Serial port</label>
          <input id="port" type="text" value={port} placeholder="e.g. COM5" onChange={(e) => setPort(e.target.value)}
            list="ports" onFocus={load} />
          <datalist id="ports">{sources.serial_ports.map((p) => <option key={p} value={p} />)}</datalist>
        </div>
      )}

      <div style={{ marginTop: 14 }}>
        <label>Inject a fault {isSim ? "" : "(simulator only)"}</label>
        <div className="fault-grid">
          {FAULTS.map(([k, label]) => (
            <button key={k} className="btn" disabled={!isSim} aria-pressed={isSim && current === k}
              onClick={() => inject(k)}>{label}</button>
          ))}
        </div>
        <label htmlFor="sev" style={{ marginTop: 10 }}>Fault severity: {Math.round(severity * 100)}%</label>
        <input id="sev" type="range" min="0.1" max="1" step="0.1" value={severity} disabled={!isSim}
          onChange={(e) => setSeverity(e.target.value)} style={{ width: "100%" }} />
        <div className="hint">Current source: {info?.name || "–"}</div>
      </div>
      {err && <div className="error" role="alert">{err}</div>}
    </section>
  );
}

/* ---------------- alert history ---------------- */
function EmailStatus() {
  const [st, setSt] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/api/notify/status").then(setSt).catch(() => {}); }, []);
  if (!st) return null;
  const test = async () => {
    setBusy(true); setMsg("");
    try { const r = await api("/api/notify/test", {}); setMsg(`Test email sent to ${r.to.join(", ")}`); }
    catch (e) { setMsg(`Failed: ${e.message}`); }
    setBusy(false);
  };
  return (
    <div className="row" style={{ marginBottom: 10 }}>
      {st.configured ? (
        <>
          <span className="badge">✉ Email alerts ON → {st.to.join(", ")}</span>
          <button className="btn small" onClick={test} disabled={busy}>{busy ? "Sending…" : "Send test email"}</button>
        </>
      ) : (
        <span className="sub">✉ Email alerts off — add SMTP settings to .env (see README)</span>
      )}
      {!st.auto_report && <span className="sub">Auto-report off (AUTO_REPORT=0)</span>}
      {msg && <span className="sub">{msg}</span>}
    </div>
  );
}

function emailCell(s) {
  if (!s) return "…";
  if (s.startsWith("sent")) return `✓ ${s}`;
  if (s === "email not configured") return "–";
  return s;
}

export function AlertsTable({ last }) {
  const [rows, setRows] = useState([]);
  const alertId = last?.active_alert_id;
  useEffect(() => {
    const get = () => api("/api/alerts?limit=30").then(setRows).catch(() => {});
    get();
    const t = setInterval(get, 4000);
    return () => clearInterval(t);
  }, [alertId]);

  const time = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return (
    <section className="card">
      <h2>Alert history</h2>
      <EmailStatus />
      {rows.length === 0 ? <div className="sub">No alerts yet.</div> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Time</th><th>Fault</th><th>Health</th><th>Recommended action</th><th>State</th><th>Files</th><th>Email</th></tr></thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="num">{time(a.ts)}</td>
                  <td><strong>{a.label}</strong></td>
                  <td className="num">{a.health == null ? "–" : Math.round(a.health)}</td>
                  <td>{a.action}</td>
                  <td>{a.resolved_ts ? `Resolved ${time(a.resolved_ts)}` : <span className="badge">● Active</span>}</td>
                  <td>
                    <span className="row" style={{ gap: 6 }}>
                      {a.report_id
                        ? <a className="btn small" href={`/api/reports/${a.report_id}/download?format=html&inline=1`} target="_blank" rel="noreferrer">Report</a>
                        : <span className="sub">report…</span>}
                      {a.event_file && (
                        <a className="btn small" href={`/api/${a.event_file}`} download
                          title="Raw sensor data: 30 s before to 15 s after the alert (replayable)">Sensor data</a>
                      )}
                    </span>
                  </td>
                  <td className="sub">{emailCell(a.email_status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/* ---------------- AI report ---------------- */
// Tiny markdown renderer: headings, bullets, bold, italics. Builds React
// elements (no innerHTML), so model output can never inject HTML.
function inline(text, key) {
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).filter(Boolean);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={`${key}-${i}`}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("_") && p.endsWith("_") && p.length > 2) return <em key={`${key}-${i}`}>{p.slice(1, -1)}</em>;
    return p;
  });
}
function Markdown({ text }) {
  const out = [];
  let list = [];
  const flush = () => {
    if (list.length) out.push(<ul key={`ul${out.length}`}>{list}</ul>);
    list = [];
  };
  text.split("\n").forEach((raw, i) => {
    const line = raw.trim();
    if (!line) { flush(); return; }
    const bullet = line.match(/^[-*•]\s+(.*)/);
    if (bullet) { list.push(<li key={i}>{inline(bullet[1], i)}</li>); return; }
    flush();
    const heading = line.match(/^#{1,6}\s+(.*)/) || line.match(/^(\d+\.\s+.*)$/);
    if (heading) out.push(<h4 key={i}>{inline(heading[1].replace(/\*\*/g, ""), i)}</h4>);
    else out.push(<p key={i}>{inline(line, i)}</p>);
  });
  flush();
  return <div className="report-body">{out}</div>;
}

const ENGINE = { claude: "Claude", gemini: "Gemini", template: "Offline template" };
const engineLabel = (r) => (r.engine === "template" ? ENGINE.template : `${ENGINE[r.engine] || r.engine} · ${r.model}`);
const when = (ts) => new Date(ts * 1000).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

function DownloadLinks({ id }) {
  if (!id) return null;
  const base = `/api/reports/${id}/download`;
  return (
    <span className="row" style={{ gap: 8 }}>
      <a className="btn small" href={`${base}?format=html&inline=1`} target="_blank" rel="noreferrer">PDF / Print</a>
      <a className="btn small" href={`${base}?format=txt`} download>TXT</a>
      <a className="btn small" href={`${base}?format=md`} download>MD</a>
    </span>
  );
}

export function ReportPanel({ last }) {
  const [lang, setLang] = useState("en");
  const [rep, setRep] = useState(null);          // report on screen
  const [past, setPast] = useState([]);          // previous reports (metadata)
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const loadPast = useCallback(() => api("/api/reports?limit=30").then(setPast).catch(() => {}), []);
  useEffect(() => {                              // auto-reports from alerts appear here too
    loadPast();
    const t = setInterval(loadPast, 8000);
    return () => clearInterval(t);
  }, [loadPast]);

  const generate = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api("/api/report", { lang });
      setRep({ ...r, text: r.report, ts: r.generated_at });
      loadPast();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const open = async (id) => {
    setErr("");
    try { setRep(await api(`/api/reports/${id}`)); } catch (e) { setErr(e.message); }
  };

  return (
    <section className="card">
      <div className="chart-title">
        <h2>AI maintenance report</h2>
        <div className="seg" role="group" aria-label="Report language">
          <button aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
          <button aria-pressed={lang === "hi"} onClick={() => setLang("hi")}>हिंदी</button>
        </div>
      </div>
      <button className="btn primary" onClick={generate} disabled={busy || !last}>
        {busy ? "Writing report…" : "Generate AI report"}
      </button>
      {err && <div className="error" role="alert">{err}</div>}

      {rep && (
        <>
          <div className="row" style={{ marginTop: 12 }}>
            <span className="badge">{engineLabel(rep)}</span>
            <span className="sub">#{rep.id} · {when(rep.ts)}</span>
            {rep.cached && <span className="sub">(same situation within a minute - reused)</span>}
            {rep.note && <span className="sub">{rep.note}</span>}
          </div>
          <div style={{ marginTop: 8 }}><DownloadLinks id={rep.id} /></div>
          <Markdown text={rep.text} />
        </>
      )}

      <h2 style={{ marginTop: 18 }}>Previous reports</h2>
      {past.length === 0 ? <div className="sub">No reports yet.</div> : (
        <div className="table-wrap" style={{ maxHeight: 260 }}>
          <table>
            <thead><tr><th>When</th><th>Condition</th><th>Health</th><th>Lang</th><th>Download</th></tr></thead>
            <tbody>
              {past.map((r) => (
                <tr key={r.id} aria-current={rep?.id === r.id ? "true" : undefined}>
                  <td className="num">
                    <button className="link-btn" onClick={() => open(r.id)} title="Show this report">{when(r.ts)}</button>
                  </td>
                  <td>{r.condition || "–"}{r.alert ? " ⚠" : ""}</td>
                  <td className="num">{r.health == null ? "–" : Math.round(r.health)}</td>
                  <td>{r.lang === "hi" ? "हिंदी" : "EN"}</td>
                  <td><DownloadLinks id={r.id} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
