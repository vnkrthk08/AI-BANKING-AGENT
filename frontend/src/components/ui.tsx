import { useEffect, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";

export function PageHead({ title, sub, actions }: { title: string; sub?: string; actions?: ReactNode }) {
  return <header className="page-head"><div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>{actions && <div className="actions">{actions}</div>}</header>;
}

export function Panel({ title, sub, actions, children, flush }: { title?: ReactNode; sub?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <section className="panel">
      {(title || actions) && <div className="panel-head"><div><h2>{title}</h2>{sub && <div className="sub">{sub}</div>}</div>{actions && <div className="actions">{actions}</div>}</div>}
      <div className={flush ? "panel-flush" : "panel-body"}>{children}</div>
    </section>
  );
}

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "alert" | "warn" }) {
  return <div className={`kpi ${tone ?? ""}`}><label>{label}</label><strong>{value}</strong>{hint && <small>{hint}</small>}</div>;
}

const TONES: Record<string, string> = {
  ACTIVE: "ok", APPROVED: "info", PAUSED: "warn", DRAFT: "", COMPLETED: "ok", CANCELLED: "", FAILED: "bad",
  NEW: "info", ASSIGNED: "info", IN_PROGRESS: "warn", PENDING_CUSTOMER: "warn", RESOLVED: "ok", CLOSED: "ok",
  SCHEDULED: "info", REQUESTED: "warn", DUE: "bad", OVERDUE: "bad", DIALING: "warn",
  AVAILABLE: "ok", ON_CALL: "info", BUSY: "warn", BREAK: "warn", OFFLINE: "",
  HEALTHY: "ok", CONFIGURED: "ok", RUNNING: "ok", CONNECTED: "ok", DEGRADED: "warn", NOT_CONFIGURED: "", NOT_RUNNING_IN_API: "warn",
  DOWN: "bad", AUTH_FAILED: "bad", DELIVERED: "ok", SENT: "ok", QUEUED: "info", SENDING: "info", SKIPPED: "",
  URGENT: "bad", HIGH: "warn", NORMAL: "", LOW: "",
  ESCALATED: "warn", CALLBACK_SCHEDULED: "info", NO_RESPONSE: "warn", NO_ANSWER: "warn", OPTED_OUT: "",
};

export function Badge({ value, tone, children }: { value?: string | null; tone?: string; children?: ReactNode }) {
  const key = (value ?? "").toUpperCase();
  const label = children ?? (value ? value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "—");
  return <span className={`badge ${tone ?? TONES[key] ?? ""}`}>{label}</span>;
}

export function Empty({ icon, title, text, action }: { icon?: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return <div className="empty">{icon && <div className="ico">{icon}</div>}<h3>{title}</h3>{text && <p>{text}</p>}{action}</div>;
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return <div aria-busy="true" aria-label="Loading">{Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />)}</div>;
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return <div className="alert bad" role="alert"><span className="grow">{error}</span>{onRetry && <button className="btn sm" onClick={onRetry}>Retry</button>}</div>;
}

export function Drawer({ title, sub, onClose, children, footer }: { title: ReactNode; sub?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="scrim" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head"><div><h2>{title}</h2>{sub && <p>{sub}</p>}</div><button className="icon-btn" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </div>
  );
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="modal-wrap" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2><div className="body">{children}</div><div className="foot">{footer}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { key: T; label: string; count?: number }[] }) {
  return <div className="tabs" role="tablist">{items.map((it) => <button key={it.key} role="tab" aria-selected={value === it.key} className={`tab ${value === it.key ? "active" : ""}`} onClick={() => onChange(it.key)}>{it.label}{it.count !== undefined && <span className="count">{it.count}</span>}</button>)}</div>;
}

const IST = { timeZone: "Asia/Kolkata" } as const;
export function fmtDateTime(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", { ...IST, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
export function fmtRelative(iso?: string | null): string {
  if (!iso) return "—";
  const diff = new Date(iso).getTime() - Date.now();
  const mins = Math.round(Math.abs(diff) / 60000);
  const label = mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.round(mins / 60)}h` : `${Math.round(mins / 1440)}d`;
  return diff >= 0 ? `in ${label}` : `${label} ago`;
}
export function fmtDuration(sec?: number | null): string {
  if (!sec) return "0:00";
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}
export function titleCase(v?: string | null): string {
  return v ? v.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : "—";
}
