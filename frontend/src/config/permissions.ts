import type { Role } from "../types";

export type RouteKey = "executive" | "team" | "my-work" | "live-calls" | "call-log" | "customer-journey" | "callbacks" | "escalations" | "campaigns" | "insights" | "reports" | "compliance" | "system-health" | "test-console";
export type ActionKey = "export" | "view-transcript" | "view-audio" | "call-now" | "assign-case" | "resolve-case" | "supervise-live" | "manage-campaigns" | "schedule-report" | "view-audit";

export interface RoleAccess {
  label: string;
  home: RouteKey;
  routes: RouteKey[];
  actions: ActionKey[];
}

export const ROLE_ACCESS: Record<Role, RoleAccess> = {
  OPS_MANAGER: {
    label: "Ops manager",
    home: "test-console",
    routes: ["test-console", "executive", "live-calls", "call-log", "customer-journey", "callbacks", "escalations", "campaigns", "insights", "reports", "system-health"],
    actions: ["export", "view-transcript", "view-audio", "call-now", "assign-case", "supervise-live", "manage-campaigns", "schedule-report"],
  },
  SUPERVISOR: {
    label: "Supervisor",
    home: "team",
    routes: ["test-console", "team", "live-calls", "call-log", "customer-journey", "callbacks", "escalations", "system-health"],
    actions: ["view-transcript", "view-audio", "call-now", "assign-case", "supervise-live"],
  },
  AGENT: {
    label: "Human agent",
    home: "my-work",
    routes: ["test-console", "my-work", "callbacks"],
    actions: ["view-transcript", "view-audio", "call-now", "resolve-case"],
  },
  COMPLIANCE: {
    label: "Compliance / auditor",
    home: "compliance",
    routes: ["test-console", "compliance", "call-log", "customer-journey", "reports"],
    actions: ["export", "view-transcript", "view-audio", "schedule-report", "view-audit"],
  },
};

export const ROUTES: Record<RouteKey, { path: string; label: string; section: "WORKSPACE" | "MANAGE" | "GOVERNANCE" | "TOOLS" }> = {
  executive: { path: "/executive", label: "Executive overview", section: "WORKSPACE" },
  team: { path: "/team", label: "Team board", section: "WORKSPACE" },
  "my-work": { path: "/my-work", label: "My work", section: "WORKSPACE" },
  "live-calls": { path: "/live-calls", label: "Live calls", section: "WORKSPACE" },
  "call-log": { path: "/call-log", label: "Call log", section: "WORKSPACE" },
  "customer-journey": { path: "/customer-journey", label: "Customer journey", section: "WORKSPACE" },
  callbacks: { path: "/callbacks", label: "Callbacks", section: "MANAGE" },
  escalations: { path: "/escalations", label: "Escalations", section: "MANAGE" },
  campaigns: { path: "/campaigns", label: "Campaigns", section: "MANAGE" },
  insights: { path: "/insights", label: "Insights", section: "MANAGE" },
  reports: { path: "/reports", label: "Reports", section: "MANAGE" },
  compliance: { path: "/compliance", label: "Compliance & audit", section: "GOVERNANCE" },
  "system-health": { path: "/system-health", label: "AI quality & health", section: "GOVERNANCE" },
  "test-console": { path: "/test-console", label: "AVA Voice Call", section: "WORKSPACE" },
};

export const hasAction = (role: Role, action: ActionKey): boolean => ROLE_ACCESS[role].actions.includes(action);
export const hasRoute = (role: Role, route: RouteKey): boolean => ROLE_ACCESS[role].routes.includes(route);
