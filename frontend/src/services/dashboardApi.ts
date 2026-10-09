import { createMockSnapshot, currentDemoRoleActor, MOCK_SNAPSHOT } from "../mock/data";
import type { AuditEvent, Callback, DashboardSnapshot, EscalationCase, ReportSchedule, Role } from "../types";

export type DashboardMode = "mock" | "live";
declare global { interface ImportMetaEnv { readonly VITE_DASHBOARD_API_MODE?: string; readonly VITE_MOCK_DATA?: string } interface ImportMeta { readonly env: ImportMetaEnv } }
const mode: DashboardMode = (import.meta.env.VITE_MOCK_DATA === "true" || import.meta.env.VITE_DASHBOARD_API_MODE === "mock") ? "mock" : "live";


export interface DashboardApi {
  readonly mode: DashboardMode;
  getSnapshot(): Promise<DashboardSnapshot>;
  recordAudit(action: string, resourceType: string, resourceId: string, role: Role, detail?: string): Promise<AuditEvent>;
  updateCase(id: string, patch: Partial<EscalationCase>): Promise<void>;
  updateCallback(id: string, patch: Partial<Callback>): Promise<void>;
  createCallback(callback: Callback): Promise<void>;
  updateCampaign(id: string, patch: Record<string, unknown>): Promise<void>;
  createCampaign(campaign: DashboardSnapshot["campaigns"][number]): Promise<void>;
  createCase(caseData: Record<string, unknown>): Promise<void>;
  createAgent(agentData: Record<string, unknown>): Promise<void>;
  updateAgent(id: string, patch: Record<string, unknown>): Promise<void>;
  getSchedules(): Promise<ReportSchedule[]>;
  saveSchedule(schedule: ReportSchedule): Promise<void>;
}


let mockSnapshot = createMockSnapshot();
const AUDIT_KEY = "kural-ops-audit-demo-v1";
const SCHEDULE_KEY = "kural-ops-schedules-demo-v1";

function readStored<T>(key: string, fallback: T): T {
  try { const value = localStorage.getItem(key); return value ? JSON.parse(value) as T : fallback; }
  catch { return fallback; }
}
function writeStored(key: string, value: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* A private-mode browser can still use this tab's mock state. */ }
}

function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  return fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } })
    .then(async (response) => {
      if (!response.ok) throw new Error(`Operations API returned ${response.status} at ${path}`);
      return response.json() as Promise<T>;
    })
    .catch((err: unknown) => {
      if (err instanceof Error) {
        if (err.message.startsWith("Operations API")) throw err;
        throw new Error(`Failed to reach AVA backend at ${path} (${err.message}). Verify FastAPI server is running on port 8000.`);
      }
      throw new Error(`Failed to reach AVA backend at ${path}`);
    });
}

const mockApi: DashboardApi = {
  mode,
  async getSnapshot() {
    try {
      const liveCallbacks = await fetchJson<Callback[]>("/api/callbacks");
      if (Array.isArray(liveCallbacks) && liveCallbacks.length > 0) {
        const liveMap = new Map(liveCallbacks.map((c) => [c.id, c]));
        const merged = [...liveCallbacks, ...mockSnapshot.callbacks.filter((c) => !liveMap.has(c.id))];
        mockSnapshot.callbacks = merged;
      }
    } catch {
      /* Fallback to local mock state if backend not reached */
    }
    return structuredClone(mockSnapshot);
  },
  async recordAudit(action, resourceType, resourceId, role, detail = "") {
    const event: AuditEvent = {
      id: `AUD-UI-${crypto.randomUUID()}`, actor: currentDemoRoleActor(role), actorRole: role,
      action, resourceType, resourceId, timestamp: new Date().toISOString(),
      ip: "192.0.2.42", detail: detail || "Operations audit event logged under banking controls",
    };
    const existing = readStored<AuditEvent[]>(AUDIT_KEY, []);
    const events = [event, ...existing].slice(0, 500);
    writeStored(AUDIT_KEY, events);
    mockSnapshot.auditEvents = [...events, ...MOCK_SNAPSHOT.auditEvents];
    return event;
  },
  async updateCase(id, patch) {
    mockSnapshot = { ...mockSnapshot, escalations: mockSnapshot.escalations.map((item) => item.id === id ? { ...item, ...patch } : item) };
    writeStored("kural-ops-cases-demo-v1", mockSnapshot.escalations);
    try {
      await fetchJson(`/api/escalations/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) });
    } catch {
      /* Local fallback */
    }
  },
  async updateCallback(id, patch) {
    mockSnapshot = { ...mockSnapshot, callbacks: mockSnapshot.callbacks.map((item) => item.id === id ? { ...item, ...patch } : item) };
    writeStored("kural-ops-callbacks-demo-v1", mockSnapshot.callbacks);
    try {
      if (patch.preferredAt) {
        await fetchJson(`/api/callbacks/${encodeURIComponent(id)}/reschedule`, {
          method: "POST",
          body: JSON.stringify({ scheduled_at_local: patch.preferredAt, actor: "STAFF" }),
        });
      } else {
        await fetchJson(`/api/callbacks/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: JSON.stringify(patch),
        });
      }
    } catch {
      /* Local fallback */
    }
  },
  async createCallback(callback) { mockSnapshot = { ...mockSnapshot, callbacks: [callback, ...mockSnapshot.callbacks] }; writeStored("kural-ops-callbacks-demo-v1", mockSnapshot.callbacks); },
  async updateCampaign(id, patch) {
    mockSnapshot = { ...mockSnapshot, campaigns: mockSnapshot.campaigns.map((item) => item.id === id ? { ...item, ...patch, updatedAt: new Date().toISOString() } as typeof item : item) };
    writeStored("kural-ops-campaigns-demo-v1", mockSnapshot.campaigns);
  },
  async createCampaign(campaign) { mockSnapshot = { ...mockSnapshot, campaigns: [campaign, ...mockSnapshot.campaigns] }; writeStored("kural-ops-campaigns-demo-v1", mockSnapshot.campaigns); },
  async createCase(caseData) {
    const newCase = { id: `CASE-UI-${crypto.randomUUID().slice(0, 8)}`, status: "NEW", priority: "NORMAL", createdAt: new Date().toISOString(), ...caseData } as any;
    mockSnapshot = { ...mockSnapshot, escalations: [newCase, ...mockSnapshot.escalations] };
    writeStored("kural-ops-cases-demo-v1", mockSnapshot.escalations);
  },
  async createAgent(agentData) {
    const newAgent = { id: `AG-${mockSnapshot.agents.length + 1}`, name: "New Agent", team: "Digital support · Tier 1", languages: ["Hindi", "English"], availability: "AVAILABLE", activeCalls: 0, handledToday: 0, avgResolutionMin: 0, slaHitPercent: 100, ...agentData } as any;
    mockSnapshot = { ...mockSnapshot, agents: [newAgent, ...mockSnapshot.agents] };
  },
  async updateAgent(id, patch) {
    mockSnapshot = { ...mockSnapshot, agents: mockSnapshot.agents.map((a) => a.id === id ? { ...a, ...patch } : a) };
  },
  async getSchedules() { return readStored<ReportSchedule[]>(SCHEDULE_KEY, []); },
  async saveSchedule(schedule) { writeStored(SCHEDULE_KEY, [schedule, ...readStored<ReportSchedule[]>(SCHEDULE_KEY, [])]); },
};

const liveApi: DashboardApi = {
  mode,
  async getSnapshot() {
    const [calls, campaigns, callbacks, escalations, agentPayload, compliance, auditEvents] = await Promise.all([
      fetchJson<DashboardSnapshot["calls"]>("/api/calls"),
      fetchJson<DashboardSnapshot["campaigns"]>("/api/campaigns"),
      fetchJson<DashboardSnapshot["callbacks"]>("/api/callbacks"),
      fetchJson<DashboardSnapshot["escalations"]>("/api/escalations"),
      fetchJson<DashboardSnapshot["agents"] | Pick<DashboardSnapshot,"agents"|"workloads"|"slaPolicies">>("/api/agents"),
      fetchJson<{ consents: DashboardSnapshot["consents"]; egressLogs: DashboardSnapshot["egressLogs"] }>("/api/compliance/summary"),
      fetchJson<DashboardSnapshot["auditEvents"]>("/api/audit"),
    ]);
    const agentData = Array.isArray(agentPayload) ? { agents: agentPayload, workloads: [], slaPolicies: [] } : agentPayload;
    return { calls, campaigns, callbacks, escalations, ...agentData, auditEvents, consents: compliance.consents, egressLogs: compliance.egressLogs };
  },
  async recordAudit(action, resourceType, resourceId, role, detail = "") {
    return fetchJson<AuditEvent>("/api/audit", { method: "POST", body: JSON.stringify({ action, resourceType, resourceId, role, detail }) });
  },
  async updateCase(id, patch) { await fetchJson(`/api/escalations/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }); },
  async createCase(caseData) { await fetchJson("/api/escalations", { method: "POST", body: JSON.stringify(caseData) }); },
  async updateCallback(id, patch) { await fetchJson(`/api/callbacks/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }); },
  async createCallback(callback) { await fetchJson("/api/callbacks", { method: "POST", body: JSON.stringify(callback) }); },
  async updateCampaign(id, patch) { await fetchJson(`/api/campaigns/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(patch) }); },
  async createCampaign(campaign) { await fetchJson("/api/campaigns", { method: "POST", body: JSON.stringify(campaign) }); },
  async createAgent(agentData) { await fetchJson("/api/agents", { method: "POST", body: JSON.stringify(agentData) }); },
  async updateAgent(id, patch) { await fetchJson(`/api/agents/${encodeURIComponent(id)}/status`, { method: "PATCH", body: JSON.stringify(patch) }); },
  getSchedules() { return fetchJson<ReportSchedule[]>("/api/reports/schedules"); },
  async saveSchedule(schedule) { await fetchJson("/api/reports/schedules", { method: "POST", body: JSON.stringify(schedule) }); },
};


export const dashboardApi: DashboardApi = mode === "live" ? liveApi : mockApi;

export function applyMockPersistence(): void {
  if (mode !== "mock") return;
  const cases = readStored<EscalationCase[] | null>("kural-ops-cases-demo-v1", null);
  const callbacks = readStored<Callback[] | null>("kural-ops-callbacks-demo-v1", null);
  const campaigns = readStored<DashboardSnapshot["campaigns"] | null>("kural-ops-campaigns-demo-v1", null);
  mockSnapshot = { ...MOCK_SNAPSHOT,
    escalations: cases ?? MOCK_SNAPSHOT.escalations,
    callbacks: callbacks ?? MOCK_SNAPSHOT.callbacks,
    campaigns: campaigns ?? MOCK_SNAPSHOT.campaigns,
    auditEvents: [...readStored<AuditEvent[]>(AUDIT_KEY, []), ...MOCK_SNAPSHOT.auditEvents],
  };
}

export function resetMockDataForSession(): void { if (mode === "mock") { mockSnapshot = createMockSnapshot(); applyMockPersistence(); } }
