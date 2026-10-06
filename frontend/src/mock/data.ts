import type {
  Agent, AgentWorkload, AuditEvent, CallRecord, Campaign, Callback, ConsentRecord,
  DashboardSnapshot, Disposition, EscalationCase, LLMEgressLog, Role, SlaPolicy, TranscriptMessage,
} from "../types";

const languages = ["Hindi", "English", "Tamil", "Telugu", "Kannada", "Marathi", "Bengali"];
const regions = ["North", "South", "West", "East", "Central"];
const branches = ["Delhi NCR", "Mumbai Metro", "Bengaluru Urban", "Chennai South", "Hyderabad Central", "Kolkata East", "Pune West", "Lucknow Central"];
const issues = ["Update failed", "Login assistance", "App access", "Feature query", "Network issue", "Device compatibility"];
const features = ["UPI payments", "Bill payments", "Card controls", "Account alerts", "Fixed deposits", "Mobile recharge"];
const outcomes: Disposition[] = [
  ...Array<Disposition>(43).fill("CLOSED"), ...Array<Disposition>(12).fill("CALLBACK_SCHEDULED"),
  ...Array<Disposition>(10).fill("ESCALATED"), ...Array<Disposition>(9).fill("NOT_INTERESTED"),
  ...Array<Disposition>(8).fill("BUSY"), ...Array<Disposition>(10).fill("NO_ANSWER"),
  ...Array<Disposition>(4).fill("DND"), ...Array<Disposition>(4).fill("FAILED"),
];

function random(seed: number): () => number {
  let value = seed >>> 0;
  return () => { value = (1664525 * value + 1013904223) >>> 0; return value / 4294967296; };
}

function pick<T>(items: T[], rand: () => number): T { return items[Math.floor(rand() * items.length)]!; }
function isoDaysAgo(rand: () => number): string {
  const now = new Date();
  const istNow = new Date(now.getTime() + 330 * 60_000);
  const day = new Date(Date.UTC(istNow.getUTCFullYear(), istNow.getUTCMonth(), istNow.getUTCDate() - Math.floor(rand() * 120)));
  const hour = 9 + Math.floor(rand() * 12);
  const minute = Math.floor(rand() * 60);
  return new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), hour, minute) - 330 * 60_000).toISOString();
}
function shiftedIso(base: string, minutes: number): string { return new Date(new Date(base).getTime() + minutes * 60_000).toISOString(); }

export const SLA_POLICIES: SlaPolicy[] = [
  { priority: "URGENT", firstContactMinutes: 15, resolutionHours: 4 },
  { priority: "HIGH", firstContactMinutes: 60, resolutionHours: 8 },
  { priority: "NORMAL", firstContactMinutes: 240, resolutionHours: 24 },
  { priority: "LOW", firstContactMinutes: 480, resolutionHours: 48 },
];

export const MOCK_CAMPAIGNS: Campaign[] = [
  { id: "CMP-APP-01", name: "App adoption · Q4", objective: "App adoption", status: "ACTIVE", scriptVersion: "v2.4", segmentSize: 8200, maxAttempts: 3, retryGapHours: 24, languages: ["Hindi", "English", "Tamil"], region: "All India", callsDialed: 684, answerRate: 0.72, updatedAt: new Date().toISOString() },
  { id: "CMP-UPD-02", name: "App update follow-up", objective: "App update", status: "ACTIVE", scriptVersion: "v1.8", segmentSize: 3400, maxAttempts: 2, retryGapHours: 36, languages: ["English", "Kannada", "Telugu"], region: "South", callsDialed: 392, answerRate: 0.68, updatedAt: new Date().toISOString() },
  { id: "CMP-FEAT-03", name: "Feature discovery", objective: "Feature awareness", status: "PAUSED", scriptVersion: "v3.1", segmentSize: 12500, maxAttempts: 2, retryGapHours: 48, languages: ["Hindi", "Marathi", "Bengali"], region: "West", callsDialed: 251, answerRate: 0.64, updatedAt: new Date().toISOString() },
  { id: "CMP-CARD-04", name: "Card controls introduction", objective: "Feature awareness", status: "ACTIVE", scriptVersion: "v1.2", segmentSize: 5700, maxAttempts: 3, retryGapHours: 24, languages: ["Hindi", "English"], region: "North", callsDialed: 421, answerRate: 0.7, updatedAt: new Date().toISOString() },
  { id: "CMP-LOGIN-05", name: "Digital access support", objective: "Service support", status: "DRAFT", scriptVersion: "v0.9", segmentSize: 2100, maxAttempts: 2, retryGapHours: 24, languages: ["Tamil", "Telugu"], region: "South", callsDialed: 0, answerRate: 0, updatedAt: new Date().toISOString() },
  { id: "CMP-ALERT-06", name: "Account alerts awareness", objective: "Feature awareness", status: "ACTIVE", scriptVersion: "v2.0", segmentSize: 6100, maxAttempts: 2, retryGapHours: 48, languages: ["English", "Bengali"], region: "East", callsDialed: 252, answerRate: 0.66, updatedAt: new Date().toISOString() },
];

const TRANSCRIPTS: Record<string, string[]> = {
  CLOSED: ["Customer confirmed the app is updated and had no further questions.", "Customer reviewed the feature information and was satisfied.", "Customer confirmed successful access after the approved guidance."],
  CALLBACK_SCHEDULED: ["Customer was occupied and asked for a later follow-up.", "Customer requested a call during a more convenient time.", "Customer asked for a support callback about app access."],
  ESCALATED: ["Customer reported an app issue and requested human support.", "Customer could not complete the update and asked for assistance.", "Customer reported a repeated sign-in problem."],
  NOT_INTERESTED: ["Customer declined further product information.", "Customer said they were not interested in this call.", "Customer asked to conclude the conversation."],
  BUSY: ["Customer was driving and asked for a callback.", "Customer said this was not a convenient time.", "Customer was unavailable to continue."],
  NO_ANSWER: ["No answer was detected during the attempt."], DND: ["Number was suppressed by the demo DND scrub."], FAILED: ["Call attempt did not connect."],
};

function transcriptFor(disposition: Disposition, at: string, rand: () => number): TranscriptMessage[] {
  const h = Math.floor(new Date(at).getTime() / 3_600_000);
  const time = (offset: number) => new Date((h + offset) * 3_600_000).toISOString();
  const customerText = pick(TRANSCRIPTS[disposition] ?? TRANSCRIPTS.CLOSED!, rand);
  return [
    { id: `t-${h}-1`, speaker: "AVA", text: "Hello, I’m AVA, an automated assistant calling on behalf of the bank. Is now a convenient time?", time: time(0) },
    { id: `t-${h}-2`, speaker: "CUSTOMER", text: customerText, time: time(0), redacted: rand() < 0.04 },
    ...(disposition === "ESCALATED" || disposition === "CALLBACK_SCHEDULED" ? [{ id: `t-${h}-3`, speaker: "AVA" as const, text: "I’ve noted your request for a follow-up from the support team.", time: time(0) }] : []),
  ];
}

const AGENT_NAMES = ["Aarav S.", "Aditi R.", "Ananya K.", "Arjun M.", "Devika P.", "Ishaan D.", "Kabir N.", "Kavya T.", "Meera V.", "Neel G.", "Nisha B.", "Pranav C.", "Riya J.", "Sana F.", "Vihaan L.", "Zoya H."];

export function createMockSnapshot(): DashboardSnapshot {
  const rand = random(8241025);
  const agents: Agent[] = AGENT_NAMES.map((name, index) => ({
    id: `AG-${String(index + 1).padStart(3, "0")}`, name, team: index < 8 ? "Digital support · North" : "Digital support · South",
    languages: index % 3 === 0 ? ["Hindi", "English"] : index % 3 === 1 ? ["Tamil", "English"] : ["English", "Marathi"],
    availability: index < 6 ? "AVAILABLE" : index < 10 ? "ON_CALL" : index < 12 ? "BREAK" : "OFFLINE",
    activeCalls: index >= 6 && index < 10 ? 1 : 0, handledToday: 8 + Math.floor(rand() * 25),
    avgResolutionMin: 6 + Math.round(rand() * 15), slaHitPercent: 84 + Math.round(rand() * 15),
  }));
  const dispositions: Disposition[] = Array.from({ length: 2000 }, (_, index) => index < 18 ? "CLOSED" : pick(outcomes, rand));
  const calls: CallRecord[] = dispositions.map((disposition, index) => {
    const campaign = pick(MOCK_CAMPAIGNS, rand);
    const startedAt = isoDaysAgo(rand);
    const live = index < 18;
    const connected = live || !["NO_ANSWER", "DND", "FAILED"].includes(disposition);
    const appInstalled = rand() > 0.27;
    const issueCategory = disposition === "ESCALATED" || disposition === "CALLBACK_SCHEDULED" ? pick(issues, rand) : null;
    const customerNum = 1 + (index % 340);
    const customerRef = `CUST-${String(customerNum).padStart(5, "0")}`;
    const phoneEnd = String(100 + (customerNum * 31) % 900);
    return {
      id: `CALL-${String(index + 1).padStart(6, "0")}`, customerRef, maskedPhone: `+91 98XXX XX${phoneEnd}`,
      campaignId: campaign.id, campaignName: campaign.name, language: pick(languages, rand), region: pick(regions, rand),
      branch: pick(branches, rand), startedAt, durationSec: live ? 42 + Math.floor(rand() * 260) : 35 + Math.floor(rand() * 405),
      disposition: live ? null : disposition, status: live ? "IN_PROGRESS" : "COMPLETED", connected,
      resolutionMode: live ? "OPEN" : disposition === "ESCALATED" || disposition === "CALLBACK_SCHEDULED" ? "HUMAN" : disposition === "CLOSED" && index % 5 === 0 ? "HUMAN" : disposition === "CLOSED" ? "AI" : "OPEN",
      consented: connected && !["DND", "NO_ANSWER", "FAILED"].includes(disposition) && rand() > 0.11,
      appInstalled, appUpdated: appInstalled && rand() > 0.28, appVersion: appInstalled ? pick(["5.0.0", "4.9.2", "4.8.1", "4.7.0"], rand) : "—",
      sentiment: Math.round((rand() * 1.8 - 0.65) * 100) / 100, issueCategory,
      callbackId: null, escalationId: null, kuralState: live ? pick(["PERMISSION", "APP_STATUS", "UPDATE_HELP", "ISSUE_CAPTURE"], rand) : disposition === "ESCALATED" ? "HUMAN_ESCALATION" : "ENDED",
      intent: live ? pick(["AFFIRM", "BUSY", "APP_INSTALLED", "UPDATE_FAILURE", "OTHER"], rand) : disposition,
      policy: "ALLOWED", costInr: Math.round((0.38 + rand() * 0.95) * 100) / 100,
      complianceFlags: disposition === "DND" ? ["DND_SUPPRESSED"] : !connected ? [] : rand() > 0.97 ? ["CONSENT_REVIEW"] : [],
      featureInterest: rand() > 0.44 ? [pick(features, rand)] : [],
      summary: pick(TRANSCRIPTS[disposition] ?? TRANSCRIPTS.CLOSED!, rand), transcript: transcriptFor(disposition, startedAt, rand), recordingAvailable: false,
    };
  });

  const escalationCalls = calls.filter((call) => call.disposition === "ESCALATED");
  const callbacks: Callback[] = calls.filter((call) => call.disposition === "CALLBACK_SCHEDULED" || (call.disposition === "ESCALATED" && rand() > 0.35)).map((call, index) => {
    const status: Callback["status"] = index % 11 === 0 ? "OVERDUE" : index % 7 === 0 ? "COMPLETED" : index % 3 === 0 ? "IMMEDIATE" : "SCHEDULED";
    const agent = status === "COMPLETED" ? agents[index % agents.length]! : (index % 4 === 0 ? null : agents[index % agents.length]!);
    const due = status === "OVERDUE"
      ? new Date(Date.now() - (40 + Math.floor(rand() * 360)) * 60_000).toISOString()
      : status === "COMPLETED"
        ? shiftedIso(call.startedAt, 45 + Math.floor(rand() * 500))
        : new Date(Date.now() + (status === "IMMEDIATE" ? 10 + Math.floor(rand() * 40) : 30 + Math.floor(rand() * 150)) * 60_000).toISOString();
    const callback: Callback = {
      id: `CB-${String(index + 1).padStart(5, "0")}`, callId: call.id, customerRef: call.customerRef, maskedPhone: call.maskedPhone,
      campaignName: call.campaignName, reason: call.issueCategory ?? "Customer requested a convenient follow-up",
      status, requestedAt: status === "COMPLETED" ? shiftedIso(call.startedAt, call.durationSec / 60) : new Date(Date.now() - 8 * 60_000).toISOString(), preferredAt: status === "IMMEDIATE" ? null : due,
      preferredLanguage: call.language, assignedAgentId: agent?.id ?? null, slaDueAt: due,
      priority: status === "OVERDUE" ? "URGENT" : index % 4 === 0 ? "HIGH" : "NORMAL", resolutionNotes: "", rescheduledCount: index % 4,
    };
    call.callbackId = callback.id;
    return callback;
  });

  const escalations: EscalationCase[] = escalationCalls.map((call, index) => {
    const callback = callbacks.find((item) => item.callId === call.id);
    const status: EscalationCase["status"] = index % 13 === 0 ? "RESOLVED" : index % 4 === 0 ? "IN_PROGRESS" : index % 3 === 0 ? "ASSIGNED" : "NEW";
    const agent = status === "NEW" || index % 5 === 0 ? null : agents[index % agents.length]!;
    const due = status === "RESOLVED"
      ? shiftedIso(call.startedAt, 95)
      : index % 9 === 0
        ? new Date(Date.now() - Math.floor(rand() * 360) * 60_000).toISOString()
        : new Date(Date.now() + (45 + Math.floor(rand() * 1200)) * 60_000).toISOString();
    const issue = call.issueCategory ?? "Mobile app support";
    const c: EscalationCase = {
      id: `CASE-${String(index + 1).padStart(5, "0")}`, callId: call.id, callbackId: callback?.id ?? null,
      customerRef: call.customerRef, maskedPhone: call.maskedPhone,
      issueSummary: `Customer needs follow-up for ${issue.toLowerCase()}.`, customerIssue: call.summary, category: issue,
      severity: index % 13 === 0 ? "CRITICAL" : index % 5 === 0 ? "HIGH" : index % 3 === 0 ? "MEDIUM" : "LOW",
      status, appVersion: call.appVersion, appInstalled: call.appInstalled, preferredLanguage: call.language,
      preferredTime: callback?.preferredAt ?? "As soon as available", consentFlags: ["Voice follow-up consent recorded"],
      assignedAgentId: agent?.id ?? null, slaDueAt: due, priority: index % 10 === 0 ? "URGENT" : index % 4 === 0 ? "HIGH" : "NORMAL",
      resolutionNotes: status === "RESOLVED" ? "Customer confirmed access after approved troubleshooting." : "",
      createdAt: call.startedAt, firstContactAt: status === "NEW" ? null : shiftedIso(call.startedAt, 27),
      resolvedAt: status === "RESOLVED" ? shiftedIso(call.startedAt, 95) : null,
    };
    call.escalationId = c.id;
    return c;
  });

  const workloads: AgentWorkload[] = agents.map((agent) => {
    const assignedCases = escalations.filter((c) => c.assignedAgentId === agent.id && c.status !== "RESOLVED");
    return { agentId: agent.id, assignedCases: assignedCases.length, immediateCallbacks: callbacks.filter((c) => c.assignedAgentId === agent.id && c.status === "IMMEDIATE").length,
      overdueCases: assignedCases.filter((c) => new Date(c.slaDueAt).getTime() < Date.now()).length,
      utilizationPercent: agent.availability === "ON_CALL" ? 83 + Math.floor(rand() * 16) : agent.availability === "AVAILABLE" ? 34 + Math.floor(rand() * 41) : 0 };
  });

  const consents: ConsentRecord[] = calls.filter((call) => call.connected).map((call) => ({
    callId: call.id, customerRef: call.customerRef, purpose: "Mobile app service call", consented: call.consented,
    recordedAt: call.startedAt, channel: "VOICE", retentionUntil: new Date(new Date(call.startedAt).setFullYear(new Date(call.startedAt).getFullYear() + 1)).toISOString(),
  }));

  const auditEvents: AuditEvent[] = calls.slice(0, 80).map((call, index) => ({
    id: `AUD-${String(index + 1).padStart(6, "0")}`, actor: index % 3 === 0 ? "system:ava-demo" : `AG-${String(1 + index % agents.length).padStart(3, "0")}`,
    actorRole: index % 3 === 0 ? "OPS_MANAGER" : "AGENT", action: index % 3 === 0 ? "CALL_RECORD_CREATED" : "CASE_REVIEWED",
    resourceType: "CALL", resourceId: call.id, timestamp: call.startedAt,
    ip: `192.0.2.${1 + index % 240}`, detail: "Synthetic audit entry; not a production audit record.",
  }));

  const egressLogs: LLMEgressLog[] = [];
  const summary: DashboardSnapshot = { calls, campaigns: [...MOCK_CAMPAIGNS], callbacks, escalations, agents, workloads, slaPolicies: SLA_POLICIES, consents, auditEvents, egressLogs };
  return summary;
}

export const MOCK_SNAPSHOT = createMockSnapshot();

export function currentDemoRoleActor(role: Role): string {
  return role === "AGENT" ? "AG-001" : role === "SUPERVISOR" ? "SUP-001" : role === "COMPLIANCE" ? "AUD-001" : "OPS-001";
}
