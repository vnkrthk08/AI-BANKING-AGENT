import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiJson, onSessionExpired, refreshSession, setAccessToken } from "../services/http";

export interface SessionUser {
  id: string; username: string; full_name: string; email: string; role: string; branch: string;
  agent_id?: string | null; permissions: string[];
}
interface AuthValue {
  user: SessionUser | null; checking: boolean;
  login(username: string, password: string): Promise<void>;
  logout(): Promise<void>;
  can(permission: string): boolean;
}
const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [checking, setChecking] = useState(true);

  const loadMe = useCallback(async () => {
    const me = await apiJson<{ user: SessionUser & { sub: string } }>("/api/v1/auth/me");
    setUser({ ...me.user, id: me.user.id ?? me.user.sub });
  }, []);

  useEffect(() => {
    void (async () => {
      try { if (await refreshSession()) await loadMe(); } catch { setUser(null); } finally { setChecking(false); }
    })();
    return onSessionExpired(() => { setAccessToken(null); setUser(null); });
  }, [loadMe]);

  const value = useMemo<AuthValue>(() => ({
    user, checking,
    async login(username, password) {
      const res = await apiJson<{ access_token: string }>("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      setAccessToken(res.access_token);
      await loadMe();
    },
    async logout() {
      await apiJson("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
      setAccessToken(null); setUser(null);
    },
    can: (p) => Boolean(user?.permissions.includes(p)),
  }), [user, checking, loadMe]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
