import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { dashboardApi, type DashboardMode } from "../services/dashboardApi";
import { streamTicket } from "../services/http";
import type { DashboardFilters, DashboardSnapshot } from "../types";

interface DashboardContextValue {
  snapshot: DashboardSnapshot | null;
  loading: boolean;
  error: string | null;
  mode: DashboardMode;
  filters: DashboardFilters;
  setFilters: (filters: DashboardFilters) => void;
  refresh: () => Promise<void>;
}

const Context = createContext<DashboardContextValue | null>(null);
const initialFilters: DashboardFilters = { range: "30D", campaign: "ALL", language: "ALL", region: "ALL" };

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState(initialFilters);

  async function refresh() {
    setLoading(true);
    try {
      const data = await dashboardApi.getSnapshot();
      setSnapshot(data);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Dashboard data could not be loaded.");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    void refresh();

    let eventSource: EventSource | null = null;
    let closed = false;
    let timer: number | undefined;
    const schedule = () => { window.clearTimeout(timer); timer = window.setTimeout(() => void refresh(), 400); };
    const connect = async () => {
      try {
        const ticket = await streamTicket("events");
        if (closed) return;
        eventSource = new EventSource(`/api/events/sse?ticket=${encodeURIComponent(ticket)}`);
        eventSource.onmessage = schedule;
        for (const t of ["case.created", "case.assigned", "case.reassigned", "case.status_changed", "case.resolved", "callback.scheduled",
          "callback.rescheduled", "callback.cancelled", "callback.due", "callback.outcome", "callback.requested", "telephony_status_updated"]) {
          eventSource.addEventListener(t, schedule);
        }
        eventSource.onerror = () => { eventSource?.close(); if (!closed) window.setTimeout(() => void connect(), 5000); };
      } catch { if (!closed) window.setTimeout(() => void connect(), 10000); }
    };
    void connect();

    return () => {
      closed = true;
      window.clearTimeout(timer);
      eventSource?.close();
    };
  }, []);
  const value = useMemo(() => ({ snapshot, loading, error, mode: dashboardApi.mode, filters, setFilters, refresh }), [snapshot, loading, error, filters]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useDashboard(): DashboardContextValue {
  const context = useContext(Context);
  if (!context) throw new Error("useDashboard must be used inside DashboardProvider");
  return context;
}
