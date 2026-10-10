import { useState } from "react";
import { CheckCircle, Megaphone, Plus, UploadSimple, XCircle } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../auth/AuthContext";
import { apiJson } from "../services/http";
import { Badge, Drawer, Empty, ErrorNote, Loading, Modal, PageHead, Panel, fmtDateTime, titleCase } from "../components/ui";

interface Campaign { id: string; name: string; objective: string; status: string; category: string; scriptVersion: string; languages: string[]; region: string; maxAttempts: number; retryGapHours: number; maxConcurrent: number; approvedBy: string | null; approvedAt: string | null; createdBy: string | null; callsDialed: number; answerRate: number; contactStats: Record<string, number>; updatedAt: string }
interface Preflight { ready: boolean; checks: { key: string; label: string; ok: boolean; detail: string }[]; eligible_contacts: number; calling_window_open: boolean; calling_window_note: string | null }
interface Contact { contact_id: string; customer_ref: string; phone: string; status: string; attempts_count: number; last_disposition: string | null; next_attempt_at: string | null }

function total(stats: Record<string, number>) { return Object.values(stats).reduce((a, b) => a + b, 0); }

function CampaignDrawer({ c, onClose, onChanged }: { c: Campaign; onClose: () => void; onChanged: () => void }) {
  const { can } = useAuth();
  const pre = useApi<Preflight>(`/api/campaigns/${c.id}/preflight`, [c.id, c.status]);
  const contacts = useApi<Contact[]>(`/api/campaigns/${c.id}/contacts?limit=200`, [c.id]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | "cancel">(null);
  const act = async (path: string, body?: BodyInit) => {
    setBusy(true); setErr(null);
    try { await apiJson(`/api/campaigns/${c.id}/${path}`, { method: "POST", body: body ?? "{}" }); onChanged(); void pre.reload(); void contacts.reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Action failed"); } finally { setBusy(false); }
  };
  const importCsv = (file: File) => { const fd = new FormData(); fd.append("file", file); void act("contacts/import", fd); };
  const s = c.status;
  return (
    <Drawer title={c.name} sub={`${c.id} · ${c.objective}`} onClose={onClose} footer={<>
      {s === "DRAFT" && can("campaign:approve") && <button className="btn" disabled={busy} onClick={() => act("approve")}>Approve for calling</button>}
      {(s === "APPROVED" || s === "PAUSED") && can("campaign:execute") && <button className="btn primary" disabled={busy || !pre.data?.ready} onClick={() => act(s === "PAUSED" ? "resume" : "start")} title={pre.data?.ready ? "" : "Resolve the preflight checks first"}>{s === "PAUSED" ? "Resume" : "Start campaign"}</button>}
      {s === "ACTIVE" && can("campaign:execute") && <button className="btn" disabled={busy} onClick={() => act("pause")}>Pause</button>}
      {!["COMPLETED", "CANCELLED"].includes(s) && can("campaign:execute") && <button className="btn danger" disabled={busy} onClick={() => setConfirm("cancel")}>Cancel campaign</button>}
    </>}>
      {err && <ErrorNote error={err} />}
      <div className="actions"><Badge value={s} /><Badge value={c.category} tone={c.category === "SERVICE" ? "" : "warn"} /><span className="badge plain">Script {c.scriptVersion}</span></div>
      <dl className="kv">
        <dt>Languages</dt><dd>{c.languages.join(", ")}</dd><dt>Region</dt><dd>{c.region}</dd>
        <dt>Attempts / gap</dt><dd>{c.maxAttempts} attempts, {c.retryGapHours}h apart</dd><dt>Concurrency</dt><dd>{c.maxConcurrent} simultaneous calls</dd>
        <dt>Approval</dt><dd>{c.approvedBy ? `${c.approvedBy} · ${fmtDateTime(c.approvedAt)}` : "Not approved"}</dd>
        <dt>Dialled / answered</dt><dd className="num">{c.callsDialed} · {c.callsDialed ? `${Math.round(c.answerRate * 100)}%` : "—"}</dd>
      </dl>
      <section><h3 className="section-title">Preflight</h3>
        {pre.loading ? <Loading rows={3} /> : pre.data && <>
          {pre.data.checks.map((k) => <div key={k.key} className="legend-row"><span style={{ display: "flex", gap: 8, alignItems: "center" }}>{k.ok ? <CheckCircle size={18} color="var(--ok)" weight="fill" /> : <XCircle size={18} color="var(--bad)" weight="fill" />}{k.label}</span><span className="small muted" style={{ textAlign: "right" }}>{k.detail}</span></div>)}
          {pre.data.calling_window_note && <p className="small muted">{pre.data.calling_window_note}</p>}
        </>}
      </section>
      <section><div className="actions" style={{ justifyContent: "space-between" }}><h3 className="section-title" style={{ margin: 0 }}>Contacts ({total(c.contactStats)})</h3>
        {can("campaign:manage") && <label className="btn sm"><UploadSimple size={14} /> Import CSV<input type="file" accept=".csv" hidden onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} /></label>}</div>
        <div className="chips" style={{ margin: "8px 0" }}>{Object.entries(c.contactStats).map(([k, n]) => <span key={k} className="badge plain">{titleCase(k)} {n}</span>)}</div>
        {contacts.data?.length ? <div className="table-wrap"><table className="t"><thead><tr><th>Customer</th><th>Status</th><th>Attempts</th></tr></thead><tbody>
          {contacts.data.slice(0, 50).map((x) => <tr key={x.contact_id}><td className="primary-cell"><b>{x.customer_ref}</b><span className="num">{x.phone}</span></td><td><Badge value={x.status} /></td><td className="num">{x.attempts_count}</td></tr>)}
        </tbody></table></div> : <p className="muted small">No contacts yet. CSV columns: customer_ref, phone.</p>}
      </section>
      {confirm && <Modal title="Cancel campaign?" onClose={() => setConfirm(null)} footer={<><button className="btn" onClick={() => setConfirm(null)}>Keep campaign</button><button className="btn danger solid" disabled={busy} onClick={() => act("cancel").then(() => setConfirm(null))}>Cancel campaign</button></>}>
        <p style={{ margin: 0 }}>All pending contacts are cancelled and will not be dialled. Completed outcomes are kept.</p></Modal>}
    </Drawer>
  );
}

export function CampaignsPage() {
  const { can } = useAuth();
  const { data, error, loading, reload } = useApi<Campaign[]>("/api/campaigns");
  const health = useApi<{ dialing: { stopped: boolean; reason: string | null; actor: string | null }; components: { key: string; status: string }[] }>("/api/system/health");
  const [openId, setOpenId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", objective: "App update support", scriptVersion: "v1.0", languages: "English, Hindi", maxAttempts: 3, retryGapHours: 24, maxConcurrent: 2 });
  const [err, setErr] = useState<string | null>(null);
  const open = data?.find((c) => c.id === openId) ?? null;
  const create = async () => {
    try {
      await apiJson("/api/campaigns", { method: "POST", body: JSON.stringify({ ...form, languages: form.languages.split(",").map((s) => s.trim()).filter(Boolean), category: "SERVICE" }) });
      setCreating(false); void reload();
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not create"); }
  };
  const tel = health.data?.components.find((c) => c.key === "telephony")?.status;
  return (
    <>
      <PageHead title="Campaigns" sub="Outbound service campaigns. Every launch requires compliance approval and passing preflight checks." actions={can("campaign:manage") && <button className="btn primary" onClick={() => setCreating(true)}><Plus size={16} /> New campaign</button>} />
      {health.data?.dialing.stopped && <div className="alert bad"><span className="grow"><b>Outbound dialing is stopped.</b> {health.data.dialing.reason ?? ""} {health.data.dialing.actor ? `— ${health.data.dialing.actor}` : ""}</span></div>}
      {tel && tel !== "HEALTHY" && <div className="alert info"><span className="grow">No live telephony provider is configured, so campaigns cannot start dialling. Configure telephony in the deployment settings.</span></div>}
      {error && <ErrorNote error={error} onRetry={reload} />}
      <Panel flush>
        {loading ? <Loading /> : !data?.length ? <Empty icon={<Megaphone size={20} />} title="No campaigns yet" text="Create a draft, add contacts, get compliance approval, then start when preflight passes." /> : (
          <div className="table-wrap"><table className="t"><thead><tr><th>Campaign</th><th>Status</th><th>Contacts</th><th>Dialled</th><th>Answer rate</th><th>Updated</th></tr></thead><tbody>
            {data.map((c) => <tr key={c.id} className="click" tabIndex={0} onClick={() => setOpenId(c.id)} onKeyDown={(e) => e.key === "Enter" && setOpenId(c.id)}>
              <td className="primary-cell"><b>{c.name}</b><span>{c.objective} · {c.languages.join(", ")}</span></td><td><Badge value={c.status} /></td>
              <td className="num">{total(c.contactStats)}</td><td className="num">{c.callsDialed}</td><td className="num">{c.callsDialed ? `${Math.round(c.answerRate * 100)}%` : "—"}</td><td className="num">{fmtDateTime(c.updatedAt)}</td>
            </tr>)}
          </tbody></table></div>
        )}
      </Panel>
      {open && <CampaignDrawer c={open} onClose={() => setOpenId(null)} onChanged={() => void reload()} />}
      {creating && <Modal title="New campaign" onClose={() => setCreating(false)} footer={<><button className="btn" onClick={() => setCreating(false)}>Cancel</button><button className="btn primary" disabled={!form.name.trim()} onClick={create}>Create draft</button></>}>
        {err && <ErrorNote error={err} />}
        <label className="field">Name<input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="field">Objective<input className="input" value={form.objective} onChange={(e) => setForm({ ...form, objective: e.target.value })} /></label>
        <label className="field">Languages<input className="input" value={form.languages} onChange={(e) => setForm({ ...form, languages: e.target.value })} /><small>Comma separated</small></label>
        <div className="grid cols-2" style={{ gap: 12 }}>
          <label className="field">Max attempts<input className="input" type="number" min={1} max={5} value={form.maxAttempts} onChange={(e) => setForm({ ...form, maxAttempts: Number(e.target.value) })} /></label>
          <label className="field">Retry gap (hours)<input className="input" type="number" min={1} value={form.retryGapHours} onChange={(e) => setForm({ ...form, retryGapHours: Number(e.target.value) })} /></label>
        </div>
        <p className="small muted" style={{ margin: 0 }}>Service campaigns only. Promotional calling is disabled pending legal sign-off.</p>
      </Modal>}
    </>
  );
}
