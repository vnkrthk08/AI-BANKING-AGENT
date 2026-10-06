import type { ReactNode } from "react";

export function KpiCard({ label, value, delta, deltaLabel = "vs prior period", icon, accent = "teal", footnote }: { label: string; value: string; delta?: number; deltaLabel?: string; icon: ReactNode; accent?: string; footnote?: string }) {
  return <article className={`ops-kpi ops-kpi-${accent}`}><div className="ops-kpi-top"><span>{label}</span><span className="ops-kpi-icon">{icon}</span></div><div className="ops-kpi-value">{value}</div><div className="ops-kpi-bottom">{delta !== undefined ? <span className={delta >= 0 ? "ops-delta-up" : "ops-delta-down"}>{delta >= 0 ? "↑" : "↓"} {Math.abs(delta).toFixed(1)}%</span> : <span className="ops-kpi-neutral">—</span>}<span>{footnote ?? deltaLabel}</span></div></article>;
}
