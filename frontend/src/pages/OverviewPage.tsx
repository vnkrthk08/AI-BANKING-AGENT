import { ArrowRight, CheckCircle, Megaphone, Phone, Timer, UserPlus, WarningCircle, Waveform } from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";
import { DailyTrend, DrillChart, HourlyHeatmap, OutcomeDonut } from "../charts/OperationsCharts";
import { KpiCard } from "../components/KpiCard";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { Panel } from "../components/Panel";
import { useDashboard } from "../hooks/DashboardContext";
import { filterCalls, previousPeriodCalls, summarizeCalls } from "../services/selectors";

function delta(current: number, previous: number): number | undefined {
  // No prior-period data means no honest comparison: show "—" instead of an invented 0%.
  return previous ? ((current - previous) / previous) * 100 : undefined;
}

export function OverviewPage() {
  const { snapshot, loading, error, refresh, filters } = useDashboard();
  const navigate = useNavigate();

  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;

  const calls = filterCalls(snapshot.calls, filters);
  const prior = summarizeCalls(previousPeriodCalls(snapshot.calls, filters));
  const current = summarizeCalls(calls);

  const resolvedAi = calls.filter((call) => call.resolutionMode === "AI");
  const resolvedHuman = calls.filter((call) => call.resolutionMode === "HUMAN" && call.disposition === "CLOSED");

  const drill = () => navigate("/call-log");
  const live = snapshot.calls.filter((call) => call.status === "IN_PROGRESS").length;
  const queueDepth = snapshot.callbacks.filter((callback) => callback.status !== "COMPLETED").length;
  const overdueCallbacks = snapshot.callbacks.filter(
    (c) => c.status === "OVERDUE" || (c.status !== "COMPLETED" && new Date(c.slaDueAt).getTime() < Date.now())
  ).length;
  const urgentEscalations = snapshot.escalations.filter(
    (e) => e.status !== "RESOLVED" && (e.priority === "URGENT" || new Date(e.slaDueAt).getTime() < Date.now())
  ).length;
  const available = snapshot.agents.filter((agent) => agent.availability === "AVAILABLE").length;

  return (
    <>
      <PageHeading
        eyebrow="TOWN BANK · EXECUTIVE OPERATIONS"
        title="Operations Intelligence"
        description="Real-time telephony observability, autonomous voice resolution rates, and SLA queue management."
        actions={
          <div style={{ display: "flex", gap: "10px" }}>
            <button className="ops-button ops-button-primary" onClick={() => navigate("/test-console")}>
              <Waveform size={16} /> Launch Voice Assistant
            </button>
            <button className="ops-button ops-button-secondary" onClick={drill}>
              Call log <ArrowRight size={14} />
            </button>
          </div>
        }
      />

      {/* 1. WHAT IS HAPPENING? — Live Telephony Status */}
      <div className="ops-live-strip">
        <span className="ops-live-strip-title">
          <i /> OPERATIONS NOW
        </span>
        <span>
          <Phone size={15} />
          <strong>{live}</strong> sessions active
        </span>
        <span>
          <UserPlus size={15} />
          <strong>{available}</strong> agents available
        </span>
        <span>
          <Timer size={15} />
          <strong>{queueDepth}</strong> open follow-ups
        </span>
        <span className="ops-strip-context">Calling window 09:00–19:00 IST · no Sundays or bank holidays</span>
      </div>

      {/* 2. WHAT NEEDS ATTENTION? & 3. WHAT ACTION SHOULD I TAKE? */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "12px", margin: "14px 0" }}>
        {/* Urgent Attention Alert Box */}
        <div
          style={{
            background: overdueCallbacks > 0 || urgentEscalations > 0 ? "rgba(239, 68, 68, 0.08)" : "rgba(16, 185, 129, 0.06)",
            border: `1px solid ${overdueCallbacks > 0 || urgentEscalations > 0 ? "rgba(239, 68, 68, 0.3)" : "rgba(16, 185, 129, 0.25)"}`,
            borderRadius: "12px",
            padding: "14px 18px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            {overdueCallbacks > 0 || urgentEscalations > 0 ? (
              <WarningCircle size={22} color="#ef4444" weight="fill" />
            ) : (
              <CheckCircle size={22} color="#10b981" weight="fill" />
            )}
            <div>
              <strong style={{ fontSize: "13px", display: "block", color: overdueCallbacks > 0 || urgentEscalations > 0 ? "#b91c1c" : "#047857" }}>
                {overdueCallbacks > 0 || urgentEscalations > 0 ? "ATTENTION REQUIRED" : "ALL QUEUES HEALTHY"}
              </strong>
              <span style={{ fontSize: "12px", color: "#64748b" }}>
                {overdueCallbacks} overdue callbacks · {urgentEscalations} urgent escalations
              </span>
            </div>
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            {overdueCallbacks > 0 && (
              <button className="ops-button ops-button-secondary" style={{ padding: "4px 10px", fontSize: "11px" }} onClick={() => navigate("/callbacks")}>
                View Callbacks
              </button>
            )}
            {urgentEscalations > 0 && (
              <button className="ops-button ops-button-secondary" style={{ padding: "4px 10px", fontSize: "11px" }} onClick={() => navigate("/escalations")}>
                View Cases
              </button>
            )}
          </div>
        </div>

        {/* Quick Action Dispatch Bar */}
        <div
          style={{
            background: "rgba(241, 245, 249, 0.7)",
            border: "1px solid #e2e8f0",
            borderRadius: "12px",
            padding: "14px 18px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "12px",
          }}
        >
          <div>
            <strong style={{ fontSize: "13px", display: "block", color: "#0f172a" }}>RECOMMENDED ACTIONS</strong>
            <span style={{ fontSize: "12px", color: "#64748b" }}>Direct operator workflows</span>
          </div>
          <div style={{ display: "flex", gap: "6px" }}>
            <button className="ops-button ops-button-secondary" style={{ padding: "4px 10px", fontSize: "11px" }} onClick={() => navigate("/campaigns")}>
              <Megaphone size={13} /> Campaigns
            </button>
            <button className="ops-button ops-button-secondary" style={{ padding: "4px 10px", fontSize: "11px" }} onClick={() => navigate("/team")}>
              <UserPlus size={13} /> Roster
            </button>
          </div>
        </div>
      </div>

      <div className="ops-section-label">
        KEY EXECUTIVE METRICS <span>{calls.length.toLocaleString("en-IN")} total calls in view</span>
      </div>

      <div className="ops-kpi-grid ops-kpi-grid-4">
        <KpiCard
          label="Outbound Calls Dialed"
          value={current.callsDialed.toLocaleString("en-IN")}
          delta={delta(current.callsDialed, prior.callsDialed)}
          icon={<Phone size={18} />}
          accent="teal"
        />
        <KpiCard
          label="Answer &amp; Connect Rate"
          value={`${(current.answerRate * 100).toFixed(1)}%`}
          delta={delta(current.answerRate, prior.answerRate)}
          icon={<CheckCircle size={18} />}
          accent="blue"
        />
        <KpiCard
          label="First-Contact Resolution"
          value={current.closed.toLocaleString("en-IN")}
          delta={delta(current.closed, prior.closed)}
          icon={<CheckCircle size={18} />}
          accent="green"
        />
        <KpiCard
          label="Follow-Up Queue"
          value={(current.callbacks + current.escalated).toLocaleString("en-IN")}
          delta={delta(current.callbacks, prior.callbacks)}
          icon={<Timer size={18} />}
          accent="amber"
        />
      </div>

      {calls.length === 0 ? (
        <section
          style={{
            background: "#ffffff",
            border: "1px dashed #cbd5e1",
            borderRadius: "14px",
            padding: "48px 24px",
            textAlign: "center",
            margin: "24px 0",
          }}
        >
          <Waveform size={40} color="#0d9488" style={{ marginBottom: "12px" }} />
          <h3 style={{ fontSize: "17px", fontWeight: 700, margin: "0 0 8px", color: "#0f172a" }}>
            No Telephony Sessions Recorded Yet
          </h3>
          <p style={{ color: "#64748b", maxWidth: "480px", margin: "0 auto 20px", fontSize: "13.5px" }}>
            Outbound call logs and resolution metrics will populate automatically as calls are conducted. Launch the AI Voice Assistant to test real calls, or configure an outreach campaign.
          </p>
          <div style={{ display: "flex", justifyContent: "center", gap: "10px" }}>
            <button className="ops-button ops-button-primary" onClick={() => navigate("/test-console")}>
              <Waveform size={15} /> Launch Voice Assistant
            </button>
            <button className="ops-button ops-button-secondary" onClick={() => navigate("/campaigns")}>
              <Megaphone size={15} /> Create Outbound Campaign
            </button>
          </div>
        </section>
      ) : (
        <>
          <div className="ops-grid ops-grid-2-1">
            <Panel
              title="Daily call volume &amp; closure trend"
              subtitle="Dialed attempts vs. closed interactions · latest 14 days"
              actions={
                <button className="ops-text-button" onClick={drill}>
                  Open call log <ArrowRight size={13} />
                </button>
              }
            >
              <DrillChart onDrill={drill}>
                <DailyTrend calls={calls} />
              </DrillChart>
            </Panel>

            <Panel
              title="Outcomes breakdown"
              subtitle="Completed call disposition mix"
              actions={
                <button className="ops-text-button" onClick={drill}>
                  Details <ArrowRight size={13} />
                </button>
              }
            >
              <DrillChart onDrill={drill}>
                <OutcomeDonut calls={calls} />
              </DrillChart>
              <div className="ops-outcome-legend">
                {[
                  ["Closed", "#27805f"],
                  ["Callback", "#d29132"],
                  ["Escalated", "#b74747"],
                  ["Not interested", "#8793a4"],
                  ["Busy", "#d3b461"],
                  ["No answer / DND", "#aab3c0"],
                ].map(([label, color]) => (
                  <span key={label}>
                    <i style={{ background: color }} />
                    {label}
                  </span>
                ))}
              </div>
            </Panel>
          </div>

          <div className="ops-grid ops-grid-equal">
            <Panel
              title="Autonomous AI vs Human resolution"
              subtitle="Agent Subbu automated completions compared with supervisory transfers"
              actions={
                <button className="ops-text-button" onClick={drill}>
                  Explore calls <ArrowRight size={13} />
                </button>
              }
            >
              <div className="ops-resolution-compare">
                {[
                  { label: "AI Autonomous Closure", rows: resolvedAi, color: "#0d9488" },
                  { label: "Human Specialist Transfer", rows: resolvedHuman, color: "#475569" },
                ].map((group) => (
                  <div key={group.label}>
                    <span>{group.label}</span>
                    <strong>{group.rows.length.toLocaleString("en-IN")}</strong>
                    <small>
                      Avg handling:{" "}
                      {(group.rows.length
                        ? group.rows.reduce((sum, call) => sum + call.durationSec, 0) / group.rows.length / 60
                        : 0
                      ).toFixed(1)}{" "}
                      min
                    </small>
                    <div className="ops-meter">
                      <i
                        style={{
                          width: `${calls.length ? (group.rows.length / calls.length) * 100 : 0}%`,
                          background: group.color,
                        }}
                      />
                    </div>
                    <small>
                      {calls.length ? ((group.rows.length / calls.length) * 100).toFixed(1) : "0.0"}% of total volume
                    </small>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel
              title="Call hour distribution"
              subtitle="IST · Permitted contact window (09:00 - 21:00)"
              actions={
                <button className="ops-text-button" onClick={() => navigate("/insights")}>
                  View heatmap <ArrowRight size={13} />
                </button>
              }
            >
              <DrillChart onDrill={drill}>
                <HourlyHeatmap calls={calls} />
              </DrillChart>
            </Panel>
          </div>

          <section className="ops-summary-panel" style={{ marginTop: "14px" }}>
            <div className="ops-summary-top">
              <span className="ops-ai-mark">AI</span>
              <span>EXECUTIVE INTELLIGENCE BRIEFING</span>
            </div>
            <h2>Campaign Performance &amp; Operational Efficiency</h2>
            <p>
              Outbound outreach achieved a <strong>{(current.answerRate * 100).toFixed(1)}%</strong> connection rate across{" "}
              <strong>{calls.length.toLocaleString("en-IN")}</strong> recorded interactions. Subbu AI voice agent resolved{" "}
              <strong>{resolvedAi.length.toLocaleString("en-IN")}</strong> customer interactions autonomously (
              <strong>{calls.length ? ((resolvedAi.length / calls.length) * 100).toFixed(1) : "0.0"}%</strong> of total volume),
              streamlining frontline operational load. A total of <strong>{current.callbacks.toLocaleString("en-IN")}</strong>{" "}
              callbacks and <strong>{current.escalated.toLocaleString("en-IN")}</strong> edge cases have been prioritized in the SLA queue.
            </p>
            <div style={{ display: "flex", gap: "14px", marginTop: "12px" }}>
              <button className="ops-button ops-button-secondary" onClick={() => navigate("/insights")}>
                Performance insights <ArrowRight size={13} />
              </button>
              <button className="ops-button ops-button-secondary" onClick={() => navigate("/team")}>
                Supervisor team board <ArrowRight size={13} />
              </button>
              <button className="ops-button ops-button-secondary" onClick={() => navigate("/callbacks")}>
                Callbacks queue <ArrowRight size={13} />
              </button>
            </div>
          </section>
        </>
      )}
    </>
  );
}

