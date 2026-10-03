"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, clock } from "@/lib/api";
import { useLive } from "@/lib/live";
import HealthGauge from "@/components/HealthGauge";
import { Metrics, ProbBars, StatusCard, TtfCard, WhyPanel } from "@/components/Panels";
import { FftChart, HealthTrend, TrendCharts, WaveChart } from "@/components/Charts";
import { Autopilot, Controls } from "@/components/Controls";
import Timeline from "@/components/Timeline";
import { StatusIcon } from "@/components/StatusIcon";

function RecentAlerts() {
  const { latest } = useLive();
  const [rows, setRows] = useState([]);
  const alertId = latest?.active_alert_id;
  useEffect(() => {
    const get = () => api("/api/alerts?limit=5").then(setRows).catch(() => {});
    get();
    const t = setInterval(get, 5000);
    return () => clearInterval(t);
  }, [alertId]);
  return (
    <section className="card">
      <div className="chart-title">
        <h2>Recent alerts</h2>
        <Link className="link-btn" href="/alerts">All alerts →</Link>
      </div>
      {rows.length === 0 ? <div className="sub">No alerts yet. Try pressing 2 to inject unbalance.</div> : (
        <ul className="mini-list">
          {rows.map((a) => (
            <li key={a.id}>
              <Link href={`/alerts?id=${a.id}`} className="mini-row">
                <StatusIcon zone={a.resolved_ts ? "green" : "red"} size={16} />
                <strong>{a.label}</strong>
                <span className="sub num">{clock(a.ts)}</span>
                <span className="sub">{a.resolved_ts ? "resolved" : "active"}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function LivePage() {
  const { view, history, conn, status, cursor, inspect } = useLive();
  return (
    <>
      {status.status === "disconnected" && (
        <div className="card banner" role="alert">
          <strong>Sensor disconnected:</strong> {status.error}. Switch to the simulator or a replay in Demo controls.
        </div>
      )}
      <Timeline />
      <div className="grid">
        <div className="col">
          <HealthGauge last={view} conn={conn} />
          <HealthTrend history={history} cursor={cursor} inspect={inspect} />
          <Controls />
          <Autopilot />
        </div>
        <div className="col">
          <Metrics last={view} />
          <FftChart last={view} />
          <TrendCharts history={history} cursor={cursor} inspect={inspect} />
          <WaveChart last={view} />
        </div>
        <div className="col">
          <StatusCard last={view} conn={conn} />
          <ProbBars last={view} />
          <WhyPanel last={view} />
          <TtfCard last={view} />
          <RecentAlerts />
        </div>
      </div>
    </>
  );
}
