import { apiJson } from "./http";
import type { AuditEvent, Callback, DashboardSnapshot, ReportSchedule, Role } from "../types";

/** Live operations API only. There is no mock fallback: failures surface as errors in the UI. */
export type DashboardMode = "live";

async function optional<T>(path: string, fallback: T): Promise<T> {
  // Sections the signed-in role may not read return 403; show them as empty rather than failing the page.
  try { return await apiJson<T>(path); }
  catch (e) { if (e instanceof Error && "status" in e && (e as { status: number }).status === 403) return fallback; throw e; }
}

export const dashboardApi = {
  mode: "live" as DashboardMode,
  async getSnapshot(): Promise<DashboardSnapshot> {
    const [calls, campaigns, callbacks, escalations, agentPayload, compliance, auditEvents] = await Promise.all([
      optional<DashboardSnapshot["calls"]>("/api/calls?limit=500", []),
      optional<DashboardSnapshot["campaigns"]>("/api/campaigns", []),
      optional<DashboardSnapshot["callbacks"]>("/api/callbacks", []),
      optional<DashboardSnapshot["escalations"]>("/api/escalations", []),
      optional<Pick<DashboardSnapshot, "agents" | "workloads" | "slaPolicies">>("/api/agents", { agents: [], workloads: [], slaPolicies: [] }),
      optional<{ consents: DashboardSnapshot["consents"]; egressLogs: DashboardSnapshot["egressLogs"] }>("/api/compliance/summary", { consents: [], egressLogs: [] }),
      optional<DashboardSnapshot["auditEvents"]>("/api/audit", []),
    ]);
    return { calls, campaigns, callbacks, escalations, ...agentPayload, auditEvents, consents: compliance.consents, egressLogs: compliance.egressLogs };
  },
  recordAudit(action: string, resourceType: string, resourceId: string, _role: Role, detail = ""): Promise<AuditEvent> {
    return apiJson<AuditEvent>("/api/audit", { method: "POST", body: JSON.stringify({ action, resourceType, resourceId, detail }) });
  },
  async updateCase(id: string, patch: object) { await apiJson(`/api/escalations/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }); },
  async createCase(caseData: Record<string, unknown>) { await apiJson("/api/escalations", { method: "POST", body: JSON.stringify(caseData) }); },
  async updateCallback(id: string, patch: Partial<Callback> & { status?: string }) {
    const p = patch as { preferredAt?: string; status?: string };
    if (p.preferredAt) {
      await apiJson(`/api/callbacks/${encodeURIComponent(id)}/reschedule`, { method: "POST", body: JSON.stringify({ preferredAt: patch.preferredAt }) });
    } else if (p.status === "CANCELLED") {
      await apiJson(`/api/callbacks/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" });
    } else {
      await apiJson(`/api/callbacks/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) });
    }
  },
  async createCallback(callback: object) { await apiJson("/api/callbacks", { method: "POST", body: JSON.stringify(callback) }); },
  async updateCampaign(id: string, patch: object) { await apiJson(`/api/campaigns/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }); },
  async campaignAction(id: string, action: "approve" | "start" | "pause" | "resume" | "cancel") { return apiJson(`/api/campaigns/${encodeURIComponent(id)}/${action}`, { method: "POST", body: "{}" }); },
  async createCampaign(campaign: object) { await apiJson("/api/campaigns", { method: "POST", body: JSON.stringify(campaign) }); },
  async createAgent(agentData: Record<string, unknown>) { await apiJson("/api/agents", { method: "POST", body: JSON.stringify(agentData) }); },
  async updateAgent(id: string, patch: Record<string, unknown>) { await apiJson(`/api/agents/${encodeURIComponent(id)}/status`, { method: "PATCH", body: JSON.stringify(patch) }); },
  getSchedules() { return apiJson<ReportSchedule[]>("/api/reports/schedules"); },
  async saveSchedule(schedule: ReportSchedule) { await apiJson("/api/reports/schedules", { method: "POST", body: JSON.stringify(schedule) }); },
};

export function applyMockPersistence(): void { /* mock mode removed */ }
