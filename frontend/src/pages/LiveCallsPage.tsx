import { Headset, Phone, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { createColumnHelper } from "@tanstack/react-table";
import { useState } from "react";
import { DataTable } from "../components/DataTable";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { StatusPill } from "../components/StatusPill";
import { CallDetailDrawer } from "../components/CallDetailDrawer";
import { dashboardApi } from "../services/dashboardApi";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { filterCalls, formatDateTime } from "../services/selectors";
import type { CallRecord, Role } from "../types";

const helper = createColumnHelper<CallRecord>();
const columns = [
  helper.accessor("id", { header: "CALL ID", cell: (info) => <span className="ops-mono">{info.getValue()}</span> }),
  helper.accessor("maskedPhone", { header: "MASKED CUSTOMER", cell: (info) => <span>{info.row.original.customerRef}<small className="ops-cell-sub">{info.getValue()}</small></span> }),
  helper.accessor("campaignName", { header: "CAMPAIGN" }), helper.accessor("durationSec", { header: "DURATION", cell: (info) => `${Math.floor(info.getValue() / 60)}m ${info.getValue() % 60}s` }),
  helper.accessor("kuralState", { header: "KURAL STATE", cell: (info) => info.getValue().replaceAll("_", " ") }), helper.accessor("intent", { header: "INTENT", cell: (info) => info.getValue().replaceAll("_", " ") }),
  helper.accessor("policy", { header: "POLICY", cell: (info) => <StatusPill value={info.getValue()} /> }),
];

export function LiveCallsPage() {
  const { snapshot, loading, error, refresh, filters } = useDashboard();
  const [role] = useRole();
  const [selected, setSelected] = useState<CallRecord | null>(null);
  const [notice, setNotice] = useState("");
  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  const liveCalls = filterCalls(snapshot.calls.filter((call) => call.status === "IN_PROGRESS"), filters);
  async function action(call: CallRecord, actionName: string) {
    await dashboardApi.recordAudit(actionName, "CALL", call.id, role, `Supervisor command: ${actionName.replaceAll("_", " ")} executed`);
    setNotice(`Supervisor command "${actionName.replaceAll("_", " ")}" dispatched for call ${call.id}.`);
  }
  return <>
    <PageHeading eyebrow="SUPERVISOR OPERATIONS" title="Live calls" description="Real-time telephony session monitoring, sentiment tracking, and supervisor intervention controls." actions={<span className="ops-live-chip"><i />{liveCalls.length} active now</span>} />
    <div className="ops-call-disclaimer"><ShieldCheck size={16} /><span>Live monitoring active · Telephony audio and FSM transition telemetry secured under banking audit controls.</span></div>
    {notice && <div className="ops-notice-banner" role="status">{notice}<button onClick={() => setNotice("")}>Dismiss</button></div>}
    <section className="ops-panel"><header className="ops-panel-head"><div><h2>Calls in progress</h2><p>Current intent, sentiment, KURAL state and policy decision</p></div><span className="ops-mini-label"><Phone size={14} /> IST</span></header><div className="ops-panel-body"><DataTable data={liveCalls} columns={columns} rowId={(call) => call.id} onRowClick={setSelected} emptyTitle="No live calls" emptyText="Active telephony sessions will appear here in real time." /></div></section>
    <section className="ops-live-card-grid">{liveCalls.slice(0, 6).map((call) => <article className="ops-live-detail-card" key={call.id}><div className="ops-live-card-head"><StatusPill value="IN_PROGRESS" /><time>{formatDateTime(call.startedAt)} IST</time></div><strong>{call.customerRef}</strong><span>{call.maskedPhone} · {call.campaignName}</span><div className="ops-live-state-line">{call.kuralState.replaceAll("_", " ")} <span>·</span> {call.intent.replaceAll("_", " ")}</div><div className="ops-live-sentiment">Sentiment <strong>{call.sentiment >= 0 ? "+" : ""}{call.sentiment.toFixed(2)}</strong><StatusPill value={call.policy} /></div><div className="ops-button-row"><button className="ops-button ops-button-secondary" onClick={() => setSelected(call)}>Open detail</button><button className="ops-button ops-button-secondary" onClick={() => void action(call, "BARGE_IN")}><Headset size={14} />Barge in</button><button className="ops-button ops-button-danger" onClick={() => void action(call, "ESCALATE_NOW")}><WarningCircle size={14} />Escalate now</button></div></article>)}</section>
    {selected && <CallDetailDrawer call={selected} role={role as Role} onClose={() => setSelected(null)} />}
  </>;
}
