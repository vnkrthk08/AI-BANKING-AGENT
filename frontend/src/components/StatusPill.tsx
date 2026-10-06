import type { ReactNode } from "react";

const tones: Record<string, string> = {
  CLOSED: "good", RESOLVED: "good", COMPLETED: "good", ACTIVE: "good", AVAILABLE: "good", ALLOWED: "good", CONSENTED: "good",
  CALLBACK_SCHEDULED: "warn", SCHEDULED: "warn", IMMEDIATE: "warn", HIGH: "warn", URGENT: "bad", OVERDUE: "bad", ESCALATED: "bad", CRITICAL: "bad", BLOCKED: "bad", DND: "muted",
  NOT_INTERESTED: "muted", NO_ANSWER: "muted", FAILED: "muted", PAUSED: "muted", OFFLINE: "muted", BREAK: "muted", NEW: "info", ASSIGNED: "info", IN_PROGRESS: "info", ON_CALL: "info", NORMAL: "info", LOW: "muted",
};

export function StatusPill({ value, children }: { value?: string; children?: ReactNode }) {
  const text = value ?? (typeof children === "string" ? children : "—");
  return <span className={`ops-status ops-status-${tones[text] ?? "muted"}`}><i />{children ?? text.replaceAll("_", " ")}</span>;
}
