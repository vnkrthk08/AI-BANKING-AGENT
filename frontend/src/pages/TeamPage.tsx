import { CheckCircle, Clock, Headset, Phone, UsersThree } from "@phosphor-icons/react";
import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { DataTable } from "../components/DataTable";
import { KpiCard } from "../components/KpiCard";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { dashboardApi } from "../services/dashboardApi";
import { formatDateTime } from "../services/selectors";
import { useDashboard } from "../hooks/DashboardContext";
import type { EscalationCase } from "../types";

const helper = createColumnHelper<EscalationCase>();
const columns = [
  helper.accessor("id", { header: "CASE", cell: (info) => <span className="ops-mono">{info.getValue()}</span> }),
  helper.accessor("customerRef", { header: "CUSTOMER REF" }),
  helper.accessor("category", { header: "ISSUE" }),
  helper.accessor("priority", { header: "PRIORITY", cell: (info) => <StatusPill value={info.getValue()} /> }),
  helper.accessor("assignedAgentId", { header: "ASSIGNED", cell: (info) => info.getValue() ?? <span className="ops-unassigned">Unassigned</span> }),
  helper.accessor("slaDueAt", { header: "SLA DUE · IST", cell: (info) => <span className="ops-mono">{formatDateTime(info.getValue())}</span> }),
];
export function TeamPage() {
  const navigate = useNavigate();
  const { snapshot, loading, error, refresh } = useDashboard();
  const [notice, setNotice] = useState("");
  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  const active = snapshot.escalations.filter((item) => item.status !== "RESOLVED");
  const available = snapshot.agents.filter((agent) => agent.availability === "AVAILABLE");
  const onCall = snapshot.agents.filter((agent) => agent.availability === "ON_CALL");
  const liveCalls = snapshot.calls.filter((call) => call.status === "IN_PROGRESS");
  const atRisk = active.filter((item) => new Date(item.slaDueAt).getTime() < Date.now() + 60 * 60_000).slice(0, 8);
  async function handleSupervisorCommand(callId: string, action: string) {
    await dashboardApi.recordAudit(action, "CALL", callId, "SUPERVISOR", `Supervisor command: ${action}`);
    setNotice(`Supervisor command "${action === "BARGE_IN" ? "Barge-in" : "Take over"}" dispatched for session ${callId}.`);
  }
  return <>
    <PageHeading eyebrow="SUPERVISOR WORKSPACE" title="Team board" description="Live call pressure, agent availability and the cases closest to breaching SLA." actions={<span className="ops-refresh-label"><i />Live Telephony Feed</span>} />
    <div className="ops-kpi-grid ops-kpi-grid-4"><KpiCard label="Live calls" value={liveCalls.length.toString()} icon={<Phone size={17} />} /><KpiCard label="Queue depth" value={active.length.toLocaleString("en-IN")} icon={<Clock size={17} />} accent="amber" /><KpiCard label="Agents available" value={available.length.toString()} icon={<UsersThree size={17} />} accent="green" /><KpiCard label="SLA at risk" value={atRisk.length.toString()} icon={<CheckCircle size={17} />} accent="red" /></div>
    {notice && <div className="ops-notice-banner" role="status">{notice}<button onClick={() => setNotice("")}>Dismiss</button></div>}
    <div className="ops-grid ops-grid-2-1">
      <Panel title="SLA at risk" subtitle="Open cases due within the next hour" actions={<button className="ops-text-button" onClick={() => navigate("/escalations")}>Reassign in queue <span>{atRisk.length} at risk</span></button>}><DataTable data={atRisk} columns={columns} rowId={(item) => item.id} pageSize={8} emptyTitle="No cases nearing SLA" emptyText="The team has no immediate deadline pressure." /></Panel>
      <Panel title="Agent availability" subtitle={`${snapshot.agents.length} active agents on roster`}>
        <div className="ops-agent-capacity"><div><strong>{available.length}</strong><span>Available</span></div><div><strong>{onCall.length}</strong><span>On a call</span></div><div><strong>{snapshot.agents.filter((agent) => agent.availability === "BREAK").length}</strong><span>On break</span></div></div>
        <div className="ops-agent-list">{snapshot.agents.slice(0, 8).map((agent) => <div key={agent.id} className="ops-agent-row"><span className="ops-person-avatar">{agent.name.split(" ").map((part) => part[0]).join("")}</span><span><strong>{agent.name}</strong><small>{agent.team} · {agent.languages.join(", ")}</small></span><StatusPill value={agent.availability} /></div>)}</div>
      </Panel>
    </div>
    <Panel title="Live calls" subtitle="Active concurrent calls with supervisor intervention controls" actions={<span className="ops-mini-label">{liveCalls.length} active</span>}>
      <div className="ops-live-call-grid">{liveCalls.slice(0, 8).map((call) => <article className="ops-live-call-card" key={call.id}><div className="ops-live-call-top"><StatusPill value="IN_PROGRESS" /><span className="ops-mono">{call.id}</span></div><strong>{call.customerRef} <small>{call.maskedPhone}</small></strong><span>{call.campaignName} · {call.language}</span><div className="ops-live-call-state">{call.kuralState.replaceAll("_", " ")} · {call.intent.replaceAll("_", " ")}</div><div className="ops-button-row"><button className="ops-button ops-button-secondary" onClick={() => void handleSupervisorCommand(call.id, "BARGE_IN")}><Headset size={14} />Barge in</button><button className="ops-button ops-button-secondary" onClick={() => void handleSupervisorCommand(call.id, "TAKE_OVER")}>Take over</button></div></article>)}</div>
    </Panel>
  </>;
}
