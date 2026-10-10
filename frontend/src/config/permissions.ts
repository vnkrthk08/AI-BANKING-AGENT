import type { Role } from "../types";

export type RouteKey =
  | "executive"
  | "test-console"
  | "calls"
  | "campaigns"
  | "work"
  | "team"
  | "governance"
  | "my-work"
  | "live-calls"
  | "call-log"
  | "customer-journey"
  | "callbacks"
  | "escalations"
  | "insights"
  | "reports"
  | "compliance"
  | "system-health";

export type ActionKey =
  | "export"
  | "view-transcript"
  | "view-audio"
  | "call-now"
  | "assign-case"
  | "resolve-case"
  | "supervise-live"
  | "manage-campaigns"
  | "schedule-report"
  | "view-audit";

export interface RoleAccess {
  label: string;
  home: RouteKey;
  routes: RouteKey[];
  actions: ActionKey[];
}

export const ROLE_ACCESS: Record<Role, RoleAccess> = {
  SYSTEM_ADMIN: {
    label: "System administrator",
    home: "governance",
    routes: ["governance", "system-health"],
    actions: ["view-audit"],
  },
  OPS_MANAGER: {
    label: "Ops manager",
    home: "executive",
    routes: [
      "executive",
      "test-console",
      "calls",
      "campaigns",
      "work",
      "team",
      "governance",
      "live-calls",
      "call-log",
      "customer-journey",
      "callbacks",
      "escalations",
      "insights",
      "reports",
      "system-health",
    ],
    actions: [
      "export",
      "view-transcript",
      "view-audio",
      "call-now",
      "assign-case",
      "supervise-live",
      "manage-campaigns",
      "schedule-report",
    ],
  },
  SUPERVISOR: {
    label: "Supervisor",
    home: "team",
    routes: [
      "test-console",
      "team",
      "calls",
      "work",
      "governance",
      "live-calls",
      "call-log",
      "customer-journey",
      "callbacks",
      "escalations",
      "system-health",
    ],
    actions: ["view-transcript", "view-audio", "call-now", "assign-case", "supervise-live"],
  },
  AGENT: {
    label: "Human agent",
    home: "work",
    routes: ["test-console", "team", "work", "my-work", "callbacks"],
    actions: ["view-transcript", "view-audio", "call-now", "resolve-case"],
  },
  COMPLIANCE: {
    label: "Compliance / auditor",
    home: "governance",
    routes: [
      "test-console",
      "governance",
      "calls",
      "compliance",
      "call-log",
      "customer-journey",
      "reports",
    ],
    actions: ["export", "view-transcript", "view-audio", "schedule-report", "view-audit"],
  },
};

export const ROUTES: Record<
  RouteKey,
  { path: string; label: string; section: "WORKSPACE" | "MANAGE" | "GOVERNANCE" | "TOOLS" }
> = {
  // 7 Unified Operational Hubs
  executive: { path: "/executive", label: "Executive Overview", section: "WORKSPACE" },
  "test-console": { path: "/test-console", label: "AI Voice Studio", section: "WORKSPACE" },
  calls: { path: "/calls", label: "Calls Hub", section: "WORKSPACE" },
  campaigns: { path: "/campaigns", label: "Campaigns", section: "MANAGE" },
  work: { path: "/work", label: "Work Queue", section: "MANAGE" },
  team: { path: "/team", label: "Team Roster", section: "MANAGE" },
  governance: { path: "/governance", label: "Governance & Health", section: "GOVERNANCE" },

  // Backwards-compatible legacy route targets
  "my-work": { path: "/my-work", label: "My Work", section: "MANAGE" },
  "live-calls": { path: "/live-calls", label: "Live Calls", section: "WORKSPACE" },
  "call-log": { path: "/call-log", label: "Call Log", section: "WORKSPACE" },
  "customer-journey": { path: "/customer-journey", label: "Customer Journey", section: "WORKSPACE" },
  callbacks: { path: "/callbacks", label: "Callbacks", section: "MANAGE" },
  escalations: { path: "/escalations", label: "Escalations", section: "MANAGE" },
  insights: { path: "/insights", label: "Insights", section: "MANAGE" },
  reports: { path: "/reports", label: "Reports", section: "MANAGE" },
  compliance: { path: "/compliance", label: "Compliance & Audit", section: "GOVERNANCE" },
  "system-health": { path: "/system-health", label: "AI Quality & Health", section: "GOVERNANCE" },
};

export const hasAction = (role: Role, action: ActionKey): boolean =>
  ROLE_ACCESS[role].actions.includes(action);
export const hasRoute = (role: Role, route: RouteKey): boolean =>
  ROLE_ACCESS[role].routes.includes(route);
