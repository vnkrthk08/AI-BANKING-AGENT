export type VoiceState = "READY" | "LISTENING" | "PROCESSING" | "SPEAKING" | "INTERRUPTED" | "SILENCE_REMINDER" | "TERMINATING" | "ENDED";
export type PolicyDecision = "ALLOWED" | "BLOCKED";
export type Role = "OPS_MANAGER" | "SUPERVISOR" | "AGENT" | "COMPLIANCE" | "COMPLIANCE_OFFICER" | "AUDITOR" | "SYSTEM_ADMIN" | "SUPER_ADMIN";
export type Disposition = "CLOSED" | "CALLBACK_SCHEDULED" | "ESCALATED" | "NOT_INTERESTED" | "BUSY" | "NO_ANSWER" | "DND" | "FAILED";
export type CallStatus = "IN_PROGRESS" | "COMPLETED";
export type CallbackStatus = "IMMEDIATE" | "SCHEDULED" | "OVERDUE" | "COMPLETED" | "CANCELLED" | "DUE" | "DIALING" | "REQUESTED" | "FAILED";
export type CaseStatus = "NEW" | "ASSIGNED" | "IN_PROGRESS" | "RESOLVED";
export type Priority = "URGENT" | "HIGH" | "NORMAL" | "LOW";
export type AgentAvailability = "AVAILABLE" | "ON_CALL" | "BREAK" | "OFFLINE";


export interface SessionResponse {
  session_id: string;
  state: string;
  response: string;
  customer_ref: string;
}

export interface TurnResponse {
  session_id: string;
  state: string;
  intent: string;
  response: string;
  ended: boolean;
  case_id: string | null;
  callback_id: string | null;
  policy_decision: PolicyDecision;
  sanitized_user_text: string;
}

export interface SessionDetail {
  session_id: string;
  current_state: string;
  turns: Array<{ turn_order: number; text: string; intent: string; state: string; response: string }>;
}

export interface TranscriptMessage {
  id: string;
  speaker: "AVA" | "CUSTOMER" | "Subbu";
  text: string;
  time: string;
  redacted?: boolean;
}

export interface Campaign {
  id: string;
  name: string;
  objective: string;
  status: "ACTIVE" | "PAUSED" | "DRAFT";
  scriptVersion: string;
  segmentSize: number;
  maxAttempts: number;
  retryGapHours: number;
  languages: string[];
  region: string;
  callsDialed: number;
  answerRate: number;
  updatedAt: string;
}

export interface CallRecord {
  id: string;
  customerRef: string;
  maskedPhone: string;
  campaignId: string;
  campaignName: string;
  language: string;
  region: string;
  branch: string;
  startedAt: string;
  durationSec: number;
  disposition: Disposition | null;
  resolutionMode: "AI" | "HUMAN" | "OPEN";
  status: CallStatus;
  connected: boolean;
  consented: boolean;
  appInstalled: boolean;
  appUpdated: boolean;
  appVersion: string;
  sentiment: number;
  issueCategory: string | null;
  callbackId: string | null;
  escalationId: string | null;
  kuralState: string;
  intent: string;
  policy: PolicyDecision;
  costInr: number;
  complianceFlags: string[];
  featureInterest: string[];
  summary: string;
  transcript: TranscriptMessage[];
  recordingAvailable: boolean;
}

export interface Callback {
  id: string;
  callId: string;
  customerRef: string;
  maskedPhone: string;
  campaignName: string;
  reason: string;
  status: CallbackStatus;
  requestedAt: string;
  preferredAt: string | null;
  preferredLanguage: string;
  assignedAgentId: string | null;
  slaDueAt: string;
  priority: "URGENT" | "HIGH" | "NORMAL" | "LOW";
  resolutionNotes: string;
  rescheduledCount: number;
}

export interface EscalationCase {
  id: string;
  callId: string;
  callbackId: string | null;
  customerRef: string;
  maskedPhone: string;
  issueSummary: string;
  customerIssue: string;
  category: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  status: CaseStatus;
  appVersion: string;
  appInstalled: boolean;
  preferredLanguage: string;
  preferredTime: string;
  consentFlags: string[];
  assignedAgentId: string | null;
  slaDueAt: string;
  priority: "URGENT" | "HIGH" | "NORMAL" | "LOW";
  resolutionNotes: string;
  createdAt: string;
  firstContactAt: string | null;
  resolvedAt: string | null;
}

export interface Agent {
  id: string;
  name: string;
  team: string;
  languages: string[];
  availability: AgentAvailability;
  activeCalls: number;
  handledToday: number;
  avgResolutionMin: number;
  slaHitPercent: number;
}

export interface AgentWorkload {
  agentId: string;
  assignedCases: number;
  immediateCallbacks: number;
  overdueCases: number;
  utilizationPercent: number;
}

export interface SlaPolicy {
  priority: "URGENT" | "HIGH" | "NORMAL" | "LOW";
  firstContactMinutes: number;
  resolutionHours: number;
}

export interface ConsentRecord {
  callId: string;
  customerRef: string;
  purpose: string;
  consented: boolean;
  recordedAt: string;
  channel: "VOICE";
  retentionUntil: string;
}

export interface AuditEvent {
  id: string;
  actor: string;
  actorRole: Role;
  action: string;
  resourceType: string;
  resourceId: string;
  timestamp: string;
  ip: string;
  detail: string;
}

export interface LLMEgressLog {
  id: string;
  callId: string;
  provider: string;
  fieldsSent: string[];
  redactedText: string;
  timestamp: string;
  status: "SENT" | "BLOCKED";
}

export interface KpiSummary {
  callsDialed: number;
  connected: number;
  answerRate: number;
  closed: number;
  callbacks: number;
  escalated: number;
  refusedDnd: number;
  averageDurationSec: number;
  averageSentiment: number;
  costPerCallInr: number;
  costPerResolvedInr: number;
}

export interface DashboardSnapshot {
  calls: CallRecord[];
  campaigns: Campaign[];
  callbacks: Callback[];
  escalations: EscalationCase[];
  agents: Agent[];
  workloads: AgentWorkload[];
  slaPolicies: SlaPolicy[];
  consents: ConsentRecord[];
  auditEvents: AuditEvent[];
  egressLogs: LLMEgressLog[];
}

export interface DashboardFilters {
  range: "7D" | "30D" | "60D" | "ALL";
  campaign: string;
  language: string;
  region: string;
}

export interface ReportSchedule {
  id: string;
  cadence: "DAILY";
  time: string;
  formats: Array<"PDF" | "XLSX">;
  recipient: string;
  enabled: boolean;
  demoOnly: boolean;
  createdAt: string;
}

export interface SessionCreateResponse {
  session_id: string;
  state: string;
  response: string;
  customer_ref: string;
}

export interface CaseRecord { case_id: string; session_id: string; customer_ref: string; category: string; description: string; status: string; callback_requested: boolean }
