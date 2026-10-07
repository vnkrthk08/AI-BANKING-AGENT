import { useState } from "react";
import { ShieldCheck, LockKey } from "@phosphor-icons/react";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { formatDateTime } from "../services/selectors";
import { ExportButtons } from "../components/ExportButtons";

export function CompliancePage() {
  const { snapshot, loading, error, refresh } = useDashboard();
  const [role] = useRole();
  const [notice, setNotice] = useState("");

  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;

  const consented = snapshot.consents.filter((x) => x.consented).length;
  const dnd = snapshot.calls.filter((x) => x.disposition === "DND" && x.connected).length;
  const outOfWindow = snapshot.calls.filter((call) => {
    const parts = new Intl.DateTimeFormat("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date(call.startedAt));
    const hour = Number(parts.find((x) => x.type === "hour")?.value ?? 0);
    return hour < 9 || hour >= 21;
  }).length;
  const audit = snapshot.auditEvents.slice(0, 200);

  return (
    <>
      <PageHeading
        eyebrow="REGULATORY ASSURANCE &amp; AUDIT"
        title="Compliance & audit"
        description="Consent compliance, RBI contact-window enforcement, PII redaction, and access controls."
        actions={
          <ExportButtons
            role={role}
            rows={audit.map((e) => ({
              timestamp: e.timestamp,
              actor: e.actor,
              role: e.actorRole,
              action: e.action,
              resourceType: e.resourceType,
              resourceId: e.resourceId,
              detail: e.detail,
              ip: e.ip,
            }))}
            name="kural-audit-log"
            title="KURAL audit events"
          />
        }
      />
      {notice && (
        <div className="ops-notice-banner" role="status">
          {notice}
          <button onClick={() => setNotice("")}>Dismiss</button>
        </div>
      )}

      <div className="ops-compliance-kpis">
        <div>
          <small>CONSENT COVERAGE</small>
          <strong>
            {snapshot.consents.length ? ((consented / snapshot.consents.length) * 100).toFixed(1) : "0.0"}%
          </strong>
          <span>
            {consented.toLocaleString("en-IN")} / {snapshot.consents.length.toLocaleString("en-IN")} connected records
          </span>
        </div>
        <div className={dnd ? "risk" : "safe"}>
          <small>DND SUPPRESSION</small>
          <strong>{dnd}</strong>
          <span>{dnd === 0 ? "100% compliant · Zero violations" : "Requires immediate review"}</span>
        </div>
        <div className={outOfWindow ? "risk" : "safe"}>
          <small>OUT-OF-WINDOW DIALS</small>
          <strong>{outOfWindow}</strong>
          <span>Enforced: 09:00–21:00 IST</span>
        </div>
        <div className="safe">
          <small>RECORDING SECURITY</small>
          <strong>100%</strong>
          <span>AES-256 encrypted voice logs</span>
        </div>
      </div>

      <div className="ops-compliance-grid">
        <Panel title="Security & Data Boundary" subtitle="Telephony egress and strict privacy controls">
          <div className="ops-boundary-state">
            <ShieldCheck size={20} />
            <div>
              <strong>Deterministic Boundary Active</strong>
              <span>Zero external LLM decision making. All state transitions governed by bank policy FSM.</span>
            </div>
            <StatusPill value="PROTECTED" />
          </div>
          <div className="ops-fact-list">
            <span>Model boundary<strong>Local NLU Classification (Zero conversational drift)</strong></span>
            <span>PII Redaction<strong>Automated regex + token masking before logging</strong></span>
            <span>Customer Redaction<strong>{snapshot.calls.filter((c) => c.transcript.some((t) => t.redacted)).length.toLocaleString("en-IN")} records sanitized</strong></span>
            <span>Data Residency<strong>India Central (Mumbai DC · RBI Compliant)</strong></span>
          </div>
          <p className="ops-helper">
            <LockKey size={14} style={{ display: "inline", verticalAlign: "middle", marginRight: "4px" }} />
            All call telemetry and transcripts reside exclusively within Town Bank banking perimeter.
          </p>
        </Panel>

        <Panel title="Policy & Regulatory Enforcements" subtitle="Real-time compliance checks across active calls">
          <div className="ops-policy-list">
            <div>
              <span>Customer Consent Pre-check</span>
              <StatusPill value={consented ? "CONSENTED" : "REQUIRED"} />
            </div>
            <div>
              <span>National DND Registry Filter</span>
              <StatusPill value={dnd === 0 ? "ALLOWED" : "FLAGGED"} />
            </div>
            <div>
              <span>TRAI 09:00 - 21:00 Window</span>
              <StatusPill value={outOfWindow === 0 ? "ALLOWED" : "FLAGGED"} />
            </div>
            <div>
              <span>Encrypted Storage Retention</span>
              <StatusPill value="ACTIVE" />
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="Supervisor Audit Events" subtitle="Immutable event trail with actor and IP verification">
        <div className="ops-table-wrap">
          <table className="ops-audit-table">
            <thead>
              <tr>
                <th>Timestamp (IST)</th>
                <th>Actor / role</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {audit.slice(0, 100).map((e) => (
                <tr key={e.id}>
                  <td>{formatDateTime(e.timestamp)}</td>
                  <td>
                    {e.actor}
                    <small>{e.actorRole}</small>
                  </td>
                  <td>{e.action}</td>
                  <td>
                    {e.resourceType} · {e.resourceId}
                  </td>
                  <td>{e.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="ops-helper">
          Transcript views, role modifications, and supervisory takeovers are logged immutably for compliance audits.
        </p>
      </Panel>
    </>
  );
}
