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
          {alert.event_file ? (
            <>
              <button className="btn primary" onClick={replay} disabled={busy}>{busy ? "Starting…" : "▶ Replay this event"}</button>
              <a className="btn" href={`/api/${alert.event_file}`} download>Sensor data CSV</a>
            </>
          ) : (
            <span className="sub">Black-box recording is being saved…</span>
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

function GmailConfigModal({ current, onClose, onSaved }) {
  const toast = useToast();
  const [provider, setProvider] = useState(current?.provider === "smtp" ? "smtp" : "gmail");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [to, setTo] = useState(current?.recipients?.join(", ") || current?.to?.join(", ") || "");
  const [host, setHost] = useState(current?.host || "smtp.gmail.com");
  const [port, setPort] = useState(current?.port || 587);
  const [testNow, setTestNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const handleProviderChange = (p) => {
    setProvider(p);
    if (p === "gmail") {
      setHost("smtp.gmail.com");
      setPort(587);
    }
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);

    try {
      const payload = {
        provider,
        user: user.trim(),
        password: password.trim(),
        to: to.trim(),
        host: provider === "gmail" ? "smtp.gmail.com" : host.trim(),
        port: Number(port) || 587,
        test_now: testNow,
        save_env: true,
      };

      const res = await api("/api/notify/config", payload);
      toast({
        zone: "green",
        title: "Alerts Configured",
        body: testNow ? "Gmail connection verified and test message sent!" : "Settings saved successfully."
      });
      onSaved(res);
    } catch (err) {
      setError(err.message || "Failed to configure email alerts.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose} style={{ zIndex: 100 }}>
      <div
        className="card dialog"
        role="dialog"
        aria-modal="true"
        aria-label="Configure Gmail Alerts"
        onClick={(e) => e.stopPropagation()}
        style={{ width: "min(560px, 95vw)" }}
      >
        <div className="chart-title" style={{ marginBottom: 12 }}>
          <h2>Configure Email &amp; Gmail Alerts</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>

        <form onSubmit={handleSave}>
          <div style={{ marginBottom: 16 }}>
            <label className="sub" style={{ display: "block", marginBottom: 6, fontWeight: 600 }}>Email Service</label>
            <div className="seg" role="group">
              <button
                type="button"
                aria-pressed={provider === "gmail"}
                onClick={() => handleProviderChange("gmail")}
              >
                Gmail (Recommended)
              </button>
              <button
                type="button"
                aria-pressed={provider === "smtp"}
                onClick={() => handleProviderChange("smtp")}
              >
                Custom SMTP
              </button>
            </div>
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
              {provider === "gmail" ? "Your Gmail Address" : "SMTP Username / Email"}
            </label>
            <input
              type="email"
              required
              placeholder={provider === "gmail" ? "maintenance.team@gmail.com" : "alerts@company.com"}
              value={user}
              onChange={(e) => setUser(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--axis)", background: "var(--surface)", color: "var(--ink)" }}
            />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
              {provider === "gmail" ? "Google 16-Character App Password" : "SMTP Password"}
            </label>
            <input
              type="password"
              required
              placeholder={provider === "gmail" ? "abcd efgh ijkl mnop" : "••••••••"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--axis)", background: "var(--surface)", color: "var(--ink)" }}
            />
            {provider === "gmail" && (
              <div className="hint" style={{ marginTop: 6, lineHeight: 1.45 }}>
                Google requires a 16-character <strong>App Password</strong>. (Normal Gmail passwords will be rejected by Google SMTP).
                <br />
                <a
                  href="https://myaccount.google.com/apppasswords"
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "var(--accent)", textDecoration: "underline", display: "inline-block", marginTop: 2 }}
                >
                  Generate Google App Password ↗
                </a>
                <span style={{ marginLeft: 6, color: "var(--muted)" }}>(Spaces are removed automatically)</span>
              </div>
            )}
          </div>

          <div style={{ marginBottom: 14 }}>
            <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
              Alert Recipients (To)
            </label>
            <input
              type="text"
              required
              placeholder="operator@plant.com, engineer@plant.com"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              style={{ width: "100%", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--axis)", background: "var(--surface)", color: "var(--ink)" }}
            />
            <div className="hint">Comma-separated email addresses that will receive alerts.</div>
          </div>

          {provider === "smtp" && (
            <div className="row" style={{ gap: 12, marginBottom: 14 }}>
              <div style={{ flex: 2 }}>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>SMTP Host</label>
                <input
                  type="text"
                  required
                  placeholder="smtp.example.com"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--axis)", background: "var(--surface)", color: "var(--ink)" }}
                />
              </div>
              <div style={{ flex: 1 }}>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>Port</label>
                <input
                  type="number"
                  required
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  style={{ width: "100%", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--axis)", background: "var(--surface)", color: "var(--ink)" }}
                />
              </div>
            </div>
          )}

          <div style={{ marginBottom: 18 }}>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 14 }}>
              <input
                type="checkbox"
                checked={testNow}
                onChange={(e) => setTestNow(e.target.checked)}
              />
              Send a test email now to verify connection &amp; delivery
            </label>
          </div>

          {error && (
            <div
              style={{
                background: "rgba(239, 68, 68, 0.1)",
                border: "1px solid var(--critical)",
                color: "var(--critical)",
                padding: "10px 14px",
                borderRadius: 8,
                fontSize: 13,
                marginBottom: 16,
                lineHeight: 1.4
              }}
            >
              <strong>Configuration Failed:</strong> {error}
            </div>
          )}

          <div className="row" style={{ justifyContent: "flex-end", gap: 10 }}>
            <button type="button" className="btn" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={busy}>
              {busy ? (testNow ? "Verifying & Sending…" : "Saving…") : "Save & Verify"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function EmailAlertsCard() {
  const [notify, setNotify] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const toast = useToast();

  const loadStatus = () => {
    api("/api/notify/status").then(setNotify).catch(() => {});
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const sendTest = async () => {
    setTesting(true);
    try {
      const res = await api("/api/notify/test", {});
      toast({
        zone: "green",
        title: "Test email dispatched",
        body: `Sent to ${res.to?.join(", ") || "recipients"}. Check your inbox.`
      });
    } catch (e) {
      toast({
        zone: "red",
        title: "Test email failed",
        body: e.message
      });
    }
    setTesting(false);
  };

  const isConfigured = notify?.configured;
  const isGmail = notify?.provider === "gmail";

  return (
    <>
      <section className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h2 style={{ margin: 0 }}>Gmail &amp; Email Alerts</h2>
              <span className="badge" style={isConfigured ? { background: "rgba(34, 197, 94, 0.15)", color: "#16a34a", borderColor: "rgba(34, 197, 94, 0.3)" } : {}}>
                {isConfigured ? (isGmail ? "✓ Gmail Active" : "✓ SMTP Active") : "● Not Configured"}
              </span>
            </div>
            <div className="sub" style={{ marginTop: 6, maxWidth: 640 }}>
              {isConfigured ? (
                <>
                  Sender: <strong>{notify.user}</strong> &bull; Recipients: <strong>{notify.to?.join(", ") || "–"}</strong>
                  {notify.cooldown_min ? ` &bull; ${notify.cooldown_min}m fault cooldown` : ""}
                </>
              ) : (
                "Receive instant Gmail alerts with AI diagnostic reports and sensor CSV attachments as soon as motor anomalies or faults occur."
              )}
            </div>
          </div>
          <div className="row" style={{ gap: 8 }}>
            {isConfigured && (
              <button className="btn" onClick={sendTest} disabled={testing}>
                {testing ? "Sending Test…" : "✉ Send Test Email"}
              </button>
            )}
            <button className={`btn ${isConfigured ? "" : "primary"}`} onClick={() => setModalOpen(true)}>
              {isConfigured ? "Edit Gmail Settings" : "⚙ Configure Gmail"}
            </button>
          </div>
        </div>
      </section>

      {modalOpen && (
        <GmailConfigModal
          current={notify}
          onClose={() => setModalOpen(false)}
          onSaved={(newStatus) => {
            setNotify(newStatus);
            setModalOpen(false);
          }}
        />
      )}
    </>
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

      <EmailAlertsCard />

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
