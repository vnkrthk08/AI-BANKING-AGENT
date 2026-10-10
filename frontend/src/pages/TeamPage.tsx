import { useState } from "react";
import { Plus, UsersThree } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../auth/AuthContext";
import { apiJson } from "../services/http";
import { Badge, Empty, ErrorNote, Kpi, Loading, Modal, PageHead, Panel, titleCase } from "../components/ui";

interface Agent { id: string; name: string; team: string; languages: string[]; skills: string[]; availability: string; openCases: number; overdueCases: number; dueCallbacks: number; maxOpenCases: number; handledToday: number; avgResolutionMin: number | null; slaHitPercent: number | null; maskedPhone: string | null; userId: string | null }
const STATES = ["AVAILABLE", "BUSY", "ON_CALL", "BREAK", "OFFLINE"];

export function TeamPage() {
  const { can, user } = useAuth();
  const { data, error, loading, reload } = useApi<{ agents: Agent[] }>("/api/agents");
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", team: "Digital support", languages: "English, Hindi", skills: "GENERAL_SUPPORT, APP_SUPPORT", max_open_cases: 12 });
  const agents = data?.agents ?? [];
  const setAvail = async (id: string, availability: string) => {
    try { await apiJson(`/api/agents/${id}/status`, { method: "PATCH", body: JSON.stringify({ availability }) }); void reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Update failed"); }
  };
  const add = async () => {
    try {
      await apiJson("/api/agents", { method: "POST", body: JSON.stringify({ ...form, languages: form.languages.split(",").map((s) => s.trim()), skills: form.skills.split(",").map((s) => s.trim()) }) });
      setAdding(false); void reload();
    } catch (e) { setErr(e instanceof Error ? e.message : "Could not add agent"); }
  };
  const me = agents.find((a) => a.id === user?.agent_id);
  return (
    <>
      <PageHead title="Team" sub="Who is available, what they own and how close they are to capacity." actions={can("agent:manage") && <button className="btn primary" onClick={() => setAdding(true)}><Plus size={16} /> Add agent</button>} />
      {err && <ErrorNote error={err} />}
      {error && <ErrorNote error={error} onRetry={reload} />}
      {me && <Panel title="My availability" sub="New cases are only auto-assigned while you are Available"><div className="seg">{STATES.map((s) => <button key={s} className={me.availability === s ? "on" : ""} onClick={() => setAvail(me.id, s)}>{titleCase(s)}</button>)}</div></Panel>}
      {me && <div style={{ height: 16 }} />}
      <div className="kpis">
        <Kpi label="Agents" value={agents.length} />
        <Kpi label="Available" value={agents.filter((a) => a.availability === "AVAILABLE").length} />
        <Kpi label="Open cases owned" value={agents.reduce((s, a) => s + a.openCases, 0)} />
        <Kpi label="Overdue" value={agents.reduce((s, a) => s + a.overdueCases, 0)} tone={agents.some((a) => a.overdueCases) ? "alert" : undefined} />
      </div>
      <Panel flush>
        {loading ? <Loading /> : !agents.length ? <Empty icon={<UsersThree size={20} />} title="No agents registered" text="Add the people who handle escalations and callbacks. Link them to a user account to give them a personal queue." /> : (
          <div className="table-wrap"><table className="t"><thead><tr><th>Agent</th><th>Availability</th><th>Workload</th><th>Handled today</th><th>Avg resolution</th><th>SLA met</th></tr></thead><tbody>
            {agents.map((a) => {
              const pct = Math.round((100 * a.openCases) / Math.max(a.maxOpenCases, 1));
              return <tr key={a.id}>
                <td className="primary-cell"><b>{a.name}</b><span>{a.team} · {a.languages.join(", ")}</span></td>
                <td>{can("agent:manage") ? <select className="select" aria-label={`Availability for ${a.name}`} value={a.availability} onChange={(e) => setAvail(a.id, e.target.value)}>{STATES.map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</select> : <Badge value={a.availability} />}</td>
                <td style={{ minWidth: 150 }}><div className="small num" style={{ marginBottom: 4 }}>{a.openCases}/{a.maxOpenCases} cases{a.dueCallbacks ? ` · ${a.dueCallbacks} callbacks due` : ""}</div><div className={`meter ${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}`}><i style={{ width: `${Math.min(pct, 100)}%` }} /></div></td>
                <td className="num">{a.handledToday}</td><td className="num">{a.avgResolutionMin === null ? "—" : `${a.avgResolutionMin} min`}</td><td className="num">{a.slaHitPercent === null ? "—" : `${a.slaHitPercent}%`}</td>
              </tr>;
            })}
          </tbody></table></div>
        )}
      </Panel>
      {adding && <Modal title="Add agent" onClose={() => setAdding(false)} footer={<><button className="btn" onClick={() => setAdding(false)}>Cancel</button><button className="btn primary" disabled={!form.name.trim()} onClick={add}>Add agent</button></>}>
        <label className="field">Name<input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="field">Team<input className="input" value={form.team} onChange={(e) => setForm({ ...form, team: e.target.value })} /></label>
        <label className="field">Languages<input className="input" value={form.languages} onChange={(e) => setForm({ ...form, languages: e.target.value })} /></label>
        <label className="field">Skills<input className="input" value={form.skills} onChange={(e) => setForm({ ...form, skills: e.target.value })} /><small>e.g. GENERAL_SUPPORT, APP_SUPPORT, SECURITY_CONCERN</small></label>
        <label className="field">Max open cases<input className="input" type="number" min={1} max={100} value={form.max_open_cases} onChange={(e) => setForm({ ...form, max_open_cases: Number(e.target.value) })} /></label>
        <p className="small muted" style={{ margin: 0 }}>New agents start Offline. To link a sign-in account, use the admin CLI with --agent.</p>
      </Modal>}
    </>
  );
}
