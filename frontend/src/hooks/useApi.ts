import { useCallback, useEffect, useState } from "react";
import { apiJson } from "../services/http";
import { useDashboard } from "./DashboardContext";

/** Fetch a live API resource; re-fetches when the server pushes a relevant event. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const { version } = useDashboard();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    if (!path) return;
    try { setData(await apiJson<T>(path)); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load data"); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { void load(); }, [load, version]);
  return { data, error, loading, reload: load };
}
