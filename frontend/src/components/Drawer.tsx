import { X } from "@phosphor-icons/react";
import { useEffect, type ReactNode } from "react";

export function Drawer({ title, eyebrow, onClose, children, wide = false }: { title: string; eyebrow?: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return <div className="ops-drawer-layer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className={`ops-drawer ${wide ? "ops-drawer-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
      <header className="ops-drawer-head"><div>{eyebrow && <small>{eyebrow}</small>}<h2>{title}</h2></div><button className="ops-icon-button" aria-label="Close panel" onClick={onClose}><X size={19} /></button></header>
      <div className="ops-drawer-body">{children}</div>
    </section>
  </div>;
}
