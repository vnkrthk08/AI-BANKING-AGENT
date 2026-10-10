import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus, Warning } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../auth/AuthContext";
import { apiJson } from "../services/http";
import { Badge, Empty, ErrorNote, Loading, Modal, PageHead, Panel, Tabs, fmtDateTime, titleCase } from "../components/ui";

interface Health { environment: string; components: { key: string; label: string; status: string; detail: string }[]; dialing: { stopped: boolean; reason: string | null; actor: string | null; updated_at: string | null }; autodial_enabled: boolean; dial_allowlist_active: boolean; recording_enabled: boolean }
interface Delivery { id: string; event_type: string; channel: string; recipient: string; address: string; subject: string; status: string; attempts: number; max_attempts: number; last_error: string | null; created_at: string }
interface Audit { id: string; actor: string; actorRole: string; action: string; resourceType: string; resourceId: string; timestamp: string; ip: string; detail: string }
interface Compliance { consents: { callId: string; customerRef: string; consented: boolean; recordedAt: string; retentionUntil: string; channel: string }[]; policy: Record<string, string | number | boolean> }
interface User { id: string; username: string; full_name: string; role: string; email: string; is_active: boolean }
type TabKey = "health" | "notifications" | "audit" | "compliance" | "users";

function HealthTab() {
  const { can } = useAuth();
  const { data, error, loading, reload } = useApi<Health>("/api/system/health");
  const [dialog, setDialog] = useState<null | boolean>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const setDialing = async (stopped: boolean) => {
    try { await apiJson("/api/system/dialing", { method: "POST", body: JSON.stringify({ stopped, reason: reason || null }) }); setDialog(null); setReason(""); void reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Failed"); }
  };
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error ?? "Unavailable"} onRetry={reload} />;
  return (
    <div className="stack">
      <Panel title="Outbound dialing" sub={data.dialing.stopped ? `Stopped by ${data.dialing.actor ?? "—"} · ${fmtDateTime(data.dialing.updated_at)}` : "Campaigns and due callbacks may dial when every policy gate passes"}
        actions={data.dialing.stopped ? can("system:resume_dialing") && <button className="btn" onClick={() => setDialog(false)}>Resume dialing</button> : can("system:emergency_stop") && <button className="btn danger solid" onClick={() => setDialog(true)}><Warning size={16} /> Emergency stop</button>}>
        <div className="actions"><Badge tone={data.dialing.stopped ? "bad" : "ok"}>{data.dialing.stopped ? "Stopped" : "Enabled"}</Badge>
          <Badge tone={data.autodial_enabled ? "ok" : ""}>Callback auto-dial {data.autodial_enabled ? "on" : "off"}</Badge>
          <Badge tone={data.dial_allowlist_active ? "info" : ""}>Test-number allowlist {data.dial_allowlist_active ? "active" : "off"}</Badge>
          <Badge tone={data.recording_enabled ? "info" : ""}>Call recording {data.recording_enabled ? "on" : "off"}</Badge>
          <span className="badge plain">Environment: {data.environment}</span></div>
        {data.dialing.reason && <p className="small muted">Reason: {data.dialing.reason}</p>}
      </Panel>
      <Panel title="Integrations" sub="Live checks from the API server" flush>
        <div className="rows">{data.components.map((c) => <div className="row-item" key={c.key}><div className="grow"><b>{c.label}</b><span>{c.detail || "—"}</span></div><Badge value={c.status} /></div>)}</div>
      </Panel>
      {err && <ErrorNote error={err} />}
      {dialog !== null && <Modal title={dialog ? "Stop all outbound dialing?" : "Resume outbound dialing?"} onClose={() => setDialog(null)} footer={<><button className="btn" onClick={() => setDialog(null)}>Cancel</button><button className={`btn ${dialog ? "danger solid" : "primary"}`} onClick={() => setDialing(dialog)}>{dialog ? "Stop dialing" : "Resume"}</button></>}>
        <p style={{ marginTop: 0 }}>{dialog ? "Every worker stops placing campaign and callback calls immediately. Queued contacts are released." : "Dialing resumes subject to approvals, calling window and preflight checks."}</p>
        <label className="field">Reason<input className="input" value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      </Modal>}
    </div>
  );
}

function NotificationsTab() {
  const { data, error, loading, reload } = useApi<{ deliveries: Delivery[]; summary: Record<string, Record<string, number>> }>("/api/notifications/deliveries?limit=200");
  const channels = useApi<{ channels: { channel: string; label: string; status: string; description: string }[] }>("/api/notifications/channels");
  const retry = async (id: string) => { await apiJson(`/api/notifications/deliveries/${id}/retry`, { method: "POST" }).catch(() => undefined); void reload(); };
  return (
    <div className="stack">
      <Panel title="Channels" flush>{channels.data ? <div className="rows">{channels.data.channels.map((c) => <div className="row-item" key={c.channel}><div className="grow"><b>{c.label}</b><span>{c.description}</span></div><Badge value={c.status} /></div>)}</div> : <Loading rows={2} />}</Panel>
      <Panel title="Delivery log" sub="Sent means accepted by the e-mail/SMS provider; it is not a handset or inbox receipt." flush>
        {error ? <div style={{ padding: 12 }}><ErrorNote error={error} onRetry={reload} /></div> : loading ? <Loading /> : !data?.deliveries.length ? <Empty title="No notifications yet" text="Case, callback and system events create notifications here." /> : (
          <div className="table-wrap"><table className="t"><thead><tr><th>Event</th><th>Channel</th><th>Recipient</th><th>Status</th><th>Attempts</th><th>Created</th><th /></tr></thead><tbody>
            {data.deliveries.map((d) => <tr key={d.id}><td className="primary-cell"><b>{d.subject}</b><span>{d.event_type}</span></td><td>{titleCase(d.channel)}</td><td className="primary-cell"><b>{d.recipient}</b><span>{d.address}</span></td>
              <td><Badge value={d.status} />{d.last_error && d.status !== "DELIVERED" && <div className="small muted">{d.last_error}</div>}</td><td className="num">{d.attempts}/{d.max_attempts}</td><td className="num">{fmtDateTime(d.created_at)}</td>
              <td>{d.status === "FAILED" && <button className="btn sm" onClick={() => retry(d.id)}>Retry</button>}</td></tr>)}
          </tbody></table></div>
        )}
      </Panel>
    </div>
  );
}

function AuditTab() {
  const { data, error, loading, reload } = useApi<Audit[]>("/api/audit?limit=300");
  const [q, setQ] = useState("");
  const rows = (data ?? []).filter((a) => !q || `${a.action} ${a.actor} ${a.resourceId}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <Panel flush title="Audit trail" sub="Operator actions with actor, role and source IP">
      <div className="toolbar"><input className="input" placeholder="Filter by action, actor or resource" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter audit" /></div>
      {error ? <div style={{ padding: 12 }}><ErrorNote error={error} onRetry={reload} /></div> : loading ? <Loading /> : !rows.length ? <Empty title="No audit events" /> : (
        <div className="table-wrap"><table className="t"><thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Resource</th><th>IP</th></tr></thead><tbody>
          {rows.map((a) => <tr key={a.id}><td className="num">{fmtDateTime(a.timestamp)}</td><td className="primary-cell"><b>{titleCase(a.action)}</b><span>{a.detail}</span></td><td className="primary-cell"><b>{a.actor}</b><span>{titleCase(a.actorRole)}</span></td><td className="mono">{a.resourceType}/{a.resourceId}</td><td className="mono">{a.ip}</td></tr>)}
        </tbody></table></div>
      )}
    </Panel>
  );
}

function ComplianceTab() {
  const { data, error, loading, reload } = useApi<Compliance>("/api/compliance/summary");
  if (loading) return <Loading />;
  if (error || !data) return <ErrorNote error={error ?? "Unavailable"} onRetry={reload} />;
  return (
    <div className="stack">
      <Panel title="Calling policy in force"><dl className="kv">{Object.entries(data.policy).map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{titleCase(k.replace(/([A-Z])/g, "_$1"))}</dt><dd>{String(v)}</dd></div>)}</dl></Panel>
      <Panel title="Consent ledger" sub="Connected calls and whether the customer agreed to continue" flush>
        {!data.consents.length ? <Empty title="No connected calls yet" /> : <div className="table-wrap"><table className="t"><thead><tr><th>Call</th><th>Customer</th><th>Consent</th><th>Recorded</th><th>Retain until</th></tr></thead><tbody>
          {data.consents.map((c) => <tr key={c.callId}><td className="mono">{c.callId}</td><td>{c.customerRef}</td><td>{c.consented ? <Badge tone="ok">Captured</Badge> : <Badge>Not captured</Badge>}</td><td className="num">{fmtDateTime(c.recordedAt)}</td><td className="num">{fmtDateTime(c.retentionUntil)}</td></tr>)}
        </tbody></table></div>}
      </Panel>
    </div>
  );
}

function UsersTab() {
  const { data, error, loading, reload } = useApi<User[]>("/api/v1/auth/users");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ username: "", full_name: "", email: "", role: "AGENT", password: "" });
  const [err, setErr] = useState<string | null>(null);
  const save = async () => { try { await apiJson("/api/v1/auth/users", { method: "POST", body: JSON.stringify(form) }); setAdding(false); void reload(); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); } };
  const deactivate = async (id: string) => { try { await apiJson(`/api/v1/auth/users/${id}/deactivate`, { method: "POST" }); void reload(); } catch (e) { setErr(e instanceof Error ? e.message : "Failed"); } };
  return (
    <Panel flush title="Access control" sub="Staff accounts and roles" actions={<button className="btn primary" onClick={() => setAdding(true)}><Plus size={16} /> Add user</button>}>
      {err && <div style={{ padding: 12 }}><ErrorNote error={err} /></div>}
      {error ? <div style={{ padding: 12 }}><ErrorNote error={error} onRetry={reload} /></div> : loading ? <Loading /> : (
        <div className="table-wrap"><table className="t"><thead><tr><th>User</th><th>Role</th><th>Status</th><th /></tr></thead><tbody>
          {(data ?? []).map((u) => <tr key={u.id}><td className="primary-cell"><b>{u.full_name}</b><span>{u.username} · {u.email}</span></td><td>{titleCase(u.role)}</td><td>{u.is_active ? <Badge tone="ok">Active</Badge> : <Badge>Deactivated</Badge>}</td><td>{u.is_active && <button className="btn sm danger" onClick={() => deactivate(u.id)}>Deactivate</button>}</td></tr>)}
        </tbody></table></div>
      )}
      {adding && <Modal title="Add user" onClose={() => setAdding(false)} footer={<><button className="btn" onClick={() => setAdding(false)}>Cancel</button><button className="btn primary" disabled={!form.username || form.password.length < 12} onClick={save}>Create user</button></>}>
        <label className="field">Full name<input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
        <label className="field">Username<input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label className="field">E-mail<input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        <label className="field">Role<select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{["OPS_MANAGER", "SUPERVISOR", "AGENT", "COMPLIANCE_OFFICER", "AUDITOR", "SYSTEM_ADMIN"].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}</select></label>
        <label className="field">Temporary password<input className="input" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><small>At least 12 characters.</small></label>
      </Modal>}
    </Panel>
  );
}

export function GovernanceHubPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const items: { key: TabKey; label: string }[] = [
    { key: "health", label: "System health" },
    ...(can("notification:deliveries") ? [{ key: "notifications" as const, label: "Notifications" }] : []),
    ...(can("audit:read") ? [{ key: "audit" as const, label: "Audit trail" }] : []),
    ...(can("compliance:read") ? [{ key: "compliance" as const, label: "Compliance" }] : []),
    ...(can("user:manage") ? [{ key: "users" as const, label: "Access control" }] : []),
  ];
  const tab = (items.find((i) => i.key === params.get("tab"))?.key ?? "health") as TabKey;
  return (
    <>
      <PageHead title="Governance" sub="Integration health, dialing controls, notification delivery, audit and compliance records." />
      <Tabs value={tab} onChange={(t) => setParams({ tab: t })} items={items} />
      {tab === "health" && <HealthTab />}{tab === "notifications" && <NotificationsTab />}{tab === "audit" && <AuditTab />}{tab === "compliance" && <ComplianceTab />}{tab === "users" && <UsersTab />}
    </>
  );
}
