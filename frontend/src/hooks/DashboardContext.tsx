import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { streamTicket } from "../services/http";

/** Live-update bus: bumps `version` whenever the backend pushes a domain event over SSE. */
interface DashboardContextValue { version: number; live: boolean; bump: () => void }
const Context = createContext<DashboardContextValue | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const [live, setLive] = useState(false);
  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;
    let timer: number | undefined;
    const bump = () => { window.clearTimeout(timer); timer = window.setTimeout(() => setVersion((v) => v + 1), 400); };
    const connect = async () => {
      try {
        const ticket = await streamTicket("events");
        if (closed) return;
        es = new EventSource(`/api/events/sse?ticket=${encodeURIComponent(ticket)}`);
        es.onopen = () => setLive(true);
        es.onmessage = bump;
        for (const t of ["case.created", "case.assigned", "case.reassigned", "case.status_changed", "case.resolved", "callback.scheduled",
          "callback.rescheduled", "callback.cancelled", "callback.due", "callback.outcome", "callback.requested", "telephony_status_updated",
          "campaign_started", "campaign_paused", "agent_status_changed", "dialing.emergency_stop"]) es.addEventListener(t, bump);
        es.onerror = () => { setLive(false); es?.close(); if (!closed) window.setTimeout(() => void connect(), 5000); };
      } catch { if (!closed) window.setTimeout(() => void connect(), 10000); }
    };
    void connect();
    return () => { closed = true; window.clearTimeout(timer); es?.close(); };
  }, []);
  const value = useMemo(() => ({ version, live, bump: () => setVersion((v) => v + 1) }), [version, live]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useDashboard(): DashboardContextValue {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useDashboard must be used inside DashboardProvider");
  return ctx;
}
