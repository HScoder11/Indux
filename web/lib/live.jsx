"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useToast } from "./toast";

const LIVE_BUFFER = 150;    // readings kept while live (~95 s)
const PAUSED_BUFFER = 600;  // while paused keep buffering, so "back to live" loses nothing

const LiveCtx = createContext(null);
export const useLive = () => useContext(LiveCtx);

function wsUrl() {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  // `next dev` runs on :3000 and can't proxy WebSockets, so talk to the backend directly
  const host = location.port === "3000" ? `${location.hostname}:8000` : location.host;
  return `${proto}://${host}/ws/live`;
}

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.15, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.4);
  } catch { /* audio blocked until the user interacts */ }
}

/**
 * One WebSocket for the whole app (it lives in the root layout, so it survives
 * page changes). Exposes:
 *   latest     newest reading          frames   buffered full readings
 *   view       reading on screen: latest when live, or the one under the cursor
 *   cursor     null = live, else the ts being inspected (pause / rewind)
 *   history    scalar points for the trend charts
 */
export function LiveProvider({ children }) {
  const toast = useToast();
  const [frames, setFrames] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [conn, setConn] = useState("connecting");
  const [status, setStatus] = useState({ status: "starting" });
  const [sound, setSound] = useState(false);
  const cursorRef = useRef(null);
  const soundRef = useRef(false);
  const prevAlert = useRef(null);
  const listeners = useRef(new Set());

  useEffect(() => { cursorRef.current = cursor; }, [cursor]);
  useEffect(() => {
    try { setSound(localStorage.getItem("indux-sound") === "1"); } catch { /* private mode */ }
  }, []);
  useEffect(() => {
    soundRef.current = sound;
    try { localStorage.setItem("indux-sound", sound ? "1" : "0"); } catch { /* private mode */ }
  }, [sound]);

  const onReading = useCallback((msg) => {
    // alert start / change / end -> toast (+ optional beep)
    const cond = msg.alert ? msg.alert_condition : null;
    if (cond !== prevAlert.current) {
      if (cond) {
        toast({ zone: "red", title: `Fault detected: ${msg.alert_label}`,
          body: `Health ${msg.health == null ? "–" : Math.round(msg.health)} · ${Math.round(msg.confidence * 100)}% confidence`,
          href: "/alerts", linkText: "See alert", ttl: 9000 });
        if (soundRef.current) beep();
      } else if (prevAlert.current) {
        toast({ zone: "green", title: "Back to normal", body: "The alert has cleared." });
      }
      prevAlert.current = cond;
    }
    setFrames((fs) => {
      const cap = cursorRef.current == null ? LIVE_BUFFER : PAUSED_BUFFER;
      const next = fs.length >= cap ? fs.slice(fs.length - cap + 1) : fs.slice();
      next.push(msg);
      return next;
    });
  }, [toast]);

  useEffect(() => {
    let ws, timer, closed = false, retry = 0;
    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => { retry = 0; setConn("live"); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        listeners.current.forEach((fn) => fn(msg));
        if (msg.type === "status") { setStatus(msg); return; }
        if (msg.type === "alert_report") {
          toast({ zone: "calibrating", title: "AI report ready", body: `Written for alert #${msg.alert_id}`,
            href: `/reports?id=${msg.report_id}`, linkText: "Read report" });
          return;
        }
        if (msg.type !== "reading") return;
        setStatus((s) => (s.status === "live" ? s : { ...s, status: "live", error: null }));
        onReading(msg);
      };
      ws.onclose = () => {
        if (closed) return;
        setConn("offline");
        timer = setTimeout(connect, Math.min(5000, 500 * 2 ** retry++));
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws && ws.close(); };
  }, [onReading, toast]);

  const latest = frames.length ? frames[frames.length - 1] : null;
  const view = useMemo(() => {
    if (cursor == null) return latest;
    return frames.find((f) => f.ts === cursor) || frames[0] || null;
  }, [cursor, frames, latest]);

  const history = useMemo(() => frames.map((m) => ({
    t: m.ts, health: m.health, vib: m.vib_rms, current: m.current, temp: m.temp, alert: m.alert,
  })), [frames]);

  const value = useMemo(() => ({
    latest, view, frames, history, conn, status, cursor, sound,
    live: cursor == null,
    pause: () => setCursor((c) => c ?? latest?.ts ?? null),
    goLive: () => setCursor(null),
    inspect: (ts) => setCursor(ts),
    setSound,
    clearHistory: () => { setFrames([]); setCursor(null); },
    subscribe: (fn) => { listeners.current.add(fn); return () => listeners.current.delete(fn); },
  }), [latest, view, frames, history, conn, status, cursor, sound]);

  return <LiveCtx.Provider value={value}>{children}</LiveCtx.Provider>;
}
