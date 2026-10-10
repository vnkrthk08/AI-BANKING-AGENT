import type { ReactNode } from "react";
import { useAuth } from "../auth/AuthContext";
import type { Role } from "../types";

/** The role always comes from the authenticated session; it cannot be switched in the browser. */
export function toUiRole(backendRole: string | undefined): Role {
  if (backendRole === "SUPER_ADMIN") return "SUPER_ADMIN";
  if (backendRole === "COMPLIANCE_OFFICER" || backendRole === "AUDITOR") return "COMPLIANCE";
  if (backendRole === "OPS_MANAGER" || backendRole === "SUPERVISOR" || backendRole === "AGENT" || backendRole === "SYSTEM_ADMIN") return backendRole;
  return "AGENT";
}

export function RoleProvider({ children }: { children: ReactNode }) { return <>{children}</>; }

export function useRole(): [Role, (role: Role) => void] {
  const { user } = useAuth();
  return [toUiRole(user?.role), () => undefined];
}
