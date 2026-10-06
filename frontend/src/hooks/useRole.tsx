import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { Role } from "../types";

const KEY = "kural-ops-demo-role";
type RoleContextValue = [Role, (role: Role) => void];
const RoleContext = createContext<RoleContextValue | null>(null);

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<Role>(() => {
    const saved = localStorage.getItem(KEY);
    return saved === "SUPERVISOR" || saved === "AGENT" || saved === "COMPLIANCE" ? saved : "OPS_MANAGER";
  });
  const value = useMemo<RoleContextValue>(() => [role, (next) => { localStorage.setItem(KEY, next); setRoleState(next); }], [role]);
  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const context = useContext(RoleContext);
  if (!context) throw new Error("useRole must be used inside RoleProvider");
  return context;
}
