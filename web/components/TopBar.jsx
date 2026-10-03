"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useLive } from "@/lib/live";

const MACHINE = "BLDC Motor #1";
const NAV = [["/", "Live"], ["/alerts", "Alerts"], ["/reports", "Reports"], ["/benchmarks", "Benchmarks"]];

function Clock() {
  const [now, setNow] = useState(null);   // client only: avoids a server/client time mismatch
  useEffect(() => {
    setNow(new Date());
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="clock">{now ? now.toLocaleTimeString() : ""}</span>;
}

function Connection() {
  const { conn, status, latest } = useLive();
  let color = "var(--muted)", text = "Connecting…";
  if (conn === "offline") { color = "var(--critical)"; text = "Backend offline"; }
  else if (status.status === "disconnected" || status.status === "error") { color = "var(--critical)"; text = `Sensor ${status.status}`; }
  else if (conn === "live") { color = "var(--good)"; text = "Live"; }
  return (
    <span className="conn" title={status.error || latest?.source_info?.name || ""}>
      <span className="dot" style={{ background: color }} aria-hidden="true" />
      {text}
      {latest?.source_info?.name && <span className="sub src-name">· {latest.source_info.name}</span>}
    </span>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState("auto");
  useEffect(() => {
    try { setTheme(localStorage.getItem("indux-theme") || "auto"); } catch { /* private mode */ }
  }, []);
  const choose = (t) => {
    setTheme(t);
    const root = document.documentElement;
    if (t === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t);
    try { localStorage.setItem("indux-theme", t); } catch { /* private mode */ }
  };
  const next = { auto: "light", light: "dark", dark: "auto" }[theme];
  const icon = { auto: "◐", light: "☀", dark: "☾" }[theme];
  return <button className="icon-btn" onClick={() => choose(next)} title={`Theme: ${theme} (click for ${next})`}>{icon}</button>;
}

function SoundToggle() {
  const { sound, setSound } = useLive();
  return (
    <button className="icon-btn" onClick={() => setSound(!sound)} aria-pressed={sound} title={sound ? "Alert sound on" : "Alert sound off"}>
      {sound ? "🔔" : "🔕"}
    </button>
  );
}

export default function TopBar({ onHelp }) {
  const path = usePathname();
  const { latest } = useLive();
  const alerting = !!latest?.alert;
  return (
    <header className="topbar">
      <Link href="/" className="brand">Indux<small>predictive maintenance</small></Link>
      <span className="machine">{MACHINE}</span>
      <Connection />
      <span className="spacer" />
      <nav className="tabs" aria-label="Pages">
        {NAV.map(([href, label]) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <Link key={href} href={href} aria-current={active ? "page" : undefined}>
              {label}
              {href === "/alerts" && alerting && <span className="nav-dot" aria-label="active alert" />}
            </Link>
          );
        })}
      </nav>
      <SoundToggle />
      <ThemeToggle />
      <button className="icon-btn" onClick={onHelp} title="Keyboard shortcuts (?)">?</button>
      <Clock />
    </header>
  );
}
