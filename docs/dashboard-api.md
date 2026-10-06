# Operations dashboard API contract

The role-aware operations dashboard uses `frontend/src/services/dashboardApi.ts`. Its default adapter is deterministic, synthetic browser-local mock data. Setting `VITE_DASHBOARD_API_MODE=live` switches the adapter to the contract below. **The current FastAPI service does not yet implement these operations endpoints**, so leave the mode as `mock` until a backend implementation exists. The existing KURAL conversation API remains available at `/api/v1/...` and is not replaced by this dashboard contract.

All endpoints require authenticated, role-authorized access in production. The `role` supplied by the browser is presentation context only; it must never grant access. All timestamps are ISO-8601 UTC and displayed in `Asia/Kolkata`. `customerRef` must be synthetic or pseudonymous; `maskedPhone` must be masked before reaching the UI. Do not return OTPs, PINs, passwords, CVV/CVC, authentication secrets, raw payment credentials, or unredacted provider payloads.

## Read endpoints

| Method | Path | Response |
| --- | --- | --- |
| GET | `/api/kpis` | `KpiSummary` (see below); can be derived from the same call set and filters. |
| GET | `/api/calls` | `CallRecord[]`; optional `from`, `to`, `campaignId`, `language`, `region`, `cursor`, `limit`. |
| GET | `/api/campaigns` | `Campaign[]`. |
| GET | `/api/callbacks` | `Callback[]`. |
| GET | `/api/escalations` | `EscalationCase[]`. |
| GET | `/api/agents` | `{ agents: Agent[], workloads: AgentWorkload[], slaPolicies: SlaPolicy[] }`. |
| GET | `/api/compliance/summary` | `{ consents: ConsentRecord[], egressLogs: LLMEgressLog[], metrics: object }`. |
| GET | `/api/audit` | `AuditEvent[]`; cursor-paginated, access-controlled, append-only. |
| GET | `/api/reports/schedules` | `ReportSchedule[]`; authorized operations/compliance access. |

The current frontend live adapter expects arrays for calls, campaigns, callbacks, escalations and audit; it expects an array for `/api/agents` today. The agent endpoint should be normalized in the adapter to return the documented workload envelope when backend support is implemented.

## Mutations

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/campaigns` | Create a draft campaign. |
| PATCH | `/api/campaigns/{campaignId}` | Pause/resume; version changes are separately audited. |
| PATCH | `/api/escalations/{caseId}` | Assign case or update status/resolution notes. |
| PATCH | `/api/callbacks/{callbackId}` | Assign, reschedule or complete callback. |
| POST | `/api/callbacks` | Create a scheduled or immediate callback from a resolved support case. |
| POST | `/api/audit` | Append a server-authenticated audit event. Actor and role come from auth context, never trusted request fields. |
| POST | `/api/reports/schedules` | Create a daily PDF/XLSX report schedule with validated recipient and delivery time. |

Mutations must enforce role policy on the server, validate legal state transitions, redact notes before persistence, and write the business change and audit event atomically. A production report scheduler must render the report and send it through an approved bank mail service; the prototype only stores a local schedule and sends no email. Production transcript/audio reads also need dedicated permission checks and access audit events. The prototype records only local mock events. No telephony action is implied by a case/callback mutation; click-to-call should invoke the bank softphone/CTI in production, never a browser-originated direct call.

## Shared record shapes

The authoritative TypeScript field definitions are in `frontend/src/types.ts` (`CallRecord`, `Campaign`, `Callback`, `EscalationCase`, `Agent`, `AgentWorkload`, `SlaPolicy`, `ConsentRecord`, `AuditEvent`, `LLMEgressLog`, `KpiSummary`). Dates are ISO strings. `CallRecord` intentionally contains masked identifiers, policy outcomes and sanitized transcript text only. Recording URLs/audio bytes are not in this UI contract; a production recording service should use short-lived, authorization-checked references and log each playback/view.

Example sanitized call record:

```json
{
  "id": "CALL-000042",
  "customerRef": "CUST-00042",
  "maskedPhone": "+91 98XXX XX231",
  "campaignId": "CMP-APP-01",
  "campaignName": "App adoption",
  "language": "Hindi",
  "region": "North",
  "branch": "Delhi NCR",
  "startedAt": "2026-10-05T09:30:00Z",
  "durationSec": 142,
  "disposition": "CLOSED",
  "resolutionMode": "AI",
  "status": "COMPLETED",
  "connected": true,
  "consented": true,
  "appInstalled": true,
  "appUpdated": true,
  "appVersion": "5.0.0",
  "sentiment": 0.42,
  "issueCategory": null,
  "callbackId": null,
  "escalationId": null,
  "kuralState": "ENDED",
  "intent": "APP_INSTALLED",
  "policy": "ALLOWED",
  "costInr": 0.74,
  "complianceFlags": [],
  "featureInterest": [],
  "summary": "Customer confirmed the app is updated and had no further questions.",
  "transcript": [],
  "recordingAvailable": false
}
```

Use stable IDs and cursor pagination in production. The present demo loads a fixed 2,000-row generated snapshot and is not a scalability or live-update implementation.
