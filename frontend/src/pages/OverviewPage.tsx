import { Link } from "react-router-dom";
import { ChartBar, Headset } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { StatusLine } from "../components/AppShell";
import { Badge, Empty, ErrorNote, Kpi, Loading, PageHead, Panel, fmtRelative, outcomeLabel, titleCase } from "../components/ui";
import { useAuth } from "../auth/AuthContext";

interface Overview {
  today: { calls: number; connected: number; resolvedByAi: number; escalated: number; callbacksBooked: number; noResponse: number };
  liveCalls: number;
  queues: { openCases: number; unassignedCases: number; slaBreached: number; urgentCases: number; scheduledCallbacks: number; dueCallbacks: number; callbacksNeedingTime: number };
  team: { total: number; available: number; onCall: number };
  campaigns: { active: number };
  notifications: { failedDeliveries: number };
  dailyVolume: { date: string; calls: number; connected: number; resolved: number }[];
  outcomes14d: Record<string, number>;
}
interface CaseRow { id: string; priority: string; status: string; category: string; customer_ref: string; sla_due_at: string | null; sla_breached: boolean; assigned_agent_name: string | null }

export function OverviewPage() {
  const { can } = useAuth();
  const { data, error, loading, reload } = useApi<Overview>("/api/reports/overview");
  const cases = useApi<CaseRow[]>(can("case:read") ? "/api/escalations" : null);
  if (loading && !data) return <><PageHead title="Overview" /><Loading rows={6} /></>;
  if (error || !data) return <><PageHead title="Overview" /><ErrorNote error={error ?? "No data"} onRetry={reload} /></>;
  const t = data.today;
  const max = Math.max(1, ...data.dailyVolume.map((d) => d.calls));
  const outcomes = Object.entries(data.outcomes14d).sort((a, b) => b[1] - a[1]);
  const outcomeTotal = outcomes.reduce((s, [, n]) => s + n, 0);
  const attention = (cases.data ?? []).filter((c) => !["RESOLVED", "CLOSED", "CANCELLED"].includes(c.status))
    .sort((a, b) => Number(b.sla_breached) - Number(a.sla_breached) || (a.sla_due_at ?? "").localeCompare(b.sla_due_at ?? "")).slice(0, 6);
  const q = data.queues;
  return (
    <>
      <PageHead title="Overview" sub="Today's AI calling, queues awaiting people, and system readiness." actions={<><StatusLine /></>} />
      {(q.slaBreached > 0 || q.dueCallbacks > 0 || data.notifications.failedDeliveries > 0) && (
        <div className="alert warn" role="status"><span className="grow">
          {[q.slaBreached && `${q.slaBreached} case${q.slaBreached > 1 ? "s" : ""} past SLA`, q.dueCallbacks && `${q.dueCallbacks} callback${q.dueCallbacks > 1 ? "s" : ""} due now`, data.notifications.failedDeliveries && `${data.notifications.failedDeliveries} failed notification deliveries`].filter(Boolean).join(" · ")}
        </span><Link className="btn sm" to="/work">Open Work Queue</Link></div>
      )}
      <div className="kpis">
        <Kpi label="Calls today" value={t.calls} hint={`${t.connected} connected`} />
        <Kpi label="Resolved by AI" value={t.resolvedByAi} hint={t.calls ? `${Math.round((100 * t.resolvedByAi) / t.calls)}% of calls` : "No calls yet"} />
        <Kpi label="Escalated to people" value={t.escalated} hint={`${t.callbacksBooked} callbacks booked`} />
        <Kpi label="Open cases" value={q.openCases} hint={`${q.unassignedCases} unassigned`} tone={q.slaBreached ? "alert" : undefined} />
        <Kpi label="Callbacks due" value={q.dueCallbacks} hint={`${q.scheduledCallbacks} scheduled · ${q.callbacksNeedingTime} need a time`} tone={q.dueCallbacks ? "warn" : undefined} />
        <Kpi label="Agents available" value={`${data.team.available}/${data.team.total}`} hint={`${data.team.onCall} on a call`} />
      </div>
      <div className="grid cols-3">
        <Panel title="Call volume" sub="Last 14 days · IST">
          {data.dailyVolume.every((d) => d.calls === 0) ? (
            <Empty icon={<ChartBar size={20} />} title="No calls in the last 14 days" text="Volume appears here once Voice Studio sessions or campaign calls take place." action={can("voice:operate") ? <Link className="btn primary" to="/test-console"><Headset size={16} /> Open Voice Studio</Link> : undefined} />
          ) : (
            <>
              <div className="bars" role="img" aria-label="Daily calls, with resolved calls highlighted">
                {data.dailyVolume.map((d) => (
                  <div className="bar" key={d.date} title={`${d.date}: ${d.calls} calls, ${d.resolved} resolved by AI`}>
                    <i style={{ height: `${(d.calls / max) * 100}%` }}><b style={{ height: d.calls ? `${(d.resolved / d.calls) * 100}%` : 0 }} /></i>
                  </div>
                ))}
              </div>
              <div className="bar-x">{data.dailyVolume.map((d, i) => <span key={d.date}>{i % 2 === 0 ? d.date.slice(8) : ""}</span>)}</div>
              <p className="small muted" style={{ margin: "10px 0 0" }}>Bar height: calls. Dark fill: resolved by AI.</p>
            </>
          )}
        </Panel>
        <Panel title="Outcomes" sub="Last 14 days">
          {outcomeTotal === 0 ? <p className="muted" style={{ margin: 0 }}>No completed calls yet.</p> : outcomes.map(([k, n]) => (
            <div key={k}>
              <div className="legend-row"><span>{outcomeLabel(k)}</span><span className="num muted">{n} · {Math.round((100 * n) / outcomeTotal)}%</span></div>
              <div className="meter"><i style={{ width: `${(100 * n) / outcomeTotal}%` }} /></div>
            </div>
          ))}
        </Panel>
      </div>
      <div style={{ height: 16 }} />
      {can("case:read") && (
        <Panel title="Needs attention" sub="Open cases ordered by SLA risk" actions={<Link className="btn sm" to="/work">View all</Link>} flush>
          {cases.loading ? <Loading /> : attention.length === 0 ? <Empty title="No open cases" text="Escalations raised by Subbu appear here with their SLA." /> : (
            <div className="rows">{attention.map((c) => (
              <Link to={`/work?case=${c.id}`} key={c.id} className="row-item" style={{ color: "inherit" }}>
                <Badge value={c.priority?.toUpperCase()} />
                <div className="grow"><b>{titleCase(c.category)} · {c.customer_ref}</b><span>{c.id} · {c.assigned_agent_name ?? "Unassigned"}</span></div>
                <span className={c.sla_breached ? "badge bad" : "badge plain"}>SLA {fmtRelative(c.sla_due_at)}</span>
              </Link>
            ))}</div>
          )}
        </Panel>
      )}
    </>
  );
}
