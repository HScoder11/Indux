"use client";
// Status is never colour alone: every status colour ships with an icon + label.
export const STATUS = {
  green: { color: "var(--good)", label: "Healthy" },
  yellow: { color: "var(--warning)", label: "Watch" },
  red: { color: "var(--critical)", label: "Critical" },
  calibrating: { color: "var(--series)", label: "Learning normal" },
  offline: { color: "var(--muted)", label: "Offline" },
};

export function StatusIcon({ zone, size = 18 }) {
  const c = (STATUS[zone] || STATUS.offline).color;
  const common = { width: size, height: size, viewBox: "0 0 20 20", className: "status-icon", "aria-hidden": true };
  if (zone === "green") {
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="9" fill={c} />
        <path d="M5.5 10.5l3 3 6-6.5" stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (zone === "yellow") {
    return (
      <svg {...common}>
        <path d="M10 1.5l9 16.5H1z" fill={c} />
        <path d="M10 7v5" stroke="#1a1a19" strokeWidth="2.2" strokeLinecap="round" />
        <circle cx="10" cy="15" r="1.2" fill="#1a1a19" />
      </svg>
    );
  }
  if (zone === "red") {
    return (
      <svg {...common}>
        <path d="M6 1h8l5 5v8l-5 5H6l-5-5V6z" fill={c} />
        <path d="M10 5.5v5.5" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
        <circle cx="10" cy="14.5" r="1.2" fill="#fff" />
      </svg>
    );
  }
  if (zone === "calibrating") {
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="8" fill="none" stroke={c} strokeWidth="2.5" strokeDasharray="30 20" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <circle cx="10" cy="10" r="8" fill="none" stroke={c} strokeWidth="2.5" />
      <path d="M5 15L15 5" stroke={c} strokeWidth="2.5" />
    </svg>
  );
}
