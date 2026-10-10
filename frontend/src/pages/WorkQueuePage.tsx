import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowsClockwise,
  CheckCircle,
  ClockAfternoon,
  PencilSimple,
  X,
} from "@phosphor-icons/react";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../hooks/DashboardContext";
import { dashboardApi } from "../services/dashboardApi";
import type { Callback, EscalationCase } from "../types";

export function WorkQueuePage() {
  const { snapshot, refresh } = useDashboard();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const [activeTab, setActiveTab] = useState<"escalations" | "callbacks">(
    tabParam === "callbacks" ? "callbacks" : "escalations"
  );

  // Modals state
  const [selectedCase, setSelectedCase] = useState<EscalationCase | null>(null);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [assignedAgent, setAssignedAgent] = useState("AG-001");
  const [resolveModalOpen, setResolveModalOpen] = useState(false);
  const [resolveNotes, setResolveNotes] = useState("");

  const [selectedCallback, setSelectedCallback] = useState<Callback | null>(null);
  const [rescheduleModalOpen, setRescheduleModalOpen] = useState(false);
  const [rescheduleTime, setRescheduleTime] = useState("Tomorrow 3:00 PM");

  const [filterPriority, setFilterPriority] = useState<string>("ALL");
  const [actionLoading, setActionLoading] = useState(false);

  const escalations = snapshot?.escalations ?? [];
  const callbacks = snapshot?.callbacks ?? [];

  const filteredEscalations = escalations.filter(
    (e) => filterPriority === "ALL" || e.priority === filterPriority
  );

  async function handleAssignSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedCase) return;
    setActionLoading(true);
    try {
      await dashboardApi.updateCase(selectedCase.id, {
        assignedAgentId: assignedAgent,
        status: "ASSIGNED",
      });
      setAssignModalOpen(false);
      refresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleResolveSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedCase) return;
    setActionLoading(true);
    try {
      await dashboardApi.updateCase(selectedCase.id, {
        status: "RESOLVED",
        resolutionNotes: resolveNotes,
      });
      setResolveModalOpen(false);
      setResolveNotes("");
      refresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleRescheduleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedCallback) return;
    setActionLoading(true);
    try {
      await dashboardApi.updateCallback(selectedCallback.id, {
        preferredAt: rescheduleTime,
        status: "SCHEDULED",
      });
      setRescheduleModalOpen(false);
      refresh();
    } finally {
      setActionLoading(false);
    }
  }

  async function handleCancelCallback(cb: Callback) {
    if (!confirm(`Cancel scheduled callback ${cb.id} for customer ${cb.customerRef}?`)) return;
    setActionLoading(true);
    try {
      await dashboardApi.updateCallback(cb.id, {
        status: "COMPLETED",
        resolutionNotes: "Cancelled by operations",
      });
      refresh();
    } finally {
      setActionLoading(false);
    }
  }

  return (
    <div className="ops-page">
      <div className="ops-page-header">
        <div>
          <h1 className="ops-page-title">Work Queue</h1>
          <p className="ops-page-subtitle">
            Unified human banking operations: prioritized customer escalations, SLA deadlines & governed callback fulfillment.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button className="ops-button" onClick={() => refresh()}>
            <ArrowsClockwise size={16} /> Refresh Queue
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="ops-tabs" style={{ marginBottom: "1.25rem" }}>
        <button
          className={`ops-tab ${activeTab === "escalations" ? "active" : ""}`}
          onClick={() => setActiveTab("escalations")}
        >
          Support Escalations ({escalations.length})
        </button>
        <button
          className={`ops-tab ${activeTab === "callbacks" ? "active" : ""}`}
          onClick={() => setActiveTab("callbacks")}
        >
          Scheduled Callbacks ({callbacks.length})
        </button>
      </div>

      {/* TAB 1: SUPPORT ESCALATIONS */}
      {activeTab === "escalations" && (
        <div className="ops-card">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "1rem",
              flexWrap: "wrap",
              gap: "0.5rem",
            }}
          >
            <h3 style={{ margin: 0 }}>Active Escalations & Disputes</h3>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <label style={{ fontSize: "0.85rem", color: "var(--ops-muted)" }}>Priority:</label>
              <select
                className="ops-select"
                value={filterPriority}
                onChange={(e) => setFilterPriority(e.target.value)}
              >
                <option value="ALL">All Priorities</option>
                <option value="URGENT">URGENT</option>
                <option value="HIGH">HIGH</option>
                <option value="NORMAL">NORMAL</option>
                <option value="LOW">LOW</option>
              </select>
            </div>
          </div>

          {filteredEscalations.length === 0 ? (
            <div className="ops-empty-state" style={{ padding: "3rem 1rem", textAlign: "center" }}>
              <CheckCircle size={48} style={{ color: "#10b981", marginBottom: "0.75rem" }} />
              <h3 style={{ margin: "0 0 0.5rem 0" }}>Work Queue Clear</h3>
              <p style={{ color: "var(--ops-muted)", maxWidth: "400px", margin: "0 auto" }}>
                There are no open escalations or disputes pending assignment. All customer cases have met SLA targets.
              </p>
            </div>
          ) : (
            <div className="ops-table-wrapper">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Case ID</th>
                    <th>Customer</th>
                    <th>Category</th>
                    <th>Priority</th>
                    <th>SLA Deadline</th>
                    <th>Assigned Agent</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEscalations.map((esc) => {
                    const isOverdue = new Date(esc.slaDueAt).getTime() < Date.now();
                    return (
                      <tr key={esc.id}>
                        <td>
                          <strong>{esc.id}</strong>
                        </td>
                        <td>{esc.customerRef}</td>
                        <td>{esc.category || esc.customerIssue || esc.issueSummary}</td>
                        <td>
                          <span
                            className={`ops-badge ${
                              esc.priority === "URGENT" || esc.priority === "HIGH"
                                ? "ops-badge-red"
                                : "ops-badge-teal"
                            }`}
                          >
                            {esc.priority}
                          </span>
                        </td>
                        <td>
                          <span style={{ color: isOverdue ? "#ef4444" : "inherit" }}>
                            {new Date(esc.slaDueAt).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}
                            {isOverdue && " (Breached)"}
                          </span>
                        </td>
                        <td>{esc.assignedAgentId || <span style={{ color: "var(--ops-muted)" }}>Unassigned</span>}</td>
                        <td>
                          <StatusPill value={esc.status} />
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: "0.25rem" }}>
                            {esc.status !== "RESOLVED" && (
                              <>
                                <button
                                  className="ops-button ops-button-sm"
                                  onClick={() => {
                                    setSelectedCase(esc);
                                    setAssignModalOpen(true);
                                  }}
                                >
                                  Assign
                                </button>
                                <button
                                  className="ops-button ops-button-sm ops-button-primary"
                                  onClick={() => {
                                    setSelectedCase(esc);
                                    setResolveModalOpen(true);
                                  }}
                                >
                                  Resolve
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: SCHEDULED CALLBACKS */}
      {activeTab === "callbacks" && (
        <div className="ops-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h3 style={{ margin: 0 }}>Governed Customer Callbacks</h3>
            <span className="ops-badge ops-badge-teal">TRAI Calling Window: 09:00 - 19:00 IST</span>
          </div>

          {callbacks.length === 0 ? (
            <div className="ops-empty-state" style={{ padding: "3rem 1rem", textAlign: "center" }}>
              <ClockAfternoon size={48} style={{ color: "var(--ops-muted)", marginBottom: "0.75rem" }} />
              <h3 style={{ margin: "0 0 0.5rem 0" }}>No Callbacks Scheduled</h3>
              <p style={{ color: "var(--ops-muted)", maxWidth: "420px", margin: "0 auto" }}>
                No customer callbacks are currently booked. Callbacks scheduled during voice interactions will queue here automatically.
              </p>
            </div>
          ) : (
            <div className="ops-table-wrapper">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Callback ID</th>
                    <th>Customer</th>
                    <th>Scheduled Slot</th>
                    <th>Reason</th>
                    <th>Assigned Agent</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {callbacks.map((cb) => (
                    <tr key={cb.id}>
                      <td>
                        <strong>{cb.id}</strong>
                      </td>
                      <td>{cb.customerRef}</td>
                      <td>
                        <strong>{cb.preferredAt}</strong>
                      </td>
                      <td>{cb.reason}</td>
                      <td>{cb.assignedAgentId || "Subbu Queue"}</td>
                      <td>
                        <StatusPill value={cb.status} />
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: "0.25rem" }}>
                          {cb.status !== "COMPLETED" && (
                            <>
                              <button
                                className="ops-button ops-button-sm"
                                onClick={() => {
                                  setSelectedCallback(cb);
                                  setRescheduleTime(cb.preferredAt || "Tomorrow 3:00 PM");
                                  setRescheduleModalOpen(true);
                                }}
                              >
                                <PencilSimple size={13} /> Reschedule
                              </button>
                              <button
                                className="ops-button ops-button-sm"
                                onClick={() => handleCancelCallback(cb)}
                              >
                                <X size={13} /> Cancel
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ASSIGN MODAL */}
      {assignModalOpen && selectedCase && (
        <div className="ops-modal-backdrop" onClick={() => setAssignModalOpen(false)}>
          <div className="ops-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "420px" }}>
            <h3 style={{ margin: "0 0 1rem 0" }}>Assign Case {selectedCase.id}</h3>
            <form onSubmit={handleAssignSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
                  Select Representative:
                </label>
                <select
                  className="ops-select"
                  style={{ width: "100%" }}
                  value={assignedAgent}
                  onChange={(e) => setAssignedAgent(e.target.value)}
                >
                  <option value="AG-001">Priya Sharma · Tier 2 Support</option>
                  <option value="AG-002">Rahul Verma · Account Desk</option>
                  <option value="AG-003">Amit Patel · Dispute Operations</option>
                </select>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
                <button type="button" className="ops-button" onClick={() => setAssignModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="ops-button ops-button-primary" disabled={actionLoading}>
                  Confirm Assignment
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* RESOLVE MODAL */}
      {resolveModalOpen && selectedCase && (
        <div className="ops-modal-backdrop" onClick={() => setResolveModalOpen(false)}>
          <div className="ops-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "460px" }}>
            <h3 style={{ margin: "0 0 1rem 0" }}>Resolve Case {selectedCase.id}</h3>
            <form onSubmit={handleResolveSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
                  Resolution Notes & Audit Summary:
                </label>
                <textarea
                  className="ops-input"
                  style={{ width: "100%", height: "80px" }}
                  value={resolveNotes}
                  onChange={(e) => setResolveNotes(e.target.value)}
                  placeholder="App update guide provided; customer confirmed login restored."
                  required
                />
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
                <button type="button" className="ops-button" onClick={() => setResolveModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="ops-button ops-button-primary" disabled={actionLoading}>
                  Mark Case Resolved
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* RESCHEDULE MODAL */}
      {rescheduleModalOpen && selectedCallback && (
        <div className="ops-modal-backdrop" onClick={() => setRescheduleModalOpen(false)}>
          <div className="ops-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "420px" }}>
            <h3 style={{ margin: "0 0 1rem 0" }}>Reschedule Callback {selectedCallback.id}</h3>
            <form onSubmit={handleRescheduleSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
                  New Local Time Slot (IST):
                </label>
                <input
                  type="text"
                  className="ops-input"
                  style={{ width: "100%" }}
                  value={rescheduleTime}
                  onChange={(e) => setRescheduleTime(e.target.value)}
                  placeholder="Tomorrow 3:00 PM"
                  required
                />
              </div>
              <p style={{ fontSize: "0.8rem", color: "var(--ops-muted)", marginBottom: "1rem" }}>
                Note: Rescheduling invalidates previous calendar locks and publishes an atomic outbox event with version increment.
              </p>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
                <button type="button" className="ops-button" onClick={() => setRescheduleModalOpen(false)}>
                  Cancel
                </button>
                <button type="submit" className="ops-button ops-button-primary" disabled={actionLoading}>
                  Confirm Reschedule
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
