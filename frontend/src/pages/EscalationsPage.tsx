import { useState } from "react";
import { ArrowUpRight, Plus, WarningCircle } from "@phosphor-icons/react";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { dashboardApi } from "../services/dashboardApi";
import { formatDateTime } from "../services/selectors";
import type { CaseStatus, Priority } from "../types";

const columns: Array<{ status: CaseStatus; label: string }> = [
  { status: "NEW", label: "New" },
  { status: "ASSIGNED", label: "Assigned" },
  { status: "IN_PROGRESS", label: "In progress" },
  { status: "RESOLVED", label: "Resolved" },
];

export function EscalationsPage() {
  const { snapshot, loading, error, refresh } = useDashboard();
  const [role] = useRole();
  const [notice, setNotice] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [customerRef, setCustomerRef] = useState("");
  const [category, setCategory] = useState("APP_SUPPORT");
  const [priority, setPriority] = useState<Priority>("NORMAL");

  const [issueSummary, setIssueSummary] = useState("");

  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;

  async function move(id: string, status: CaseStatus) {
    await dashboardApi.updateCase(id, {
      status,
      firstContactAt: status === "IN_PROGRESS" ? new Date().toISOString() : undefined,
      resolvedAt: status === "RESOLVED" ? new Date().toISOString() : null,
    });
    await dashboardApi.recordAudit("CASE_STATUS_CHANGED", "CASE", id, role, `Status set to ${status}`);
    await refresh();
    setNotice("Case status updated and synced successfully.");
  }

  async function assign(id: string, agentId: string) {
    await dashboardApi.updateCase(id, {
      assignedAgentId: agentId || null,
      status: agentId ? "ASSIGNED" : "NEW",
    });
    await dashboardApi.recordAudit("CASE_ASSIGNED", "CASE", id, role, agentId || "Unassigned");
    await refresh();
  }

  async function handleCreateCase(e: React.FormEvent) {
    e.preventDefault();
    if (!customerRef.trim() || !issueSummary.trim()) return;
    await dashboardApi.createCase({
      customer_ref: customerRef.trim(),
      customerRef: customerRef.trim(),
      category,
      issue_code: category,
      priority,
      description: issueSummary.trim(),
      summary: issueSummary.trim(),
    });
    await dashboardApi.recordAudit("CASE_CREATED", "CASE", customerRef.trim(), role, `Created case for ${customerRef}`);
    setShowCreate(false);
    setCustomerRef("");
    setIssueSummary("");
    await refresh();
    setNotice("Support escalation case created successfully.");
  }

  const atRiskCount = snapshot.escalations.filter(
    (x) => x.status !== "RESOLVED" && new Date(x.slaDueAt).getTime() < Date.now()
  ).length;

  return (
    <>
      <PageHeading
        eyebrow="HUMAN FOLLOW-UP"
        title="Escalations"
        description="Explicit case lifecycle, ownership and SLA visibility across the frontline support queue."
        actions={
          <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
            <button className="ops-button ops-button-primary" onClick={() => setShowCreate(true)}>
              <Plus size={15} /> Open Support Case
            </button>
            <span className="ops-mini-label">
              <WarningCircle size={15} />
              {atRiskCount} SLA at risk
            </span>
          </div>
        }
      />

      {notice && (
        <div className="ops-notice-banner" role="status">
          {notice}
          <button onClick={() => setNotice("")}>Dismiss</button>
        </div>
      )}

      {showCreate && (
        <form className="ops-inline-create" onSubmit={handleCreateCase}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px", width: "100%" }}>
            <label>
              Customer Ref
              <input
                value={customerRef}
                onChange={(e) => setCustomerRef(e.target.value)}
                placeholder="e.g. CUST-00001"
                required
              />
            </label>
            <label>
              Category
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="APP_SUPPORT">App Support</option>
                <option value="LOGIN_ISSUE">Login &amp; Auth Issue</option>
                <option value="SECURITY_CONCERN">Security / Fraud Concern</option>
                <option value="COMPLAINT">Frontline Complaint</option>
              </select>
            </label>
            <label>
              Priority
              <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
                <option value="LOW">Low</option>

                <option value="NORMAL">Normal</option>
                <option value="HIGH">High</option>
                <option value="URGENT">Urgent</option>
              </select>
            </label>
          </div>
          <label style={{ width: "100%" }}>
            Issue Summary
            <input
              value={issueSummary}
              onChange={(e) => setIssueSummary(e.target.value)}
              placeholder="Describe customer issue requiring frontline intervention"
              required
            />
          </label>
          <div style={{ display: "flex", gap: "10px", marginTop: "6px" }}>
            <button type="submit" className="ops-button ops-button-primary">Save Case</button>
            <button type="button" className="ops-text-button" onClick={() => setShowCreate(false)}>Cancel</button>
          </div>
        </form>
      )}

      <div className="ops-kanban">
        {columns.map((col) => {
          const items = snapshot.escalations.filter((item) => item.status === col.status);
          return (
            <section className="ops-kanban-column" key={col.status}>
              <header>
                <strong>{col.label}</strong>
                <span>{items.length}</span>
              </header>

              {items.length === 0 ? (
                <div style={{ padding: "32px 16px", textAlign: "center", color: "#94a3b8", fontSize: "12.5px" }}>
                  No {col.label.toLowerCase()} cases
                </div>
              ) : (
                items.slice(0, 100).map((item) => (
                  <article className="ops-case-card" key={item.id}>
                    <div className="ops-case-card-top">
                      <StatusPill value={item.priority} />
                      <small>{item.id}</small>
                    </div>
                    <h3>
                      {item.customerRef}
                      <small>{item.maskedPhone}</small>
                    </h3>
                    <p>{item.issueSummary}</p>
                    <div className="ops-case-card-meta">
                      <StatusPill value={item.severity} />
                      <span>SLA {formatDateTime(item.slaDueAt)} IST</span>
                    </div>
                    <div className="ops-case-card-meta">
                      <span>{item.category} · {item.preferredLanguage}</span>
                      {item.callId && (
                        <a href={`/call-log?query=${encodeURIComponent(item.callId)}`} aria-label={`Open call ${item.callId}`}>
                          {item.callId}
                          <ArrowUpRight size={13} />
                        </a>
                      )}
                    </div>
                    {role !== "AGENT" && (
                      <label className="ops-assign-select">
                        <select
                          aria-label={`Assign case ${item.id}`}
                          value={item.assignedAgentId ?? ""}
                          onChange={(e) => void assign(item.id, e.target.value)}
                        >
                          <option value="">Unassigned</option>
                          {snapshot.agents.map((agent) => (
                            <option key={agent.id} value={agent.id}>
                              {agent.name} · {agent.availability.toLowerCase()}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                    {col.status !== "RESOLVED" && (
                      <div className="ops-case-card-actions">
                        <button
                          className="ops-button ops-button-secondary"
                          onClick={() =>
                            void move(
                              item.id,
                              col.status === "NEW"
                                ? "ASSIGNED"
                                : col.status === "ASSIGNED"
                                ? "IN_PROGRESS"
                                : "RESOLVED"
                            )
                          }
                        >
                          {col.status === "IN_PROGRESS" ? "Resolve case" : "Move forward"}
                        </button>
                      </div>
                    )}
                  </article>
                ))
              )}
            </section>
          );
        })}
      </div>
      <p className="ops-table-note">Case assignment and status changes are audited under banking security policy.</p>
    </>
  );
}
