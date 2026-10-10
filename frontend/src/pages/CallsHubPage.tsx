import { useState } from "react";
import {
  ArrowsClockwise,
  Eye,
  MagnifyingGlass,
  Phone,
  PhoneCall,
  Waveform,
  X,
} from "@phosphor-icons/react";
import { CallDetailDrawer } from "../components/CallDetailDrawer";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { kuralApi } from "../services/kuralApi";

export function CallsHubPage() {
  const [role] = useRole();
  const { snapshot, refresh } = useDashboard();
  const [activeTab, setActiveTab] = useState<"history" | "live" | "journey">("history");
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [dispositionFilter, setDispositionFilter] = useState<string>("ALL");
  const [dialModalOpen, setDialModalOpen] = useState(false);
  const [dialPhone, setDialPhone] = useState("+91 98765 43210");
  const [dialCustomerRef, setDialCustomerRef] = useState("CUST-100");
  const [dialLoading, setDialLoading] = useState(false);
  const [dialResult, setDialResult] = useState<{ success: boolean; message: string } | null>(null);

  const calls = snapshot?.calls ?? [];
  const selectedCall = calls.find((c) => c.id === selectedCallId);

  // Filtered historical calls
  const filteredCalls = calls.filter((c) => {
    const q = searchQuery.toLowerCase().trim();
    const matchesSearch =
      !q ||
      c.id.toLowerCase().includes(q) ||
      c.customerRef.toLowerCase().includes(q) ||
      c.maskedPhone.toLowerCase().includes(q) ||
      c.campaignName.toLowerCase().includes(q);
    const matchesDisp = dispositionFilter === "ALL" || c.disposition === dispositionFilter;
    return matchesSearch && matchesDisp;
  });

  // Live calls in progress
  const liveCalls = calls.filter((c) => c.status === "IN_PROGRESS");

  async function handleDialSubmit(e: React.FormEvent) {
    e.preventDefault();
    setDialLoading(true);
    setDialResult(null);
    try {
      const res = await kuralApi.dialTelephonyCall(dialPhone, dialCustomerRef);
      setDialResult({
        success: true,
        message: `Call ${res.call_id} queued with gateway (${res.provider_call_sid || "Sandbox"}). Status: ${res.status}`,
      });
      refresh();
    } catch (err: unknown) {
      setDialResult({
        success: false,
        message: err instanceof Error ? err.message : "Failed to initiate outbound telephony call",
      });
    } finally {
      setDialLoading(false);
    }
  }

  return (
    <div className="ops-page">
      <div className="ops-page-header">
        <div>
          <h1 className="ops-page-title">Calls Hub</h1>
          <p className="ops-page-subtitle">
            Centralized banking telephony operations: live supervisor bridge, historical audit transcripts & customer journeys.
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <button className="ops-button" onClick={() => refresh()} title="Refresh live telemetry">
            <ArrowsClockwise size={16} /> Refresh
          </button>
          <button className="ops-button ops-button-primary" onClick={() => setDialModalOpen(true)}>
            <PhoneCall size={16} /> Dial Outbound Call
          </button>
        </div>
      </div>

      {/* Hub Tabs */}
      <div className="ops-tabs" style={{ marginBottom: "1.25rem" }}>
        <button
          className={`ops-tab ${activeTab === "history" ? "active" : ""}`}
          onClick={() => setActiveTab("history")}
        >
          Call History ({filteredCalls.length})
        </button>
        <button
          className={`ops-tab ${activeTab === "live" ? "active" : ""}`}
          onClick={() => setActiveTab("live")}
        >
          Live Telephony ({liveCalls.length})
        </button>
        <button
          className={`ops-tab ${activeTab === "journey" ? "active" : ""}`}
          onClick={() => setActiveTab("journey")}
        >
          Customer Journey
        </button>
      </div>

      {/* TAB 1: CALL HISTORY */}
      {activeTab === "history" && (
        <div className="ops-card">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "1rem",
              flexWrap: "wrap",
              gap: "0.75rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flex: 1, maxWidth: "400px" }}>
              <MagnifyingGlass size={18} style={{ color: "var(--ops-muted)" }} />
              <input
                type="text"
                className="ops-input"
                placeholder="Search by Call ID, Customer Ref, Phone..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ width: "100%" }}
              />
            </div>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <label style={{ fontSize: "0.85rem", color: "var(--ops-muted)" }}>Disposition:</label>
              <select
                className="ops-select"
                value={dispositionFilter}
                onChange={(e) => setDispositionFilter(e.target.value)}
              >
                <option value="ALL">All Dispositions</option>
                <option value="COMPLETED">COMPLETED</option>
                <option value="ESCALATED">ESCALATED</option>
                <option value="CALLBACK_SCHEDULED">CALLBACK_SCHEDULED</option>
                <option value="FAILED">FAILED</option>
                <option value="BUSY">BUSY</option>
                <option value="NO_ANSWER">NO_ANSWER</option>
              </select>
            </div>
          </div>

          {filteredCalls.length === 0 ? (
            <div className="ops-empty-state" style={{ padding: "3rem 1rem", textAlign: "center" }}>
              <Waveform size={48} style={{ color: "var(--ops-muted)", marginBottom: "0.75rem" }} />
              <h3 style={{ margin: "0 0 0.5rem 0" }}>No calls found</h3>
              <p style={{ color: "var(--ops-muted)", maxWidth: "400px", margin: "0 auto" }}>
                {searchQuery || dispositionFilter !== "ALL"
                  ? "No calls match your active filter criteria."
                  : "No call records currently stored in database."}
              </p>
            </div>
          ) : (
            <div className="ops-table-wrapper">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Call ID</th>
                    <th>Customer</th>
                    <th>Masked Phone</th>
                    <th>Campaign / Origin</th>
                    <th>Disposition</th>
                    <th>Mode</th>
                    <th>Duration</th>
                    <th>Started At</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCalls.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <strong>{c.id}</strong>
                      </td>
                      <td>{c.customerRef}</td>
                      <td>{c.maskedPhone}</td>
                      <td>{c.campaignName}</td>
                      <td>
                        <StatusPill value={c.disposition ?? undefined} />
                      </td>
                      <td>
                        <span
                          className={`ops-badge ${
                            c.resolutionMode === "AI" ? "ops-badge-teal" : "ops-badge-amber"
                          }`}
                        >
                          {c.resolutionMode}
                        </span>
                      </td>
                      <td>{c.durationSec ? `${c.durationSec}s` : "—"}</td>
                      <td>{new Date(c.startedAt).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })}</td>
                      <td>
                        <button
                          className="ops-button ops-button-sm"
                          onClick={() => setSelectedCallId(c.id)}
                          title="Inspect audio, transcript and compliance telemetry"
                        >
                          <Eye size={14} /> Inspect
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: LIVE CALLS */}
      {activeTab === "live" && (
        <div className="ops-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h3 style={{ margin: 0 }}>Active In-Progress Calls</h3>
            <span className="ops-badge ops-badge-teal">Live Monitoring Active</span>
          </div>
          {liveCalls.length === 0 ? (
            <div className="ops-empty-state" style={{ padding: "3rem 1rem", textAlign: "center" }}>
              <Phone size={48} style={{ color: "var(--ops-muted)", marginBottom: "0.75rem" }} />
              <h3 style={{ margin: "0 0 0.5rem 0" }}>No Active Calls Right Now</h3>
              <p style={{ color: "var(--ops-muted)", maxWidth: "450px", margin: "0 auto" }}>
                There are currently no telephone calls in progress on the active telephony trunks. Dial an outbound call or test in the Voice Studio.
              </p>
            </div>
          ) : (
            <div className="ops-table-wrapper">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Call ID</th>
                    <th>Customer</th>
                    <th>Trunk Provider</th>
                    <th>Assigned Agent</th>
                    <th>State</th>
                    <th>Live Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {liveCalls.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <strong>{c.id}</strong>
                      </td>
                      <td>{c.customerRef}</td>
                      <td>Sandbox Trunk</td>
                      <td>Subbu AI Engine</td>
                      <td>
                        <span className="ops-status-dot green" /> In Progress
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: "0.25rem" }}>
                          <button
                            className="ops-button ops-button-sm"
                            onClick={() => setSelectedCallId(c.id)}
                          >
                            Listen Live
                          </button>
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

      {/* TAB 3: CUSTOMER JOURNEY */}
      {activeTab === "journey" && (
        <div className="ops-card">
          <h3 style={{ margin: "0 0 1rem 0" }}>Customer Interaction Journey Timeline</h3>
          <p style={{ color: "var(--ops-muted)", marginBottom: "1.5rem" }}>
            Select any call from Call History to trace multi-turn touchpoints, callback obligations, and support escalations across sessions.
          </p>
          {calls.slice(0, 5).map((c) => (
            <div
              key={c.id}
              style={{
                display: "flex",
                gap: "1rem",
                padding: "1rem",
                borderLeft: "3px solid var(--ops-teal)",
                background: "var(--ops-card-hover)",
                borderRadius: "0 8px 8px 0",
                marginBottom: "0.75rem",
              }}
            >
              <div style={{ minWidth: "120px" }}>
                <strong>{new Date(c.startedAt).toLocaleTimeString("en-IN")}</strong>
                <div style={{ fontSize: "0.8rem", color: "var(--ops-muted)" }}>
                  {new Date(c.startedAt).toLocaleDateString("en-IN")}
                </div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.25rem" }}>
                  <strong>{c.customerRef}</strong>
                  <StatusPill value={c.disposition ?? undefined} />
                  <span className="ops-badge">{c.campaignName}</span>
                </div>
                <div style={{ fontSize: "0.875rem", color: "var(--ops-text)" }}>
                  {c.summary || "Inbound/outbound conversational turn completed with AI Voice Agent."}
                </div>
              </div>
              <div>
                <button
                  className="ops-button ops-button-sm"
                  onClick={() => setSelectedCallId(c.id)}
                >
                  Inspect
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* INSPECT CALL DRAWER */}
      {selectedCall && (
        <CallDetailDrawer
          call={selectedCall}
          role={role}
          onClose={() => setSelectedCallId(null)}
        />
      )}

      {/* DIAL OUTBOUND CALL MODAL */}
      {dialModalOpen && (
        <div className="ops-modal-backdrop" onClick={() => setDialModalOpen(false)}>
          <div className="ops-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "480px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <h3 style={{ margin: 0, display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <PhoneCall size={20} style={{ color: "var(--ops-teal)" }} /> Dial Outbound Call
              </h3>
              <button
                className="ops-icon-button"
                onClick={() => setDialModalOpen(false)}
                aria-label="Close modal"
              >
                <X size={18} />
              </button>
            </div>
            <form onSubmit={handleDialSubmit}>
              <div style={{ marginBottom: "1rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
                  Destination Phone (+91 Indian Standard):
                </label>
                <input
                  type="text"
                  className="ops-input"
                  style={{ width: "100%" }}
                  value={dialPhone}
                  onChange={(e) => setDialPhone(e.target.value)}
                  placeholder="+91 98765 43210"
                  required
                />
              </div>
              <div style={{ marginBottom: "1.25rem" }}>
                <label style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.25rem" }}>
                  Customer Reference Identifier:
                </label>
                <input
                  type="text"
                  className="ops-input"
                  style={{ width: "100%" }}
                  value={dialCustomerRef}
                  onChange={(e) => setDialCustomerRef(e.target.value)}
                  placeholder="CUST-100"
                  required
                />
              </div>

              {dialResult && (
                <div
                  style={{
                    padding: "0.75rem",
                    borderRadius: "6px",
                    marginBottom: "1rem",
                    fontSize: "0.85rem",
                    background: dialResult.success ? "rgba(16, 185, 129, 0.1)" : "rgba(239, 68, 68, 0.1)",
                    color: dialResult.success ? "#10b981" : "#ef4444",
                    border: `1px solid ${dialResult.success ? "#10b981" : "#ef4444"}`,
                  }}
                >
                  {dialResult.message}
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
                <button
                  type="button"
                  className="ops-button"
                  onClick={() => setDialModalOpen(false)}
                  disabled={dialLoading}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="ops-button ops-button-primary"
                  disabled={dialLoading}
                >
                  {dialLoading ? "Dialing..." : "Initiate Outbound Call"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
