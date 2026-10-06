import type { ReactNode } from "react";

export function PageHeading({ title, description, actions, eyebrow }: { title: string; description: string; actions?: ReactNode; eyebrow?: string }) {
  return <div className="ops-page-heading"><div>{eyebrow && <div className="ops-eyebrow">{eyebrow}</div>}<h1>{title}</h1><p>{description}</p></div>{actions && <div className="ops-heading-actions">{actions}</div>}</div>;
}
