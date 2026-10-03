"use client";
import Link from "next/link";
import { createContext, useCallback, useContext, useRef, useState } from "react";
import { StatusIcon } from "@/components/StatusIcon";

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

/** toast({ zone: "red"|"green"|"yellow"|"calibrating", title, body, href, linkText, ttl }) */
export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id) => setItems((xs) => xs.filter((x) => x.id !== id)), []);
  const toast = useCallback((t) => {
    const id = nextId.current++;
    setItems((xs) => [...xs.slice(-3), { id, ...t }]);
    setTimeout(() => dismiss(id), t.ttl ?? 6000);
  }, [dismiss]);

  return (
    <ToastCtx.Provider value={toast}>
      {children}
      <div className="toasts" aria-live="assertive">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.zone || "calibrating"}`} role="status">
            <StatusIcon zone={t.zone || "calibrating"} size={20} />
            <div className="toast-text">
              <strong>{t.title}</strong>
              {t.body && <div className="sub">{t.body}</div>}
              {t.href && <Link href={t.href} className="link-btn" onClick={() => dismiss(t.id)}>{t.linkText || "Open"}</Link>}
            </div>
            <button className="toast-x" onClick={() => dismiss(t.id)} aria-label="Dismiss">×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
