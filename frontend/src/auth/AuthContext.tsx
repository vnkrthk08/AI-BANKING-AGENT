import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiJson, getAccessToken, lastRefreshUnreachable, onSessionExpired, refreshSession, setAccessToken } from "../services/http";

export interface SessionUser {
  id: string; username: string; full_name: string; email: string; role: string; branch: string;
  agent_id?: string | null; permissions: string[];
}
interface AuthValue {
  user: SessionUser | null; checking: boolean; unreachable: boolean; retry(): void;
  login(username: string, password: string): Promise<void>;
  logout(): Promise<void>;
  impersonate(username: string): Promise<void>;
  revertImpersonation(): Promise<void>;
  isImpersonating: boolean;
  originalAdmin: SessionUser | null;
  can(permission: string): boolean;
}
const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [unreachable, setUnreachable] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [originalAdmin, setOriginalAdmin] = useState<SessionUser | null>(() => {
    try {
      const saved = sessionStorage.getItem("kural_orig_admin");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const loadMe = useCallback(async () => {
    const me = await apiJson<{ user: SessionUser & { sub: string } }>("/api/v1/auth/me");
    setUser({ ...me.user, id: me.user.id ?? me.user.sub });
  }, []);

  useEffect(() => {
    void (async () => {
      setChecking(true);
      try { if (await refreshSession()) await loadMe(); setUnreachable(lastRefreshUnreachable); } catch { setUser(null); } finally { setChecking(false); }
    })();
    return onSessionExpired(() => { setAccessToken(null); setUser(null); setOriginalAdmin(null); sessionStorage.removeItem("kural_orig_admin"); });
  }, [loadMe, attempt]);

  const value = useMemo<AuthValue>(() => ({
    user, checking, unreachable, retry: () => setAttempt((n) => n + 1),
    isImpersonating: Boolean(originalAdmin && user && originalAdmin.id !== user.id),
    originalAdmin,
    async login(username, password) {
      const res = await apiJson<{ access_token: string }>("/api/v1/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      setAccessToken(res.access_token);
      setOriginalAdmin(null);
      sessionStorage.removeItem("kural_orig_admin");
      await loadMe();
    },
    async logout() {
      await apiJson("/api/v1/auth/logout", { method: "POST" }).catch(() => undefined);
      setAccessToken(null); setUser(null); setOriginalAdmin(null);
      sessionStorage.removeItem("kural_orig_admin");
    },
    async impersonate(targetUsername: string) {
      if (!originalAdmin && user) {
        setOriginalAdmin(user);
        sessionStorage.setItem("kural_orig_admin", JSON.stringify(user));
        const curTok = getAccessToken();
        if (curTok) sessionStorage.setItem("kural_orig_admin_token", curTok);
      }
      const res = await apiJson<{ access_token: string }>("/api/v1/auth/impersonate", {
        method: "POST",
        body: JSON.stringify({ username: targetUsername }),
      });
      setAccessToken(res.access_token);
      await loadMe();
    },
    async revertImpersonation() {
      const origAdminToken = sessionStorage.getItem("kural_orig_admin_token");
      const target = originalAdmin?.username || "admin";
      try {
        const res = await apiJson<{ access_token: string }>("/api/v1/auth/revert-impersonation", {
          method: "POST",
          body: JSON.stringify({ admin_token: origAdminToken, admin_username: target }),
        });
        setAccessToken(res.access_token);
      } catch {
        // Fallback: restore saved token if network/endpoint issues
        if (origAdminToken) {
          setAccessToken(origAdminToken);
        }
      } finally {
        setOriginalAdmin(null);
        sessionStorage.removeItem("kural_orig_admin");
        sessionStorage.removeItem("kural_orig_admin_token");
        await loadMe();
      }
    },
    can: (p) => Boolean(user?.permissions.includes(p)),
  }), [user, checking, unreachable, originalAdmin, loadMe]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
