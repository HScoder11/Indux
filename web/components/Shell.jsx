"use client";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { FAULTS, injectFault } from "@/lib/api";
import { LiveProvider, useLive } from "@/lib/live";
import { ToastProvider, useToast } from "@/lib/toast";
import TopBar from "./TopBar";

const SHORTCUTS = [
  ...FAULTS.map((f) => [f.hotkey, `Inject: ${f.label}`]),
  ["Space", "Pause / resume the live view (Live page)"],
  ["← →", "Step through readings (when paused)"],
  ["L", "Back to live"],
  ["G then A / R / B", "Go to Alerts / Reports / Benchmarks (G then L for Live)"],
  ["?", "Show this help"],
];

function HelpDialog({ open, onClose }) {
  if (!open) return null;
  return (
    <div className="overlay" onClick={onClose}>
      <div className="card dialog" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}>
        <div className="chart-title">
          <h2>Keyboard shortcuts</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <table>
          <tbody>
            {SHORTCUTS.map(([k, d]) => <tr key={k}><td><kbd>{k}</kbd></td><td>{d}</td></tr>)}
          </tbody>
        </table>
        <div className="hint">Fault keys work on any page while the simulator is the source.</div>
      </div>
    </div>
  );
}

function Shortcuts({ onHelp, onEscape }) {
  const live = useLive();
  const toast = useToast();
  const router = useRouter();
  const path = usePathname();

  useEffect(() => {
    let gPressed = 0;
    const onKey = (e) => {
      if (e.key === "Escape") { onEscape(); return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target.closest("input, select, textarea, [contenteditable]")) return;
      const k = e.key;
      if (gPressed && Date.now() - gPressed < 1200) {
        gPressed = 0;
        const to = { a: "/alerts", r: "/reports", b: "/benchmarks", l: "/" }[k.toLowerCase()];
        if (to) { router.push(to); e.preventDefault(); }
        return;
      }
      if (k.toLowerCase() === "g") { gPressed = Date.now(); return; }
      if (k === "?") { onHelp(); return; }
      const fault = FAULTS.find((f) => f.hotkey === k);
      if (fault) {
        if (live.latest?.source_info?.kind !== "sim") {
          toast({ zone: "yellow", title: "Fault keys need the simulator", body: "Switch the data source to Simulator." });
          return;
        }
        injectFault(fault.key, 0.8)
          .then(() => toast({ zone: "calibrating", title: `Injected: ${fault.label}`, ttl: 2500 }))
          .catch((err) => toast({ zone: "red", title: "Could not inject fault", body: err.message }));
        return;
      }
      if (path !== "/") return;                       // pause / rewind keys belong to the Live page
      if (k === " ") { e.preventDefault(); live.live ? live.pause() : live.goLive(); return; }
      if (k.toLowerCase() === "l") { live.goLive(); return; }
      if ((k === "ArrowLeft" || k === "ArrowRight") && live.frames.length) {
        e.preventDefault();
        const idx = live.live ? live.frames.length - 1 : live.frames.findIndex((f) => f.ts === live.cursor);
        const j = Math.min(live.frames.length - 1, Math.max(0, idx + (k === "ArrowLeft" ? -1 : 1)));
        if (j === live.frames.length - 1 && k === "ArrowRight") live.goLive(); else live.inspect(live.frames[j].ts);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [live, toast, router, path, onHelp, onEscape]);
  return null;
}

export default function Shell({ children }) {
  const [help, setHelp] = useState(false);
  const toggleHelp = useCallback(() => setHelp((v) => !v), []);
  const closeHelp = useCallback(() => setHelp(false), []);
  return (
    <ToastProvider>
      <LiveProvider>
        <TopBar onHelp={() => setHelp(true)} />
        <Shortcuts onHelp={toggleHelp} onEscape={closeHelp} />
        <main>{children}</main>
        <HelpDialog open={help} onClose={closeHelp} />
      </LiveProvider>
    </ToastProvider>
  );
}
