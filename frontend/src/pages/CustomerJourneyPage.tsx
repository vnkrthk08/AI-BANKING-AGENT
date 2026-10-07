import { ClockCounterClockwise, Phone, ShieldCheck, UserCircle } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { CallDetailDrawer } from "../components/CallDetailDrawer";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { formatDateTime } from "../services/selectors";
import type { CallRecord } from "../types";

export function CustomerJourneyPage() {
  const { snapshot, loading, error, refresh } = useDashboard();
  const [role] = useRole();
  const [customerRef, setCustomerRef] = useState("");
  const [selected, setSelected] = useState<CallRecord | null>(null);
  const frequent = useMemo(() => {
    if (!snapshot) return "";
    const counts = new Map<string, number>(); snapshot.calls.forEach((call) => counts.set(call.customerRef, (counts.get(call.customerRef) ?? 0) + 1));
    return [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
  }, [snapshot]);
  const currentRef = customerRef || frequent;
  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  const journey = snapshot.calls.filter((call) => call.customerRef === currentRef).sort((a, b) => new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime());
  const latest = journey.at(-1);
  return <>
    <PageHeading eyebrow="CUSTOMER TELEPHONY TIMELINE" title="Customer journey" description="Complete chronological interaction history, call attempts, and scheduled follow-ups." />
    <section className="ops-customer-banner"><span className="ops-customer-icon"><UserCircle size={24} /></span><div><small>CUSTOMER REFERENCE</small><strong>{currentRef}</strong><span>{latest?.maskedPhone ?? "Masked number unavailable"}</span></div><div className="ops-customer-banner-stat"><strong>{journey.length}</strong><span>call attempts</span></div><div className="ops-customer-banner-stat"><strong>{journey.filter((call) => call.connected).length}</strong><span>connected</span></div><div className="ops-customer-privacy"><ShieldCheck size={17} />RBI Masking Enforced</div><label className="ops-journey-select"><span>Select Customer</span><select value={currentRef} onChange={(event) => setCustomerRef(event.target.value)}>{[...new Set(snapshot.calls.map((call) => call.customerRef))].sort().map((ref) => <option key={ref}>{ref}</option>)}</select></label></section>
    <div className="ops-grid ops-grid-2-1"><Panel title="Journey timeline" subtitle="All attempts · timestamps in Indian Standard Time" actions={<span className="ops-mini-label"><ClockCounterClockwise size={14} />{journey.length} attempts</span>}>
      {!journey.length ? <div className="ops-empty"><strong>No attempts</strong><span>No call records found for this customer identifier.</span></div> : <div className="ops-journey-timeline">{journey.map((call, index) => <article key={call.id} className="ops-journey-item"><span className="ops-journey-rail"><i className={index === journey.length - 1 ? "latest" : ""} /></span><div className="ops-journey-event"><div className="ops-journey-event-head"><span className="ops-mono">{formatDateTime(call.startedAt)} IST</span><StatusPill value={call.disposition ?? call.status} /></div><button className="ops-journey-call" onClick={() => setSelected(call)}>{call.id} <span>View detail →</span></button><p>{call.summary}</p><div className="ops-journey-tags"><span>{call.campaignName}</span><span>{call.language}</span><span>{call.durationSec ? `${Math.floor(call.durationSec / 60)}m ${call.durationSec % 60}s` : "—"}</span>{call.callbackId && <span>Callback {call.callbackId}</span>}{call.escalationId && <span>Case {call.escalationId}</span>}</div></div></article>)}</div>}
    </Panel><Panel title="Journey summary" subtitle="Consolidated customer metrics"><div className="ops-journey-summary"><div><span>First attempt</span><strong>{journey[0] ? formatDateTime(journey[0].startedAt) : "—"}</strong></div><div><span>Latest outcome</span><strong><StatusPill value={latest?.disposition ?? "—"} /></strong></div><div><span>App status</span><strong>{latest?.appInstalled ? latest.appUpdated ? "Updated" : "Update due" : "Not installed"}</strong></div><div><span>Open follow-ups</span><strong>{snapshot.callbacks.filter((item) => item.customerRef === currentRef && item.status !== "COMPLETED").length}</strong></div></div><p className="ops-helper">Customer identifiers and telephony contacts are securely masked under RBI compliance rules. Transcripts and operational events are logged for supervisor audits.</p><div className="ops-journey-links"><Phone size={15} /><span>Direct manual dialing restricted to supervisor tier.</span></div></Panel></div>
    {selected && <CallDetailDrawer call={selected} role={role} onClose={() => setSelected(null)} />}
  </>;
}
