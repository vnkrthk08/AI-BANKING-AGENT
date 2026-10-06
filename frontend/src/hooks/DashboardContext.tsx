import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { applyMockPersistence, dashboardApi, type DashboardMode } from "../services/dashboardApi";
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
      applyMockPersistence();
      const data = await dashboardApi.getSnapshot();
      setSnapshot(data);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Dashboard data could not be loaded.");
    } finally { setLoading(false); }
  }

  useEffect(() => { void refresh(); }, []);
  const value = useMemo(() => ({ snapshot, loading, error, mode: dashboardApi.mode, filters, setFilters, refresh }), [snapshot, loading, error, filters]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useDashboard(): DashboardContextValue {
  const context = useContext(Context);
  if (!context) throw new Error("useDashboard must be used inside DashboardProvider");
  return context;
}
