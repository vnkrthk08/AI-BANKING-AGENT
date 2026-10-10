import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CalendarCheck, Clock, Tray, WarningOctagon } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../auth/AuthContext";
import { apiJson } from "../services/http";
import {
  Badge,
  Drawer,
  Empty,
  ErrorNote,
  Kpi,
  Loading,
  Modal,
  PageHead,
  Panel,
  Tabs,
  fmtDateTime,
  fmtRelative,
  titleCase,
  useToast,
} from "../components/ui";

interface CaseRow {
  id: string;
  priority: string;
  status: string;
  category: string;
  case_type: string;
  customer_ref: string;
  customer_name: string | null;
  masked_phone: string;
  summary: string;
  assigned_team: string;
  assigned_agent_id: string | null;
  assigned_agent_name: string | null;
  sla_due_at: string | null;
  sla_breached: boolean;
  created_at: string;
  callback_id: string | null;
  resolution_notes: string | null;
  source: string;
  history?: {
    event_id: string;
    event_type: string;
    from_value: string | null;
    to_value: string | null;
    note: string | null;
    actor: string;
    created_at: string;
  }[];
}

interface CallbackRow {
  id: string;
  customer_ref: string;
  customer_name: string | null;
  maskedPhone: string;
  status: string;
  raw_status: string;
  scheduled_at_utc: string | null;
  relative_label: string;
  reason: string;
  case_id: string | null;
  priority: string | null;
  assigned_agent_name: string | null;
  attempt_count: number;
  last_outcome: string | null;
  outcome_notes: string | null;
  version: number;
  moved_label: string | null;
  history: {
    event_id: string;
    event_type: string;
    actor: string;
    old_value: string | null;
    new_value: string | null;
    created_at: string;
  }[];
}

interface Agent {
  id: string;
  name: string;
  availability: string;
  openCases: number;
  maxOpenCases: number;
  skills: string[];
}

const OPEN = ["NEW", "ASSIGNED", "IN_PROGRESS", "PENDING_CUSTOMER"];
const PRIORITY_RANK: Record<string, number> = { urgent: 0, high: 1, normal: 2, low: 3 };

function useAction(onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };
  return { busy, err, run, setErr };
}

function CaseDrawer({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { can, user } = useAuth();
  const toast = useToast();
  const { data: c, reload } = useApi<CaseRow>(`/api/escalations/${id}`, [id]);
  const agents = useApi<{ agents: Agent[] }>(can("case:assign") ? "/api/agents" : null);
  const { busy, err, run } = useAction(() => {
    void reload();
    onChanged();
  });
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolution, setResolution] = useState("");

  const patch = (body: object) => apiJson(`/api/escalations/${id}`, { method: "PATCH", body: JSON.stringify(body) });

  if (!c) return <Drawer title="Case" onClose={onClose}><Loading /></Drawer>;

  const open = OPEN.includes(c.status);
  const mine = user?.agent_id && c.assigned_agent_id === user.agent_id;

  const handleStartWork = () => {
    run(async () => {
      await patch({ status: "IN_PROGRESS" });
      toast.ok("Status updated", "Case is now in progress.");
    });
  };

  const handleSaveNote = () => {
    run(async () => {
      await patch({ note });
      setNote("");
      toast.ok("Note saved", "Case note added successfully.");
    });
  };

  const handleResolve = () => {
    run(async () => {
      await patch({ status: "RESOLVED", resolution_notes: resolution });
      setResolving(false);
      toast.ok("Case resolved", `Case ${c.id} marked as resolved.`);
    });
  };

  return (
    <Drawer
      title={`${titleCase(c.category)}`}
      sub={`${c.id} · ${c.customer_name ?? c.customer_ref} ${c.masked_phone ? `· ${c.masked_phone}` : ""}`}
      onClose={onClose}
      footer={
        open &&
        can("case:work") && (
          <>
            {c.status !== "IN_PROGRESS" && (
              <button className="btn" disabled={busy} onClick={handleStartWork}>
                Start work
              </button>
            )}
            <button className="btn primary" disabled={busy} onClick={() => setResolving(true)}>
              Resolve case
            </button>
          </>
        )
      }
    >
      {err && <ErrorNote error={err} />}
      <div className="actions">
        <Badge value={c.priority?.toUpperCase()} />
        <Badge value={c.status} />
        <span className={`badge ${c.sla_breached ? "bad" : "plain"}`}>
          {c.sla_breached ? "Past SLA " : "SLA due "}
          {fmtRelative(c.sla_due_at)}
        </span>
      </div>

      <dl className="kv">
        <dt>Summary</dt>
        <dd>{c.summary || "—"}</dd>
        <dt>Team</dt>
        <dd>{titleCase(c.assigned_team)}</dd>
        <dt>Owner</dt>
        <dd>
          {c.assigned_agent_name ?? "Unassigned"}
          {mine ? " (you)" : ""}
        </dd>
        <dt>SLA due</dt>
        <dd className="num">{fmtDateTime(c.sla_due_at)}</dd>
        <dt>Raised</dt>
        <dd className="num">
          {fmtDateTime(c.created_at)} · {c.source === "VOICE_AI" ? "by Subbu AI" : "by staff"}
        </dd>
        <dt>Callback</dt>
        <dd>{c.callback_id ?? "—"}</dd>
        {c.resolution_notes && (
          <>
            <dt>Resolution</dt>
            <dd>{c.resolution_notes}</dd>
          </>
        )}
      </dl>

      {open && can("case:assign") && (
        <section>
          <h3 className="section-title">Ownership & Assignment</h3>
          <div className="actions">
            <select
              className="select"
              aria-label="Assign to agent"
              value={c.assigned_agent_id ?? ""}
              disabled={busy}
              onChange={(e) =>
                e.target.value &&
                run(async () => {
                  await patch({ assigned_agent_id: e.target.value });
                  toast.ok("Owner reassigned", "Case assigned to selected agent.");
                })
              }
            >
              <option value="">{c.assigned_agent_id ? "Reassign to…" : "Assign to…"}</option>
              {agents.data?.agents
                .filter((a) => a.availability !== "OFFLINE")
                .map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} · {titleCase(a.availability)} · {a.openCases}/{a.maxOpenCases} cases
                  </option>
                ))}
            </select>
            <button
              className="btn"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  const res = await apiJson("/api/agents/assign", {
                    method: "POST",
                    body: JSON.stringify({ category: c.category }),
                  });
                  const agent = (res as { assigned_agent: Agent }).assigned_agent;
                  await patch({ assigned_agent_id: agent.id });
                  toast.ok("Auto-assigned", `Case assigned to ${agent.name}.`);
                })
              }
            >
              Auto-assign
            </button>
          </div>
        </section>
      )}

      {open && can("case:work") && (
        <section>
          <h3 className="section-title">Case Notes</h3>
          <textarea
            className="input"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Add operational notes visible to the entire team. (Do not record OTPs, PINs, passwords or card numbers)."
          />
          <div style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy || !note.trim()} onClick={handleSaveNote}>
              Save note
            </button>
          </div>
        </section>
      )}

      <section>
        <h3 className="section-title">Audit History</h3>
        <div className="timeline">
          {(c.history ?? []).map((h) => (
            <div className="tl" key={h.event_id}>
              <div>
                <b>{titleCase(h.event_type)}</b>
                {h.to_value ? ` → ${h.to_value}` : ""}
                {h.note && <div>{h.note}</div>}
                <small>
                  {h.actor} · {fmtDateTime(h.created_at)}
                </small>
              </div>
            </div>
          ))}
        </div>
      </section>

      {resolving && (
        <Modal
          title="Resolve case"
          onClose={() => setResolving(false)}
          footer={
            <>
              <button className="btn" onClick={() => setResolving(false)}>
                Cancel
              </button>
              <button className="btn primary" disabled={busy || !resolution.trim()} onClick={handleResolve}>
                Resolve case
              </button>
            </>
          }
        >
          <label className="field">
            Resolution notes
            <textarea
              className="input"
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              placeholder="State what action was taken to resolve the customer's issue."
            />
            <small>Required for audit compliance. Saved to case history.</small>
          </label>
        </Modal>
      )}
    </Drawer>
  );
}

function CallbackDrawer({ cb, onClose, onChanged }: { cb: CallbackRow; onClose: () => void; onChanged: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const { busy, err, run } = useAction(onChanged);
  const [when, setWhen] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [outcome, setOutcome] = useState("COMPLETED");
  const [notes, setNotes] = useState("");
  const agents = useApi<{ agents: Agent[] }>(can("case:assign") ? "/api/agents" : null);
  const active = ["REQUESTED", "SCHEDULED", "DUE"].includes(cb.raw_status);

  return (
    <Drawer
      title={cb.customer_name ?? cb.customer_ref}
      sub={`${cb.id} · ${cb.maskedPhone}`}
      onClose={onClose}
      footer={
        active &&
        can("callback:manage") && (
          <button className="btn danger" disabled={busy} onClick={() => setConfirmCancel(true)}>
            Cancel callback
          </button>
        )
      }
    >
      {err && <ErrorNote error={err} />}
      <div className="actions">
        <Badge value={cb.status} />
        {cb.priority && <Badge value={cb.priority.toUpperCase()} />}
      </div>

      <dl className="kv">
        <dt>Scheduled time</dt>
        <dd>
          {cb.scheduled_at_utc
            ? `${fmtDateTime(cb.scheduled_at_utc)} (${fmtRelative(cb.scheduled_at_utc)})`
            : "Time slot not agreed yet"}
        </dd>
        <dt>Reason</dt>
        <dd>{titleCase(cb.reason)}</dd>
        <dt>Linked case</dt>
        <dd>{cb.case_id ?? "—"}</dd>
        <dt>Owner</dt>
        <dd>{cb.assigned_agent_name ?? "Unassigned"}</dd>
        <dt>Dial attempts</dt>
        <dd>
          {cb.attempt_count}
          {cb.last_outcome ? ` · last outcome: ${titleCase(cb.last_outcome)}` : ""}
        </dd>
        {cb.outcome_notes && (
          <>
            <dt>Note</dt>
            <dd>{cb.outcome_notes}</dd>
          </>
        )}
      </dl>

      {active && can("callback:manage") && (
        <section>
          <h3 className="section-title">{cb.scheduled_at_utc ? "Reschedule callback" : "Agree a time slot"}</h3>
          <div className="actions">
            <input
              type="datetime-local"
              className="input"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
              aria-label="New callback time"
            />
            <button
              className="btn primary"
              disabled={busy || !when}
              onClick={() =>
                run(async () => {
                  await apiJson(`/api/callbacks/${cb.id}/reschedule`, {
                    method: "POST",
                    body: JSON.stringify({ preferredAt: new Date(when).toISOString() }),
                  });
                  toast.ok("Callback rescheduled", "New preferred calling window set.");
                })
              }
            >
              Save time
            </button>
          </div>
          <p className="small muted">
            Calling window: 09:00–19:00 IST (excluding Sundays and national holidays).
          </p>
        </section>
      )}

      {active && can("case:assign") && (
        <section>
          <h3 className="section-title">Owner Assignment</h3>
          <select
            className="select"
            aria-label="Assign callback"
            value=""
            disabled={busy}
            onChange={(e) =>
              e.target.value &&
              run(async () => {
                await apiJson(`/api/callbacks/${cb.id}/assign`, {
                  method: "POST",
                  body: JSON.stringify({ agent_id: e.target.value }),
                });
                toast.ok("Owner assigned", "Callback assigned to agent.");
              })
            }
          >
            <option value="">{cb.assigned_agent_name ? `Reassign (now ${cb.assigned_agent_name})…` : "Assign to…"}</option>
            {agents.data?.agents
              .filter((a) => a.availability !== "OFFLINE")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} · {titleCase(a.availability)}
                </option>
              ))}
          </select>
        </section>
      )}

      {active && can("callback:manage") && (
        <section>
          <h3 className="section-title">Record manual call outcome</h3>
          <p className="small muted" style={{ marginTop: 0 }}>
            Use after placing the outbound phone call yourself.
          </p>
          <div className="actions">
            <select
              className="select"
              aria-label="Call outcome"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            >
              {[
                ["COMPLETED", "Spoke to customer (Resolved)"],
                ["BUSY", "Line busy"],
                ["NO_ANSWER", "Not answered"],
                ["WRONG_NUMBER", "Wrong number"],
                ["CUSTOMER_DECLINED", "Customer declined call"],
                ["FAILED", "Could not connect"],
              ].map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <textarea
            className="input"
            style={{ marginTop: 8 }}
            aria-label="Outcome notes"
            placeholder="What happened on the call? (Never record OTPs, PINs or card numbers)."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div style={{ marginTop: 8 }}>
            <button
              className="btn primary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await apiJson(`/api/callbacks/${cb.id}/outcome`, {
                    method: "POST",
                    body: JSON.stringify({ outcome, notes }),
                  });
                  toast.ok("Outcome recorded", `Callback marked as ${titleCase(outcome)}.`);
                })
              }
            >
              Save outcome
            </button>
          </div>
        </section>
      )}

      <section>
        <h3 className="section-title">History</h3>
        <div className="timeline">
          {cb.history.map((h) => (
            <div className="tl" key={h.event_id}>
              <div>
                <b>{titleCase(h.event_type)}</b>
                {h.new_value ? ` → ${h.new_value}` : ""}
                <small>
                  {h.actor} · {fmtDateTime(h.created_at)}
                </small>
              </div>
            </div>
          ))}
        </div>
      </section>

      {confirmCancel && (
        <Modal
          title="Cancel this callback?"
          onClose={() => setConfirmCancel(false)}
          footer={
            <>
              <button className="btn" onClick={() => setConfirmCancel(false)}>
                Keep callback
              </button>
              <button
                className="btn danger solid"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await apiJson(`/api/callbacks/${cb.id}/cancel`, { method: "POST", body: "{}" });
                    toast.warn("Callback cancelled", "Customer will not be dialled.");
                    setConfirmCancel(false);
                  })
                }
              >
                Cancel callback
              </button>
            </>
          }
        >
          <p style={{ margin: 0 }}>The customer will not be dialled. This cancellation is recorded in the permanent audit trail.</p>
        </Modal>
      )}
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
    .sort(
      (a, b) =>
        Number(b.sla_breached) - Number(a.sla_breached) ||
        (PRIORITY_RANK[a.priority?.toLowerCase()] ?? 9) - (PRIORITY_RANK[b.priority?.toLowerCase()] ?? 9) ||
        (a.sla_due_at ?? "").localeCompare(b.sla_due_at ?? "")
    );

  const cbs = (callbacks.data ?? []).filter(
    (c) => showClosed || ["REQUESTED", "SCHEDULED", "DUE", "DIALING", "OVERDUE"].includes(c.status)
  );

  const refresh = () => {
    void cases.reload();
    void callbacks.reload();
  };

  const slaBreachedCount = openCases.filter((c) => c.sla_breached).length;
  const unassignedCount = openCases.filter((c) => !c.assigned_agent_id).length;
  const dueCallbacksCount = (callbacks.data ?? []).filter((c) => c.status === "DUE" || c.status === "OVERDUE").length;

  return (
    <>
      <PageHead
        title="Work Queue"
        sub="Escalated customer issues and booked callbacks waiting on banking operators, prioritized by SLA deadline."
      />

      {cases.data && callbacks.data && (
        <div className="kpis">
          <Kpi label="Open cases" value={openCases.length} />
          <Kpi
            label="Unassigned"
            value={unassignedCount}
            hint="Awaiting owner"
            tone={unassignedCount > 0 ? "warn" : undefined}
          />
          <Kpi
            label="Past SLA"
            value={slaBreachedCount}
            hint="Needs immediate action"
            tone={slaBreachedCount > 0 ? "alert" : undefined}
          />
          <Kpi
            label="Callbacks due"
            value={dueCallbacksCount}
            hint="Ready for outbound dial"
            tone={dueCallbacksCount > 0 ? "warn" : undefined}
          />
          <Kpi
            label="Needs slot"
            value={(callbacks.data ?? []).filter((c) => c.status === "REQUESTED").length}
            hint="Customer awaiting call time"
          />
        </div>
      )}

      <Tabs
        value={tab}
        onChange={(t) => setParams({ tab: t })}
        items={[
          { key: "cases", label: "Cases", count: openCases.length },
          { key: "callbacks", label: "Callbacks", count: cbs.length, pulse: dueCallbacksCount > 0 },
        ]}
      />

      <Panel flush>
        <div className="toolbar">
          {tab === "cases" && (
            <div className="seg" role="group" aria-label="Scope filter">
              {(["all", "mine", "unassigned"] as const).map((s) => (
                <button
                  key={s}
                  className={scope === s ? "on" : ""}
                  onClick={() => setScope(s)}
                  disabled={s === "mine" && !user?.agent_id}
                >
                  {titleCase(s)}
                </button>
              ))}
            </div>
          )}
          <label className="small muted" style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />
            Include resolved / closed
          </label>
        </div>

        {tab === "cases" ? (
          cases.error ? (
            <div style={{ padding: 12 }}>
              <ErrorNote error={cases.error} onRetry={cases.reload} />
            </div>
          ) : cases.loading ? (
            <Loading />
          ) : caseRows.length === 0 ? (
            <Empty
              icon={<Tray size={24} />}
              title="Nothing waiting in queue"
              text="When a customer requests staff assistance or reports an app update issue, Subbu creates a case here with an SLA guarantee."
            />
          ) : (
            <div className="table-wrap">
              <table className="t">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Owner</th>
                    <th>SLA Target</th>
                  </tr>
                </thead>
                <tbody>
                  {caseRows.map((c) => {
                    const stripeClass =
                      c.priority?.toLowerCase() === "urgent"
                        ? "stripe-urgent"
                        : c.priority?.toLowerCase() === "high"
                        ? "stripe-high"
                        : "stripe-normal";
                    return (
                      <tr
                        key={c.id}
                        className={`click ${stripeClass}`}
                        tabIndex={0}
                        onClick={() => setParams({ tab: "cases", case: c.id })}
                        onKeyDown={(e) => e.key === "Enter" && setParams({ tab: "cases", case: c.id })}
                      >
                        <td className="primary-cell">
                          <b>{titleCase(c.category)}</b>
                          <span>
                            {c.id} · {c.customer_name ?? c.customer_ref}
                          </span>
                        </td>
                        <td>
                          <Badge value={c.priority?.toUpperCase()} />
                        </td>
                        <td>
                          <Badge value={c.status} />
                        </td>
                        <td>{c.assigned_agent_name ?? <span className="muted">Unassigned</span>}</td>
                        <td>
                          {c.sla_breached ? (
                            <span className="badge bad" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                              <WarningOctagon size={13} weight="fill" /> Breached {fmtRelative(c.sla_due_at)}
                            </span>
                          ) : (
                            <span className="badge plain" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                              <Clock size={13} /> Due {fmtRelative(c.sla_due_at)}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : callbacks.error ? (
          <div style={{ padding: 12 }}>
            <ErrorNote error={callbacks.error} onRetry={callbacks.reload} />
          </div>
        ) : callbacks.loading ? (
          <Loading />
        ) : cbs.length === 0 ? (
          <Empty
            icon={<CalendarCheck size={24} />}
            title="No callbacks waiting"
            text="Callbacks scheduled with customers appear here with their agreed calling window."
          />
        ) : (
          <div className="table-wrap">
            <table className="t">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Scheduled Window</th>
                  <th>Status</th>
                  <th>Owner</th>
                  <th>Attempts</th>
                </tr>
              </thead>
              <tbody>
                {cbs.map((c) => (
                  <tr
                    key={c.id}
                    className="click"
                    tabIndex={0}
                    onClick={() => setCbOpen(c)}
                    onKeyDown={(e) => e.key === "Enter" && setCbOpen(c)}
                  >
                    <td className="primary-cell">
                      <b>{c.customer_name ?? c.customer_ref}</b>
                      <span>
                        {c.id}
                        {c.case_id ? ` · Linked Case: ${c.case_id}` : ""}
                      </span>
                    </td>
                    <td className="num">
                      {c.scheduled_at_utc ? (
                        <>
                          {fmtDateTime(c.scheduled_at_utc)}
                          <div className="small muted">{fmtRelative(c.scheduled_at_utc)}</div>
                        </>
                      ) : (
                        <span className="muted">Time slot not agreed</span>
                      )}
                    </td>
                    <td>
                      <Badge value={c.status} />
                    </td>
                    <td>{c.assigned_agent_name ?? <span className="muted">Unassigned</span>}</td>
                    <td className="num">{c.attempt_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {caseId && <CaseDrawer id={caseId} onClose={() => setParams({ tab: "cases" })} onChanged={refresh} />}
      {cbOpen && (
        <CallbackDrawer
          cb={cbOpen}
          onClose={() => setCbOpen(null)}
          onChanged={() => {
            refresh();
            setCbOpen(null);
          }}
        />
      )}
    </>
  );
}
