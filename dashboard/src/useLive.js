import { useEffect, useRef, useState } from "react";

const BUFFER = 150; // readings kept for trend charts (~95 s)

export async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

/** Live WebSocket feed with automatic reconnect.
 *  Returns { last, history, conn, status } where conn is
 *  "connecting" | "live" | "offline" (backend unreachable). */
export function useLive() {
  const [last, setLast] = useState(null);
  const [history, setHistory] = useState([]);
  const [conn, setConn] = useState("connecting");
  const [status, setStatus] = useState({ status: "starting" });
  const retry = useRef(0);

  useEffect(() => {
    let ws;
    let timer;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/live`);
      ws.onopen = () => { retry.current = 0; setConn("live"); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "status") {
          setStatus(msg);
          return;
        }
        if (msg.type !== "reading") return;   // e.g. "alert_report" notices
        setStatus((s) => (s.status === "live" ? s : { ...s, status: "live", error: null }));
        setLast(msg);
        setHistory((h) => {
          const point = {
            t: msg.ts,
            health: msg.health,
            vib: msg.vib_rms,
            current: msg.current,
            temp: msg.temp,
            alert: msg.alert,
          };
          const next = h.length >= BUFFER ? h.slice(h.length - BUFFER + 1) : h.slice();
          next.push(point);
          return next;
        });
      };
      ws.onclose = () => {
        if (closed) return;
        setConn("offline");
        const wait = Math.min(5000, 500 * 2 ** retry.current++);
        timer = setTimeout(connect, wait);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => { closed = true; clearTimeout(timer); ws && ws.close(); };
  }, []);

  const clearHistory = () => setHistory([]);
  return { last, history, conn, status, clearHistory };
}
