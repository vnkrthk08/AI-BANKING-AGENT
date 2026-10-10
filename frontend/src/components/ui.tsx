import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { CheckCircle, Info, Warning, WarningCircle, X } from "@phosphor-icons/react";

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

/** Lightweight responsive SVG sparkline for KPI trends */
export function Sparkline({ data, color = "var(--brand-2)", height = 24 }: { data: number[]; color?: string; height?: number }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data, min + 1);
  const width = 120;
  const padding = 2;
  const effectiveHeight = height - padding * 2;
  const points = data.map((val, idx) => {
    const x = padding + (idx / (data.length - 1)) * (width - padding * 2);
    const y = height - padding - ((val - min) / (max - min)) * effectiveHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  const fillPoints = `${padding},${height} ${points} ${width - padding},${height}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="kpi-sparkline" preserveAspectRatio="none" aria-hidden="true">
      <defs>
        <linearGradient id={`spark-grad-${color.replace(/[^a-z0-9]/gi, "")}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <polygon points={fillPoints} fill={`url(#spark-grad-${color.replace(/[^a-z0-9]/gi, "")})`} />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Modern circular radial ring progress gauge */
export function RadialRing({ percent, size = 42, strokeWidth = 3.5, label, color = "var(--brand-2)" }: { percent: number; size?: number; strokeWidth?: number; label?: string; color?: string }) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, percent));
  const offset = circumference - (clamped / 100) * circumference;

  return (
    <div className="radial-ring" style={{ width: size, height: size }} title={`${clamped}%`}>
      <svg width={size} height={size}>
        <circle className="radial-ring-bg" cx={size / 2} cy={size / 2} r={radius} strokeWidth={strokeWidth} fill="transparent" />
        <circle className="radial-ring-fill" cx={size / 2} cy={size / 2} r={radius} strokeWidth={strokeWidth} strokeDasharray={circumference} strokeDashoffset={offset} stroke={color} fill="transparent" />
      </svg>
      <span className="radial-ring-label">{label ?? `${Math.round(clamped)}%`}</span>
    </div>
  );
}

export function Kpi({
  label,
  value,
  hint,
  tone,
  trend,
  spark,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "alert" | "warn";
  trend?: { dir: "up" | "down"; label: string };
  spark?: number[];
}) {
  return (
    <div className={`kpi ${tone ?? ""}`}>
      <div className="kpi-head">
        <label>{label}</label>
        {trend && (
          <span className={`kpi-trend ${trend.dir}`}>
            {trend.dir === "up" ? "↑" : "↓"} {trend.label}
          </span>
        )}
      </div>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
      {spark && spark.length > 1 && (
        <Sparkline
          data={spark}
          color={tone === "alert" ? "var(--bad)" : tone === "warn" ? "var(--warn)" : "var(--brand-2)"}
        />
      )}
    </div>
  );
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

/** Operational outcome wording shared by Overview, Calls and Campaigns. */
export const OUTCOME_LABELS: Record<string, string> = {
  CLOSED: "Resolved by AI", ESCALATED: "Escalated to staff", CALLBACK_SCHEDULED: "Callback booked",
  NO_RESPONSE: "No response", OPTED_OUT: "Opted out", ABANDONED: "Customer hung up", COMPLETED: "Call completed",
  BUSY: "Line busy", NO_ANSWER: "Not answered", FAILED: "Call failed", DND: "Blocked (DND)", NOT_INTERESTED: "Not interested",
  IN_PROGRESS: "In progress", DIALING: "Dialling", CANCELLED: "Cancelled",
};
export function outcomeLabel(v?: string | null): string { return v ? OUTCOME_LABELS[v.toUpperCase()] ?? titleCase(v) : "—"; }

/** Move focus into a dialog, trap Tab inside it, close on Escape and restore focus on unmount. */
function useDialogFocus(onClose: () => void) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const focusables = () => Array.from(node?.querySelectorAll<HTMLElement>('button:not([disabled]),[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])') ?? []);
    (node?.querySelector<HTMLElement>("[data-autofocus]") ?? focusables()[0])?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); return; }
      if (e.key !== "Tab") return;
      const f = focusables(); if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    };
    node?.addEventListener("keydown", onKey);
    return () => { node?.removeEventListener("keydown", onKey); previous?.focus?.(); };
  }, [onClose]);
  return ref;
}

export function Badge({ value, tone, children, pulse }: { value?: string | null; tone?: string; children?: ReactNode; pulse?: boolean }) {
  const key = (value ?? "").toUpperCase();
  const label = children ?? (value ? value.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "—");
  return <span className={`badge ${tone ?? TONES[key] ?? ""} ${pulse ? "pulse-badge" : ""}`}>{label}</span>;
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
  const ref = useDialogFocus(onClose);
  return (
    <div className="scrim" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" ref={ref} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head"><div><h2 id="drawer-title">{title}</h2>{sub && <p>{sub}</p>}</div><button className="icon-btn" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
        <div className="drawer-body">{children}</div>
        {footer && <div className="drawer-foot">{footer}</div>}
      </aside>
    </div>
  );
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer: ReactNode }) {
  const ref = useDialogFocus(onClose);
  return (
    <div className="modal-wrap" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={ref} onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2><div className="body">{children}</div><div className="foot">{footer}</div>
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { key: T; label: string; count?: number; pulse?: boolean }[] }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((it) => (
        <button
          key={it.key}
          role="tab"
          aria-selected={value === it.key}
          className={`tab ${value === it.key ? "active" : ""}`}
          onClick={() => onChange(it.key)}
        >
          {it.label}
          {it.count !== undefined && (
            <span className={`count ${it.pulse ? "pulse-badge" : ""}`}>
              {it.pulse && <span className="pulse-dot" style={{ width: 6, height: 6, marginRight: 4 }} />}
              {it.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

/** Visual Call Lifecycle Timeline component */
export function CallTimeline({ steps }: { steps: { label: string; time?: string; detail?: string; status?: "done" | "active" | "bad" }[] }) {
  return (
    <div className="call-timeline">
      {steps.map((st, idx) => (
        <div className="timeline-step" key={idx}>
          <div className={`step-node ${st.status ?? "done"}`} />
          <div className="step-content">
            <b>{st.label}</b>
            {st.detail && <div>{st.detail}</div>}
            {st.time && <small>{st.time}</small>}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------- Toast Notification System Context ----------
export interface Toast {
  id: string;
  type: "ok" | "warn" | "bad" | "info";
  title: string;
  message?: string;
}

interface ToastContextValue {
  show: (toast: Omit<Toast, "id">) => void;
  ok: (title: string, message?: string) => void;
  warn: (title: string, message?: string) => void;
  bad: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = (id: string) => setToasts((prev) => prev.filter((t) => t.id !== id));

  const show = (toast: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { ...toast, id }]);
    setTimeout(() => remove(id), 4500);
  };

  const ok = (title: string, message?: string) => show({ type: "ok", title, message });
  const warn = (title: string, message?: string) => show({ type: "warn", title, message });
  const bad = (title: string, message?: string) => show({ type: "bad", title, message });
  const info = (title: string, message?: string) => show({ type: "info", title, message });

  return (
    <ToastContext.Provider value={{ show, ok, warn, bad, info }}>
      {children}
      <div className="toast-viewport" role="region" aria-label="Notifications">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.type}`} role="alert">
            {t.type === "ok" && <CheckCircle size={18} color="var(--ok)" weight="fill" />}
            {t.type === "warn" && <Warning size={18} color="var(--warn)" weight="fill" />}
            {t.type === "bad" && <WarningCircle size={18} color="var(--bad)" weight="fill" />}
            {t.type === "info" && <Info size={18} color="var(--info)" weight="fill" />}
            <div className="toast-body">
              <b>{t.title}</b>
              {t.message && <span>{t.message}</span>}
            </div>
            <button className="toast-close" onClick={() => remove(t.id)} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    return {
      show: () => {},
      ok: () => {},
      warn: () => {},
      bad: () => {},
      info: () => {},
    };
  }
  return ctx;
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
