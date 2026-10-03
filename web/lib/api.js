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

export const FAULTS = [
  { key: "healthy", label: "Healthy", hotkey: "1" },
  { key: "unbalance", label: "Unbalance", hotkey: "2" },
  { key: "looseness", label: "Looseness", hotkey: "3" },
  { key: "bearing", label: "Bearing", hotkey: "4" },
  { key: "overload", label: "Overload", hotkey: "5" },
  { key: "degrade", label: "Gradual wear", hotkey: "6" },
];

export const injectFault = (condition, severity) => api("/api/fault", { condition, severity });

export function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function when(ts) {
  return new Date(ts * 1000).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmt(v, d = 1) {
  return v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d);
}

export function ago(seconds) {
  if (seconds < 1.5) return "now";
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  return `${Math.round(seconds / 60)} min ago`;
}
