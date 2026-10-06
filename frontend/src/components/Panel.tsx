import type { ReactNode } from "react";

export function Panel({ title, subtitle, actions, children, className = "" }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`ops-panel ${className}`}><header className="ops-panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{actions && <div className="ops-panel-actions">{actions}</div>}</header><div className="ops-panel-body">{children}</div></section>;
}
