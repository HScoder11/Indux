import { useEffect, useState } from "react";
import { useLive } from "./useLive.js";
import HealthGauge from "./components/HealthGauge.jsx";
import { Metrics, StatusCard, TtfCard, WhyPanel } from "./components/Panels.jsx";
import { FftChart, HealthTrend, TrendCharts, WaveChart } from "./components/Charts.jsx";
import { AlertsTable, Controls, ReportPanel } from "./components/Operate.jsx";
import Benchmarks from "./components/Benchmarks.jsx";

const MACHINE = "BLDC Motor #1";

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="clock">{now.toLocaleTimeString()}</span>;
}

function Connection({ conn, status }) {
  let color = "var(--muted)", text = "Connecting…";
  if (conn === "offline") { color = "var(--critical)"; text = "Backend offline"; }
  else if (status.status === "disconnected" || status.status === "error") {
    color = "var(--critical)"; text = `Sensor ${status.status}`;
  } else if (conn === "live") { color = "var(--good)"; text = "Live"; }
  return (
    <span className="conn" title={status.error || ""}>
      <span className="dot" style={{ background: color }} aria-hidden="true" />
      {text}
    </span>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("indux-theme") || "auto"; } catch { return "auto"; }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try { localStorage.setItem("indux-theme", theme); } catch { /* private mode */ }
  }, [theme]);
  const next = { auto: "light", light: "dark", dark: "auto" }[theme];
  return (
    <button className="icon-btn" onClick={() => setTheme(next)} title="Colour theme">
      Theme: {theme}
    </button>
  );
}

export default function App() {
  const { last, history, conn, status, clearHistory } = useLive();
  const [tab, setTab] = useState("live");

  return (
    <>
      <header className="topbar">
        <span className="brand">Indux<small>predictive maintenance</small></span>
        <span className="machine">{MACHINE}</span>
        <Connection conn={conn} status={status} />
        <span className="sub">{last?.source_info?.name}</span>
        <span className="spacer" />
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "live"} onClick={() => setTab("live")}>Live</button>
          <button role="tab" aria-selected={tab === "bench"} onClick={() => setTab("bench")}>Benchmarks</button>
        </div>
        <ThemeToggle />
        <Clock />
      </header>

      <main>
        {tab === "live" ? (
          <>
            {status.status === "disconnected" && (
              <div className="card" role="alert" style={{ marginBottom: 16, borderColor: "var(--critical)" }}>
                <strong>Sensor disconnected:</strong> {status.error}. Switch to the simulator or a replay in Demo controls.
              </div>
            )}
            <div className="grid">
              <div className="col">
                <HealthGauge last={last} conn={conn} />
                <HealthTrend history={history} />
                <Controls last={last} onSourceChange={clearHistory} />
              </div>
              <div className="col">
                <Metrics last={last} />
                <FftChart last={last} />
                <TrendCharts history={history} />
                <WaveChart last={last} />
              </div>
              <div className="col">
                <StatusCard last={last} conn={conn} />
                <WhyPanel last={last} />
                <TtfCard last={last} />
              </div>
            </div>
            <div className="bottom">
              <AlertsTable last={last} />
              <ReportPanel last={last} />
            </div>
          </>
        ) : (
          <Benchmarks />
        )}
      </main>
    </>
  );
}
