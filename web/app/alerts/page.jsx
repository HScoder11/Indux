"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, clock, when } from "@/lib/api";
import { useLive } from "@/lib/live";
import { useToast } from "@/lib/toast";
import { StatusIcon } from "@/components/StatusIcon";
import { DownloadLinks, Markdown, engineLabel } from "@/components/Report";

function duration(a) {
  const end = a.resolved_ts ?? Date.now() / 1000;
  const s = Math.max(0, end - a.ts);
  return s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;
}
function emailCell(s) {
  if (!s) return "…";
  if (s.startsWith("sent")) return `✓ ${s}`;
  if (s === "email not configured") return "–";
  return s;
}

function Drawer({ alert, onClose }) {
  const router = useRouter();
  const toast = useToast();
  const { clearHistory } = useLive();
  const [rep, setRep] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setRep(null);
    if (alert?.report_id) api(`/api/reports/${alert.report_id}`).then(setRep).catch(() => {});
  }, [alert?.report_id]);

  if (!alert) return null;
  const replay = async () => {
    setBusy(true);
    try {
      await api("/api/source", { kind: "replay", file: alert.event_file });
      clearHistory();
      toast({ zone: "calibrating", title: "Replaying the black-box recording", body: "30 s before to 15 s after the alert." });
      router.push("/");
    } catch (e) {
      toast({ zone: "red", title: "Replay failed", body: e.message });
    }
    setBusy(false);
  };

  return (
    <div className="overlay drawer-overlay" onClick={onClose}>
      <aside className="drawer card" role="dialog" aria-modal="true" aria-label={`Alert ${alert.id}`} onClick={(e) => e.stopPropagation()}>
        <div className="chart-title">
          <h2>Alert #{alert.id}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
          <StatusIcon zone={alert.resolved_ts ? "green" : "red"} size={30} />
          <div>
            <div className="cond">{alert.label}</div>
            <div className="sub">
              {when(alert.ts)} · lasted {duration(alert)} · {alert.resolved_ts ? "resolved" : "still active"}
            </div>
          </div>
        </div>
        <dl className="facts">
          <dt>Health at alert</dt><dd>{alert.health == null ? "–" : Math.round(alert.health)} / 100</dd>
          <dt>Confidence</dt><dd>{alert.confidence == null ? "–" : `${Math.round(alert.confidence * 100)}%`}</dd>
          <dt>Source</dt><dd>{alert.source || "–"}</dd>
          <dt>Email</dt><dd>{emailCell(alert.email_status)}</dd>
        </dl>
        <h3 className="sec">Recommended action</h3>
        <p style={{ marginTop: 4 }}>{alert.action}</p>
        {alert.reasons?.length > 0 && (
          <>
            <h3 className="sec">Top signals at the time</h3>
            <ul className="reasons">
              {alert.reasons.map((r) => (
                <li key={r.feature}><strong>{r.label}</strong>: {r.value} <span className="sub">(normal {r.normal}, {Math.abs(r.z).toFixed(1)}× {r.direction})</span></li>
              ))}
            </ul>
          </>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          {alert.event_file && (
            <>
              <button className="btn primary" onClick={replay} disabled={busy}>{busy ? "Starting…" : "▶ Replay this event"}</button>
              <a className="btn" href={`/api/${alert.event_file}`} download>Sensor data CSV</a>
            </>
          )}
        </div>
        <h3 className="sec">AI report</h3>
        {!alert.report_id && <div className="sub">Report is being written…</div>}
        {rep && (
          <>
            <div className="row"><span className="badge">{engineLabel(rep)}</span><DownloadLinks id={rep.id} /></div>
            <Markdown text={rep.text} />
          </>
        )}
      </aside>
    </div>
  );
}

function AlertsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const [rows, setRows] = useState(null);
  const [type, setType] = useState("all");
  const [state, setState] = useState("all");
  const [q, setQ] = useState("");
  const selectedId = Number(params.get("id")) || null;

  useEffect(() => {
    const get = () => api("/api/alerts?limit=200").then(setRows).catch(() => setRows((r) => r ?? []));
    get();
    const t = setInterval(get, 4000);
    return () => clearInterval(t);
  }, []);

  const counts = useMemo(() => {
    const c = {};
    (rows || []).forEach((a) => { c[a.label] = (c[a.label] || 0) + 1; });
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [rows]);
  const maxCount = Math.max(1, ...counts.map(([, n]) => n));

  const shown = (rows || []).filter((a) =>
    (type === "all" || a.label === type) &&
    (state === "all" || (state === "active" ? !a.resolved_ts : !!a.resolved_ts)) &&
    (!q || `${a.label} ${a.action} ${a.source}`.toLowerCase().includes(q.toLowerCase())));
  const active = (rows || []).filter((a) => !a.resolved_ts).length;
  const select = (id) => router.replace(id ? `/alerts?id=${id}` : "/alerts", { scroll: false });
  const selected = (rows || []).find((a) => a.id === selectedId);

  return (
    <>
      <div className="page-head">
        <h1>Alerts</h1>
        <span className="sub">{rows ? `${rows.length} recorded · ${active} active` : "Loading…"}</span>
      </div>

      {counts.length > 0 && (
        <section className="card">
          <h2>By fault type</h2>
          <div className="type-bars">
            {counts.map(([label, n]) => (
              <button key={label} className={`type-bar ${type === label ? "on" : ""}`} onClick={() => setType(type === label ? "all" : label)} aria-pressed={type === label}>
                <span className="name">{label}</span>
                <span className="prob-bar"><span style={{ width: `${(n / maxCount) * 100}%` }} /></span>
                <span className="num">{n}</span>
              </button>
            ))}
          </div>
          <div className="hint">Click a bar to filter the table.</div>
        </section>
      )}

      <section className="card" style={{ marginTop: 16 }}>
        <div className="filters">
          <div className="seg" role="group" aria-label="State">
            {["all", "active", "resolved"].map((s) => (
              <button key={s} aria-pressed={state === s} onClick={() => setState(s)}>{s[0].toUpperCase() + s.slice(1)}</button>
            ))}
          </div>
          <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Fault type">
            <option value="all">All fault types</option>
            {counts.map(([label]) => <option key={label} value={label}>{label}</option>)}
          </select>
          <input type="search" placeholder="Search action, source…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search alerts" />
          {(type !== "all" || state !== "all" || q) && (
            <button className="link-btn" onClick={() => { setType("all"); setState("all"); setQ(""); }}>Clear filters</button>
          )}
        </div>
        {rows && shown.length === 0 && <div className="sub" style={{ padding: 12 }}>No alerts match.</div>}
        {shown.length > 0 && (
          <div className="table-wrap tall">
            <table>
              <thead><tr><th>Time</th><th>Fault</th><th>Health</th><th>Lasted</th><th>Recommended action</th><th>State</th><th>Report</th></tr></thead>
              <tbody>
                {shown.map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => select(a.id)} aria-current={a.id === selectedId ? "true" : undefined}>
                    <td className="num">{when(a.ts)}</td>
                    <td><strong>{a.label}</strong></td>
                    <td className="num">{a.health == null ? "–" : Math.round(a.health)}</td>
                    <td className="num">{duration(a)}</td>
                    <td className="action-cell">{a.action}</td>
                    <td>{a.resolved_ts ? <span className="sub">Resolved {clock(a.resolved_ts)}</span> : <span className="badge alert-badge">● Active</span>}</td>
                    <td>{a.report_id ? "✓" : <span className="sub">…</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Drawer alert={selected} onClose={() => select(null)} />
    </>
  );
}

export default function AlertsPage() {
  return <Suspense fallback={null}><AlertsInner /></Suspense>;
}
