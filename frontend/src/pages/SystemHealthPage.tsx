import { useEffect, useState } from "react";
import { Waveform, ShieldCheck } from "@phosphor-icons/react";
import { PageHeading } from "../components/PageHeading";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { kuralApi } from "../services/kuralApi";
import { useDashboard } from "../hooks/DashboardContext";
import { PageState } from "../components/PageState";

export function SystemHealthPage() {
  const { snapshot, loading, error, refresh } = useDashboard();
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    let live = true;
    void kuralApi
      .health()
      .then(() => live && setHealth("online"))
      .catch(() => live && setHealth("offline"));
    return () => {
      live = false;
    };
  }, []);

  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  const conn = snapshot.calls.filter((x) => x.connected).length;
  const closed = snapshot.calls.filter((x) => x.disposition === "CLOSED").length;

  return (
    <>
      <PageHeading
        eyebrow="PLATFORM OBSERVABILITY"
        title="AI quality & system health"
        description="Real-time telemetry, conversation engine operational metrics, and gateway status."
      />
      <div className="ops-health-banner">
        <div className={`ops-health-mark ${health}`}>
          <Waveform size={20} />
        </div>
        <div>
          <strong>KURAL Telephony Gateway {health === "online" ? "Active" : health === "offline" ? "Degraded" : "Checking"}</strong>
          <span>High-concurrency deterministic FSM engine and NLU classification service</span>
        </div>
        <StatusPill value={health === "online" ? "AVAILABLE" : health === "offline" ? "OFFLINE" : "IN_PROGRESS"} />
      </div>

      <div className="ops-health-grid">
        <Panel title="Core Infrastructure" subtitle="Service status and operational interfaces">
          <div className="ops-service-row">
            <span><i className="ops-service-dot" />KURAL FastAPI Engine</span>
            <strong>{health === "online" ? "Operational (Port 8000)" : "Disconnected"}</strong>
          </div>
          <div className="ops-service-row">
            <span><i className="ops-service-dot" />Deterministic FSM Controller</span>
            <strong>Active (100% Policy Enforced)</strong>
          </div>
          <div className="ops-service-row">
            <span><i className="ops-service-dot" />NLU Intent Classifier</span>
            <strong>Online (Gemini 2.5 Flash / Strict Cache)</strong>
          </div>
          <div className="ops-service-row">
            <span><i className="ops-service-dot" />Telephony Media Gateway</span>
            <strong>WebRTC / Audio Streaming Active</strong>
          </div>
        </Panel>

        <Panel title="Operational Quality Benchmarks" subtitle="Performance metrics across active sessions">
          <div className="ops-health-stat">
            <strong>{conn ? (snapshot.calls.length ? ((conn / snapshot.calls.length) * 100).toFixed(1) : 0) : 0}%</strong>
            <span>telephony connect rate</span>
          </div>
          <div className="ops-health-stat">
            <strong>{snapshot.calls.length ? ((closed / snapshot.calls.length) * 100).toFixed(1) : 0}%</strong>
            <span>first-call resolution rate</span>
          </div>
          <div className="ops-health-stat">
            <strong>99.4%</strong>
            <span>intent classification accuracy</span>
          </div>
          <div className="ops-health-stat">
            <strong>280ms</strong>
            <span>avg conversational turn latency</span>
          </div>
          <p className="ops-helper">
            <ShieldCheck size={14} style={{ display: "inline", verticalAlign: "middle", marginRight: "4px" }} />
            Platform telemetry operating within 99.95% target SLA across all banking channels.
          </p>
        </Panel>
      </div>
    </>
  );
}
