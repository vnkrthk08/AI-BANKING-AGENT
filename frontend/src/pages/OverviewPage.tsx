import { ArrowRight, CheckCircle, Phone, Timer, Waveform } from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";
import { DailyTrend, DrillChart, HourlyHeatmap, OutcomeDonut } from "../charts/OperationsCharts";
import { KpiCard } from "../components/KpiCard";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { Panel } from "../components/Panel";
import { useDashboard } from "../hooks/DashboardContext";
import { filterCalls, previousPeriodCalls, summarizeCalls } from "../services/selectors";

function delta(current: number, previous: number): number {
  return previous ? ((current - previous) / previous) * 100 : 0;
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
  const available = snapshot.agents.filter((agent) => agent.availability === "AVAILABLE").length;

  return (
    <>
      <PageHeading
        eyebrow="TOWN BANK · EXECUTIVE OPERATIONS"
        title="Operations intelligence"
        description="Real-time telephony observability, autonomous voice resolution rates, and fleet capacity."
        actions={
          <div style={{ display: "flex", gap: "10px" }}>
            <button className="ops-button ops-button-primary" onClick={() => navigate("/test-console")}>
              <Waveform size={16} /> Launch Voice Studio
            </button>
            <button className="ops-button ops-button-secondary" onClick={drill}>
              Call log <ArrowRight size={14} />
            </button>
          </div>
        }
      />

      <div className="ops-live-strip">
        <span className="ops-live-strip-title">
          <i /> LIVE TELEPHONY
        </span>
        <span>
          <Phone size={15} />
          <strong>{live}</strong> sessions active
        </span>
        <span>
          <strong>{available}</strong> agents available
        </span>
        <span>
          <Timer size={15} />
          <strong>{queueDepth}</strong> open follow-ups
        </span>
        <span className="ops-strip-context">Contact Window: 09:00–20:00 IST · Trai Compliant</span>
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
          Outbound Mobile App v2.4 upgrade campaign achieved a <strong>{(current.answerRate * 100).toFixed(1)}%</strong>{" "}
          connection rate. Subbu AI voice agent resolved <strong>{current.closed.toLocaleString("en-IN")}</strong>{" "}
          customer interactions autonomously without agent intervention, reducing frontline operational pressure by{" "}
          <strong>68%</strong>. A total of <strong>{current.callbacks.toLocaleString("en-IN")}</strong> callbacks and{" "}
          <strong>{current.escalated.toLocaleString("en-IN")}</strong> edge cases have been prioritized in the SLA queue.
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
  );
}
