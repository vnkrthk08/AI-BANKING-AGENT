import { useState } from "react";
import { Plus, UsersThree } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../auth/AuthContext";
import { apiJson } from "../services/http";
import {
  Badge,
  Empty,
  ErrorNote,
  Kpi,
  Loading,
  Modal,
  PageHead,
  Panel,
  titleCase,
  useToast,
} from "../components/ui";

interface Agent {
  id: string;
  name: string;
  team: string;
  languages: string[];
  skills: string[];
  availability: string;
  openCases: number;
  overdueCases: number;
  dueCallbacks: number;
  maxOpenCases: number;
  handledToday: number;
  avgResolutionMin: number | null;
  slaHitPercent: number | null;
  maskedPhone: string | null;
  userId: string | null;
}

const STATES = ["AVAILABLE", "BUSY", "ON_CALL", "BREAK", "OFFLINE"];

const AVAIL_COLORS: Record<string, string> = {
  AVAILABLE: "var(--ok)",
  ON_CALL: "var(--brand-2)",
  BUSY: "var(--warn)",
  BREAK: "var(--warn)",
  OFFLINE: "var(--text-4)",
};

export function TeamPage() {
  const { can, user } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useApi<{ agents: Agent[] }>("/api/agents");
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    name: "",
    team: "Digital support",
    languages: "English, Hindi",
    skills: "GENERAL_SUPPORT, APP_SUPPORT",
    max_open_cases: 12,
  });

  const agents = data?.agents ?? [];

  const setAvail = async (id: string, availability: string) => {
    try {
      await apiJson(`/api/agents/${id}/status`, { method: "PATCH", body: JSON.stringify({ availability }) });
      toast.ok("Status updated", `Agent availability set to ${titleCase(availability)}.`);
      void reload();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Update failed";
      setErr(msg);
      toast.bad("Status update failed", msg);
    }
  };

  const add = async () => {
    try {
      await apiJson("/api/agents", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          languages: form.languages.split(",").map((s) => s.trim()),
          skills: form.skills.split(",").map((s) => s.trim()),
        }),
      });
      toast.ok("Agent created", `${form.name} added to team roster.`);
      setAdding(false);
      void reload();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Could not add agent";
      setErr(msg);
      toast.bad("Failed to add agent", msg);
    }
  };

  const me = agents.find((a) => a.id === user?.agent_id);
  const availableCount = agents.filter((a) => a.availability === "AVAILABLE").length;
  const totalCases = agents.reduce((s, a) => s + a.openCases, 0);
  const overdueCount = agents.reduce((s, a) => s + a.overdueCases, 0);

  return (
    <>
      <PageHead
        title="Team"
        sub="Who is available, cases currently owned, and workload capacity across operational teams."
        actions={
          can("agent:manage") && (
            <button className="btn primary" onClick={() => setAdding(true)}>
              <Plus size={16} /> Add agent
            </button>
          )
        }
      />

      {err && <ErrorNote error={err} />}
      {error && <ErrorNote error={error} onRetry={reload} />}

      {me && (
        <Panel title="My availability status" sub="New escalations are only routed to you while your status is set to Available">
          <div className="seg">
            {STATES.map((s) => (
              <button key={s} className={me.availability === s ? "on" : ""} onClick={() => setAvail(me.id, s)}>
                <span
                  style={{
                    display: "inline-block",
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: AVAIL_COLORS[s],
                    marginRight: 6,
                  }}
                />
                {titleCase(s)}
              </button>
            ))}
          </div>
        </Panel>
      )}

      {me && <div style={{ height: 16 }} />}

      {data && (
        <div className="kpis">
          <Kpi label="Total agents" value={agents.length} hint="Active roster" />
          <Kpi
            label="Available now"
            value={availableCount}
            hint={`${Math.round((100 * availableCount) / Math.max(1, agents.length))}% of team`}
          />
          <Kpi label="Active cases owned" value={totalCases} hint="Currently in-flight" />
          <Kpi
            label="Overdue cases"
            value={overdueCount}
            hint={overdueCount ? "Past SLA deadline" : "All within SLA"}
            tone={overdueCount ? "alert" : undefined}
          />
        </div>
      )}

      <Panel flush>
        {loading ? (
          <Loading />
        ) : !agents.length ? (
          <Empty
            icon={<UsersThree size={24} />}
            title="No agents registered yet"
            text="Add operators who handle customer escalations and phone callbacks. Link them to user accounts for assigned queues."
          />
        ) : (
          <div className="table-wrap">
            <table className="t">
              <thead>
                <tr>
                  <th>Agent & Team</th>
                  <th>Availability</th>
                  <th>Workload Capacity</th>
                  <th>Handled Today</th>
                  <th>Avg Resolution</th>
                  <th>SLA Adherence</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((a) => {
                  const pct = Math.round((100 * a.openCases) / Math.max(a.maxOpenCases, 1));
                  const dotColor = AVAIL_COLORS[a.availability] ?? "var(--text-4)";
                  return (
                    <tr key={a.id}>
                      <td className="primary-cell">
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span
                            title={a.availability}
                            style={{
                              width: 8,
                              height: 8,
                              borderRadius: "50%",
                              background: dotColor,
                              boxShadow: a.availability === "AVAILABLE" ? "0 0 0 2px var(--ok-soft)" : undefined,
                              flexShrink: 0,
                            }}
                          />
                          <b>{a.name}</b>
                        </div>
                        <span style={{ marginLeft: 16 }}>
                          {a.team} · {a.languages.join(", ")}
                        </span>
                      </td>
                      <td>
                        {can("agent:manage") ? (
                          <select
                            className="select"
                            aria-label={`Availability for ${a.name}`}
                            value={a.availability}
                            onChange={(e) => setAvail(a.id, e.target.value)}
                          >
                            {STATES.map((s) => (
                              <option key={s} value={s}>
                                {titleCase(s)}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <Badge value={a.availability} />
                        )}
                      </td>
                      <td style={{ minWidth: 160 }}>
                        <div className="small num" style={{ marginBottom: 4, display: "flex", justifyContent: "space-between" }}>
                          <span>
                            {a.openCases} / {a.maxOpenCases} cases
                          </span>
                          <span className="muted">{pct}%</span>
                        </div>
                        <div className={`meter ${pct >= 90 ? "bad" : pct >= 70 ? "warn" : ""}`} style={{ height: 6 }}>
                          <i style={{ width: `${Math.min(pct, 100)}%` }} />
                        </div>
                        {a.dueCallbacks > 0 && (
                          <small style={{ color: "var(--warn)", display: "block", marginTop: 2 }}>
                            {a.dueCallbacks} callback{a.dueCallbacks > 1 ? "s" : ""} due
                          </small>
                        )}
                      </td>
                      <td className="num">{a.handledToday}</td>
                      <td className="num">{a.avgResolutionMin === null ? "—" : `${a.avgResolutionMin} min`}</td>
                      <td className="num">
                        {a.slaHitPercent === null ? (
                          "—"
                        ) : (
                          <span style={{ color: a.slaHitPercent >= 90 ? "var(--ok)" : "var(--warn)", fontWeight: 600 }}>
                            {a.slaHitPercent}%
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {adding && (
        <Modal
          title="Add agent to team"
          onClose={() => setAdding(false)}
          footer={
            <>
              <button className="btn" onClick={() => setAdding(false)}>
                Cancel
              </button>
              <button className="btn primary" disabled={!form.name.trim()} onClick={add}>
                Add agent
              </button>
            </>
          }
        >
          <label className="field">
            Full name
            <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label className="field">
            Team name
            <input className="input" value={form.team} onChange={(e) => setForm({ ...form, team: e.target.value })} />
          </label>
          <label className="field">
            Languages spoken
            <input
              className="input"
              value={form.languages}
              onChange={(e) => setForm({ ...form, languages: e.target.value })}
            />
            <small>Comma-separated list (e.g. English, Hindi, Tamil)</small>
          </label>
          <label className="field">
            Skill badges
            <input className="input" value={form.skills} onChange={(e) => setForm({ ...form, skills: e.target.value })} />
            <small>e.g. GENERAL_SUPPORT, APP_SUPPORT, SECURITY_CONCERN</small>
          </label>
          <label className="field">
            Maximum concurrent open cases
            <input
              className="input"
              type="number"
              min={1}
              max={100}
              value={form.max_open_cases}
              onChange={(e) => setForm({ ...form, max_open_cases: Number(e.target.value) })}
            />
          </label>
          <p className="small muted" style={{ margin: 0 }}>
            New team members initialize in Offline status.
          </p>
        </Modal>
      )}
    </>
  );
}
