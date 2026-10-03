"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, when } from "@/lib/api";
import { useLive } from "@/lib/live";
import { DownloadLinks, Markdown, engineLabel } from "@/components/Report";

function ReportsInner() {
  const { latest } = useLive();
  const params = useSearchParams();
  const router = useRouter();
  const [lang, setLang] = useState("en");
  const [rep, setRep] = useState(null);
  const [past, setPast] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("all");
  const selectedId = Number(params.get("id")) || null;

  const loadPast = useCallback(() => api("/api/reports?limit=100").then(setPast).catch(() => {}), []);
  useEffect(() => {
    loadPast();
    const t = setInterval(loadPast, 8000);
    return () => clearInterval(t);
  }, [loadPast]);

  // open the report named in the URL (?id=), or the newest one
  useEffect(() => {
    const id = selectedId || past[0]?.id;
    if (!id || rep?.id === id) return;
    api(`/api/reports/${id}`).then(setRep).catch((e) => setErr(e.message));
  }, [selectedId, past, rep?.id]);

  const open = (id) => router.replace(`/reports?id=${id}`, { scroll: false });
  const generate = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api("/api/report", { lang });
      await loadPast();
      open(r.id);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };

  const shown = past.filter((r) => filter === "all" || (filter === "alert" ? r.alert : !r.alert));

  return (
    <>
      <div className="page-head">
        <h1>AI maintenance reports</h1>
        <span className="sub">{past.length} saved</span>
      </div>
      <div className="reports-layout">
        <section className="card">
          <h2>New report</h2>
          <div className="sub" style={{ marginBottom: 10 }}>Written from the current readings, alerts and health trend.</div>
          <div className="row">
            <div className="seg" role="group" aria-label="Report language">
              <button aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button>
              <button aria-pressed={lang === "hi"} onClick={() => setLang("hi")}>हिंदी</button>
            </div>
            <button className="btn primary" onClick={generate} disabled={busy || !latest}>
              {busy ? "Writing report…" : "Generate AI report"}
            </button>
          </div>
          {err && <div className="error" role="alert">{err}</div>}

          <div className="chart-title" style={{ marginTop: 18 }}>
            <h2>Library</h2>
            <div className="seg" role="group" aria-label="Filter reports">
              {[["all", "All"], ["alert", "From alerts"], ["manual", "Manual"]].map(([k, l]) => (
                <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
              ))}
            </div>
          </div>
          {shown.length === 0 ? <div className="sub">No reports yet.</div> : (
            <ul className="report-list">
              {shown.map((r) => (
                <li key={r.id}>
                  <button className={`report-item ${rep?.id === r.id ? "on" : ""}`} onClick={() => open(r.id)}>
                    <span className="row" style={{ justifyContent: "space-between" }}>
                      <strong>{r.condition || "–"}{r.alert ? " ⚠" : ""}</strong>
                      <span className="sub num">#{r.id}</span>
                    </span>
                    <span className="sub">{when(r.ts)} · health {r.health == null ? "–" : Math.round(r.health)} · {r.lang === "hi" ? "हिंदी" : "EN"}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card report-view">
          {!rep ? <div className="sub">Select a report, or generate one.</div> : (
            <>
              <div className="chart-title">
                <h2>Report #{rep.id}</h2>
                <DownloadLinks id={rep.id} />
              </div>
              <div className="row">
                <span className="badge">{engineLabel(rep)}</span>
                <span className="sub">{when(rep.ts)}</span>
                {rep.condition && <span className="sub">· {rep.condition}</span>}
              </div>
              <Markdown text={rep.text} />
            </>
          )}
        </section>
      </div>
    </>
  );
}

export default function ReportsPage() {
  return <Suspense fallback={null}><ReportsInner /></Suspense>;
}
