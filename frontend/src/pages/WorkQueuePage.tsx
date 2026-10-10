import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CalendarCheck, Tray } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../auth/AuthContext";
import { apiJson } from "../services/http";
import { Badge, Drawer, Empty, ErrorNote, Kpi, Loading, Modal, PageHead, Panel, Tabs, fmtDateTime, fmtRelative, titleCase } from "../components/ui";

interface CaseRow { id: string; priority: string; status: string; category: string; case_type: string; customer_ref: string; customer_name: string | null; masked_phone: string; summary: string; assigned_team: string; assigned_agent_id: string | null; assigned_agent_name: string | null; sla_due_at: string | null; sla_breached: boolean; created_at: string; callback_id: string | null; resolution_notes: string | null; source: string; history?: { event_id: string; event_type: string; from_value: string | null; to_value: string | null; note: string | null; actor: string; created_at: string }[] }
interface CallbackRow { id: string; customer_ref: string; customer_name: string | null; maskedPhone: string; status: string; raw_status: string; scheduled_at_utc: string | null; relative_label: string; reason: string; case_id: string | null; priority: string | null; assigned_agent_name: string | null; attempt_count: number; last_outcome: string | null; outcome_notes: string | null; version: number; moved_label: string | null; history: { event_id: string; event_type: string; actor: string; old_value: string | null; new_value: string | null; created_at: string }[] }
interface Agent { id: string; name: string; availability: string; openCases: number; maxOpenCases: number; skills: string[] }

const OPEN = ["NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CUSTOMER"];
const PRIORITY_RANK: Record<string, number> = { urgent: 0, high: 1, normal: 2, low: 3 };

function useAction(onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr(null);
    try { await fn(); onDone(); } catch (e) { setErr(e instanceof Error ? e.message : "Action failed"); } finally { setBusy(false); }
  };
  return { busy, err, run, setErr };
}

function CaseDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { can, user } = useAuth();
  const { data: c, reload } = useApi<CaseRow>(`/api/escalations/${id}`, [id]);
  const agents = useApi<{ agents: Agent[] }>(can("case:assign") ? "/api/agents" : null);
  const { busy, err, run } = useAction(() => { void reload(); onChanged(); });
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolution, setResolution] = useState("");
  const patch = (body: object) => apiJson(`/api/escalations/${id}`, { method: "PATCH", body: JSON.stringify(body) });
  if (!c) return <Drawer title="Case" onClose={onClose}><Loading /></Drawer>;
  const open = OPEN.includes(c.status);
  const mine = user?.agent_id && c.assigned_agent_id === user.agent_id;
  return (
    <Drawer title={`${titleCase(c.category)}`} sub={`${c.id} · ${c.customer_name ?? c.customer_ref} ${c.masked_phone ? `· ${c.masked_phone}` : ""}`} onClose={onClose}
      footer={open && can("case:work") && <>
        {c.status !== "IN_PROGRESS" && <button className="btn" disabled={busy} onClick={() => run(() => patch({ status: "IN_PROGRESS" }))}>Start work</button>}
        <button className="btn primary" disabled={busy} onClick={() => setResolving(true)}>Resolve case</button></>}>
      {err && <ErrorNote error={err} />}
      <div className="actions"><Badge value={c.priority?.toUpperCase()} /><Badge value={c.status} /><span className={`badge ${c.sla_breached ? "bad" : "plain"}`}>SLA {fmtRelative(c.sla_due_at)}</span></div>
      <dl className="kv">
        <dt>Summary</dt><dd>{c.summary || "—"}</dd>
        <dt>Team</dt><dd>{titleCase(c.assigned_team)}</dd>
        <dt>Owner</dt><dd>{c.assigned_agent_name ?? "Unassigned"}{mine ? " (you)" : ""}</dd>
        <dt>SLA due</dt><dd className="num">{fmtDateTime(c.sla_due_at)}</dd>
        <dt>Raised</dt><dd className="num">{fmtDateTime(c.created_at)} · {c.source === "VOICE_AI" ? "by Subbu" : "by staff"}</dd>
        <dt>Callback</dt><dd>{c.callback_id ?? "—"}</dd>
        {c.resolution_notes && <><dt>Resolution</dt><dd>{c.resolution_notes}</dd></>}
      </dl>
      {open && can("case:assign") && (
        <section><h3 className="section-title">Ownership</h3>
          <div className="actions">
            <select className="select" aria-label="Assign to agent" value={c.assigned_agent_id ?? ""} disabled={busy} onChange={(e) => e.target.value && run(() => patch({ assigned_agent_id: e.target.value }))}>
              <option value="">{c.assigned_agent_id ? "Reassign to…" : "Assign to…"}</option>
              {agents.data?.agents.filter((a) => a.availability !== "OFFLINE").map((a) => <option key={a.id} value={a.id}>{a.name} · {titleCase(a.availability)} · {a.openCases}/{a.maxOpenCases}</option>)}
            </select>
            <button className="btn" disabled={busy} onClick={() => run(() => apiJson("/api/agents/assign", { method: "POST", body: JSON.stringify({ category: c.category }) }).then((r) => patch({ assigned_agent_id: (r as { assigned_agent: Agent }).assigned_agent.id })))}>Auto-assign</button>
          </div>
        </section>
      )}
      {open && can("case:work") && (
        <section><h3 className="section-title">Add note</h3>
          <textarea className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Visible to the team. Do not record OTPs, PINs or card numbers." />
          <div style={{ marginTop: 8 }}><button className="btn" disabled={busy || !note.trim()} onClick={() => run(() => patch({ note }).then(() => setNote("")))}>Save note</button></div>
        </section>
      )}
      <section><h3 className="section-title">History</h3>
        <div className="timeline">{(c.history ?? []).map((h) => (
          <div className="tl" key={h.event_id}><div><b>{titleCase(h.event_type)}</b>{h.to_value ? ` → ${h.to_value}` : ""}{h.note && <div>{h.note}</div>}<small>{h.actor} · {fmtDateTime(h.created_at)}</small></div></div>
        ))}</div>
      </section>
      {resolving && <Modal title="Resolve case" onClose={() => setResolving(false)} footer={<><button className="btn" onClick={() => setResolving(false)}>Cancel</button><button className="btn primary" disabled={busy || !resolution.trim()} onClick={() => run(() => patch({ status: "RESOLVED", resolution_notes: resolution }).then(() => setResolving(false)))}>Resolve</button></>}>
        <label className="field">Resolution notes<textarea className="input" value={resolution} onChange={(e) => setResolution(e.target.value)} /><small>Required. Recorded in the case history and audit trail.</small></label>
      </Modal>}
    </Drawer>
  );
}

function CallbackDrawer({ cb, onClose, onChanged }: { cb: CallbackRow; onClose: () => void; onChanged: () => void }) {
  const { can } = useAuth();
  const { busy, err, run } = useAction(onChanged);
  const [when, setWhen] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const active = ["REQUESTED", "SCHEDULED", "DUE"].includes(cb.raw_status);
  return (
    <Drawer title={cb.customer_name ?? cb.customer_ref} sub={`${cb.id} · ${cb.maskedPhone}`} onClose={onClose}
      footer={active && can("callback:manage") && <button className="btn danger" disabled={busy} onClick={() => setConfirmCancel(true)}>Cancel callback</button>}>
      {err && <ErrorNote error={err} />}
      <div className="actions"><Badge value={cb.status} />{cb.priority && <Badge value={cb.priority.toUpperCase()} />}</div>
      <dl className="kv">
        <dt>Scheduled</dt><dd>{cb.scheduled_at_utc ? `${fmtDateTime(cb.scheduled_at_utc)} (${fmtRelative(cb.scheduled_at_utc)})` : "Time not agreed yet"}</dd>
        <dt>Reason</dt><dd>{titleCase(cb.reason)}</dd>
        <dt>Linked case</dt><dd>{cb.case_id ?? "—"}</dd>
        <dt>Owner</dt><dd>{cb.assigned_agent_name ?? "Unassigned"}</dd>
        <dt>Attempts</dt><dd>{cb.attempt_count}{cb.last_outcome ? ` · last: ${titleCase(cb.last_outcome)}` : ""}</dd>
        {cb.outcome_notes && <><dt>Note</dt><dd>{cb.outcome_notes}</dd></>}
      </dl>
      {active && can("callback:manage") && (
        <section><h3 className="section-title">{cb.scheduled_at_utc ? "Reschedule" : "Agree a time"}</h3>
          <div className="actions"><input type="datetime-local" className="input" value={when} onChange={(e) => setWhen(e.target.value)} aria-label="New callback time" />
            <button className="btn primary" disabled={busy || !when} onClick={() => run(() => apiJson(`/api/callbacks/${cb.id}/reschedule`, { method: "POST", body: JSON.stringify({ preferredAt: new Date(when).toISOString() }) }))}>Save time</button></div>
          <p className="small muted">Calling window 09:00–19:00 IST, no Sundays or bank holidays. The previous time is invalidated.</p>
        </section>
      )}
      <section><h3 className="section-title">History</h3>
        <div className="timeline">{cb.history.map((h) => <div className="tl" key={h.event_id}><div><b>{titleCase(h.event_type)}</b>{h.new_value ? ` → ${h.new_value}` : ""}<small>{h.actor} · {fmtDateTime(h.created_at)}</small></div></div>)}</div>
      </section>
      {confirmCancel && <Modal title="Cancel this callback?" onClose={() => setConfirmCancel(false)} footer={<><button className="btn" onClick={() => setConfirmCancel(false)}>Keep</button><button className="btn danger solid" disabled={busy} onClick={() => run(() => apiJson(`/api/callbacks/${cb.id}/cancel`, { method: "POST", body: "{}" })).then(() => setConfirmCancel(false))}>Cancel callback</button></>}>
        <p style={{ margin: 0 }}>The customer will not be called. This is recorded in the callback history.</p>
      </Modal>}
    </Drawer>
  );
}

export function WorkQueuePage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "cases" | "callbacks") || "cases";
  const [scope, setScope] = useState<"all" | "mine" | "unassigned">(user?.role === "AGENT" ? "mine" : "all");
  const [showClosed, setShowClosed] = useState(false);
  const cases = useApi<CaseRow[]>("/api/escalations");
  const callbacks = useApi<CallbackRow[]>("/api/callbacks");
  const [cbOpen, setCbOpen] = useState<CallbackRow | null>(null);
  const caseId = params.get("case");
  const all = cases.data ?? [];
  const openCases = all.filter((c) => OPEN.includes(c.status));
  const caseRows = (showClosed ? all : openCases)
    .filter((c) => scope === "all" || (scope === "mine" ? c.assigned_agent_id === user?.agent_id : !c.assigned_agent_id))
    .sort((a, b) => Number(b.sla_breached) - Number(a.sla_breached) || (PRIORITY_RANK[a.priority?.toLowerCase()] ?? 9) - (PRIORITY_RANK[b.priority?.toLowerCase()] ?? 9) || (a.sla_due_at ?? "").localeCompare(b.sla_due_at ?? ""));
  const cbs = (callbacks.data ?? []).filter((c) => showClosed || ["REQUESTED", "SCHEDULED", "DUE", "DIALING", "OVERDUE"].includes(c.status));
  const refresh = () => { void cases.reload(); void callbacks.reload(); };
  return (
    <>
      <PageHead title="Work Queue" sub="Escalated cases and customer callbacks waiting on people, ordered by SLA risk." />
      <div className="kpis">
        <Kpi label="Open cases" value={openCases.length} />
        <Kpi label="Unassigned" value={openCases.filter((c) => !c.assigned_agent_id).length} tone={openCases.some((c) => !c.assigned_agent_id) ? "warn" : undefined} />
        <Kpi label="Past SLA" value={openCases.filter((c) => c.sla_breached).length} tone={openCases.some((c) => c.sla_breached) ? "alert" : undefined} />
        <Kpi label="Callbacks due" value={(callbacks.data ?? []).filter((c) => c.status === "DUE" || c.status === "OVERDUE").length} />
        <Kpi label="Need a time" value={(callbacks.data ?? []).filter((c) => c.status === "REQUESTED").length} />
      </div>
      <Tabs value={tab} onChange={(t) => setParams({ tab: t })} items={[{ key: "cases", label: "Cases", count: openCases.length }, { key: "callbacks", label: "Callbacks", count: cbs.length }]} />
      <Panel flush>
        <div className="toolbar">
          {tab === "cases" && <div className="seg" role="group" aria-label="Scope">{(["all", "mine", "unassigned"] as const).map((s) => <button key={s} className={scope === s ? "on" : ""} onClick={() => setScope(s)} disabled={s === "mine" && !user?.agent_id}>{titleCase(s)}</button>)}</div>}
          <label className="small muted" style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> Include closed</label>
        </div>
        {tab === "cases" ? (
          cases.error ? <div style={{ padding: 12 }}><ErrorNote error={cases.error} onRetry={cases.reload} /></div> : cases.loading ? <Loading /> : caseRows.length === 0 ? (
            <Empty icon={<Tray size={20} />} title="Nothing waiting" text="When a customer asks for a person or reports an issue, Subbu raises a case here with its SLA." />
          ) : (
            <div className="table-wrap"><table className="t"><thead><tr><th>Case</th><th>Priority</th><th>Status</th><th>Owner</th><th>SLA</th></tr></thead><tbody>
              {caseRows.map((c) => (
                <tr key={c.id} className="click" tabIndex={0} onClick={() => setParams({ tab: "cases", case: c.id })} onKeyDown={(e) => e.key === "Enter" && setParams({ tab: "cases", case: c.id })}>
                  <td className="primary-cell"><b>{titleCase(c.category)}</b><span>{c.id} · {c.customer_name ?? c.customer_ref}</span></td>
                  <td><Badge value={c.priority?.toUpperCase()} /></td><td><Badge value={c.status} /></td>
                  <td>{c.assigned_agent_name ?? <span className="muted">Unassigned</span>}</td>
                  <td><span className={`badge ${c.sla_breached ? "bad" : "plain"} num`}>{fmtRelative(c.sla_due_at)}</span></td>
                </tr>
              ))}
            </tbody></table></div>
          )
        ) : callbacks.error ? <div style={{ padding: 12 }}><ErrorNote error={callbacks.error} onRetry={callbacks.reload} /></div> : callbacks.loading ? <Loading /> : cbs.length === 0 ? (
          <Empty icon={<CalendarCheck size={20} />} title="No callbacks waiting" text="Callbacks booked by customers or staff appear here with their agreed time." />
        ) : (
          <div className="table-wrap"><table className="t"><thead><tr><th>Customer</th><th>When</th><th>Status</th><th>Owner</th><th>Attempts</th></tr></thead><tbody>
            {cbs.map((c) => (
              <tr key={c.id} className="click" tabIndex={0} onClick={() => setCbOpen(c)} onKeyDown={(e) => e.key === "Enter" && setCbOpen(c)}>
                <td className="primary-cell"><b>{c.customer_name ?? c.customer_ref}</b><span>{c.id}{c.case_id ? ` · ${c.case_id}` : ""}</span></td>
                <td className="num">{c.scheduled_at_utc ? <>{fmtDateTime(c.scheduled_at_utc)}<div className="small muted">{fmtRelative(c.scheduled_at_utc)}</div></> : <span className="muted">Time not agreed</span>}</td>
                <td><Badge value={c.status} /></td><td>{c.assigned_agent_name ?? <span className="muted">Unassigned</span>}</td><td className="num">{c.attempt_count}</td>
              </tr>
            ))}
          </tbody></table></div>
        )}
      </Panel>
      {caseId && <CaseDrawer id={caseId} onClose={() => setParams({ tab: "cases" })} onChanged={refresh} />}
      {cbOpen && <CallbackDrawer cb={cbOpen} onClose={() => setCbOpen(null)} onChanged={() => { refresh(); setCbOpen(null); }} />}
    </>
  );
}
