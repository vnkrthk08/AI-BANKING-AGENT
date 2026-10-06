import { CalendarBlank, Clock, Phone, UserPlus } from "@phosphor-icons/react";
import { useState } from "react";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { StatusPill } from "../components/StatusPill";
import { dashboardApi } from "../services/dashboardApi";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { formatDateTime, formatIstDateTimeInput, isTodayIst, istDateTimeInputToIso } from "../services/selectors";
import { hasAction } from "../config/permissions";
import type { Callback, CallbackStatus } from "../types";

type CallbackTab = CallbackStatus;
const tabs: Array<{ key: CallbackTab; label: string }> = [{ key: "IMMEDIATE", label: "Immediate" }, { key: "SCHEDULED", label: "Scheduled today" }, { key: "OVERDUE", label: "Overdue" }, { key: "COMPLETED", label: "Completed" }];
function slaLabel(value: string): string { const minutes = Math.ceil((new Date(value).getTime() - Date.now()) / 60_000); return minutes < 0 ? `${Math.abs(minutes)}m overdue` : minutes < 60 ? `${minutes}m left` : `${Math.floor(minutes / 60)}h ${minutes % 60}m left`; }
function matchesTab(item: Callback, tab: CallbackTab): boolean {
  const overdue = new Date(item.slaDueAt).getTime() < Date.now();
  if (tab === "COMPLETED") return item.status === "COMPLETED";
  if (tab === "OVERDUE") return item.status === "OVERDUE" || item.status !== "COMPLETED" && overdue;
  if (tab === "IMMEDIATE") return item.status === "IMMEDIATE" && !overdue;
  return item.status === "SCHEDULED" && !overdue && isTodayIst(item.preferredAt);
}

export function CallbacksPage() {
  const { snapshot, loading, error, refresh } = useDashboard();
  const [role] = useRole();
  const [active, setActive] = useState<CallbackTab>("IMMEDIATE");
  const [notice, setNotice] = useState("");
  const [rescheduleId, setRescheduleId] = useState<string | null>(null);
  const [rescheduleValue, setRescheduleValue] = useState("");
  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  const agentId = "AG-001";
  const canAssign = hasAction(role, "assign-case");
  const visible = snapshot.callbacks.filter((item) => role !== "AGENT" || !item.assignedAgentId || item.assignedAgentId === agentId);
  const filtered = visible.filter((item) => matchesTab(item, active)).sort((a,b)=>({URGENT:0,HIGH:1,NORMAL:2,LOW:3}[a.priority]-{URGENT:0,HIGH:1,NORMAL:2,LOW:3}[b.priority])||new Date(a.slaDueAt).getTime()-new Date(b.slaDueAt).getTime());
  async function update(callback: Callback, patch: Partial<Callback>, message: string) {
    await dashboardApi.updateCallback(callback.id, patch);
    const action = patch.status === "COMPLETED" ? "CALLBACK_COMPLETED" : "preferredAt" in patch ? "CALLBACK_RESCHEDULED" : "assignedAgentId" in patch ? "CALLBACK_ASSIGNED" : "CALLBACK_UPDATED";
    await dashboardApi.recordAudit(action, "CALLBACK", callback.id, role, message);
    await refresh();
    setNotice(message);
  }
  async function saveReschedule(callback: Callback) {
    if (!rescheduleValue) return;
    const scheduledAt = istDateTimeInputToIso(rescheduleValue);
    await update(callback, { status: "SCHEDULED", preferredAt: scheduledAt, slaDueAt: scheduledAt, rescheduledCount: callback.rescheduledCount + 1 }, "Callback rescheduled in the local demo dataset.");
    setRescheduleId(null); setRescheduleValue("");
  }
  return <>
    <PageHeading eyebrow="FOLLOW-UP OPERATIONS" title="Callbacks" description="Work callbacks by urgency, preferred time and SLA status." actions={<span className="ops-mini-label"><CalendarBlank size={15} />All times IST</span>} />
    {notice && <div className="ops-notice-banner" role="status">{notice}<button onClick={() => setNotice("")}>Dismiss</button></div>}
    <div className="ops-callback-summary"><div><small>OPEN FOLLOW-UPS</small><strong>{visible.filter((item) => item.status !== "COMPLETED").length}</strong></div><div><small>OVERDUE</small><strong className="ops-red-text">{visible.filter((item) => item.status === "OVERDUE").length}</strong></div><div><small>RESCHEDULED</small><strong>{visible.reduce((sum, item) => sum + item.rescheduledCount, 0)}</strong></div><div><small>COMPLETED</small><strong>{visible.filter((item) => item.status === "COMPLETED").length}</strong></div><p>Mock queue · actions stay in this browser</p></div>
    <div className="ops-tabs" role="tablist" aria-label="Callback status">{tabs.map((item) => <button key={item.key} role="tab" aria-selected={active === item.key} className={active === item.key ? "active" : ""} onClick={() => setActive(item.key)}>{item.label}<span>{visible.filter((c) => matchesTab(c,item.key)).length}</span></button>)}</div>
    <section className="ops-panel"><header className="ops-panel-head"><div><h2>{tabs.find((item) => item.key === active)?.label} callbacks</h2><p>{active === "OVERDUE" ? "Past-due follow-ups, sorted by SLA urgency." : "Customer preference, case context and next action."}</p></div></header><div className="ops-callback-list">
      {filtered.length === 0 && <div className="ops-empty"><Clock size={22} /><strong>No {active.toLowerCase()} callbacks</strong><span>Try another queue or date filter.</span></div>}
      {filtered.slice(0, 60).map((callback) => <article className="ops-callback-row" key={callback.id}><div className="ops-callback-priority"><StatusPill value={callback.priority} /><span className={callback.status === "OVERDUE" || new Date(callback.slaDueAt).getTime() < Date.now() ? "ops-red-text" : ""}>{slaLabel(callback.slaDueAt)}</span></div><div className="ops-callback-customer"><strong>{callback.customerRef}</strong><span>{callback.maskedPhone} · {callback.preferredLanguage}</span></div><div className="ops-callback-reason"><strong>{callback.reason}</strong><span>{callback.campaignName} · {callback.callId}</span></div><div className="ops-callback-when"><small>{callback.preferredAt ? formatDateTime(callback.preferredAt) + " IST" : "As soon as available"}</small><span>{callback.rescheduledCount} reschedules</span></div><div className="ops-callback-actions">{active !== "COMPLETED" && <><button className="ops-button ops-button-secondary" onClick={() => { setRescheduleId(callback.id); setRescheduleValue(callback.preferredAt ? formatIstDateTimeInput(callback.preferredAt) : ""); }}>Reschedule</button><button className="ops-button ops-button-primary" onClick={() => void update(callback, { status: "COMPLETED" }, "Callback marked complete in the demo queue.")}><Phone size={14} />Complete</button></>}{canAssign && active !== "COMPLETED" && <label className="ops-assign-select"><UserPlus size={14} /><select aria-label={`Assign ${callback.id}`} value={callback.assignedAgentId ?? ""} onChange={(event) => void update(callback, { assignedAgentId: event.target.value || null }, "Callback assignment updated in the demo queue.")}><option value="">Unassigned</option>{snapshot.agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>}</div>
        {rescheduleId === callback.id && <div className="ops-reschedule-form"><label>New preferred date &amp; time (IST)<input type="datetime-local" value={rescheduleValue} onChange={(event) => setRescheduleValue(event.target.value)} /></label><button className="ops-button ops-button-primary" onClick={() => void saveReschedule(callback)}>Save time</button><button className="ops-text-button" onClick={() => setRescheduleId(null)}>Cancel</button></div>}
      </article>)}
    </div></section>
    <p className="ops-table-note"><StatusPill value="SCHEDULED" /> Callback completion and assignment are mock actions; no call is placed by this screen.</p>
  </>;
}

