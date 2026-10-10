import { Link } from "react-router-dom";
import { ChartBar, CheckCircle, Clock, Headset, Warning, WarningOctagon } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { StatusLine } from "../components/AppShell";
import {
  Badge,
  Empty,
  ErrorNote,
  Kpi,
  Loading,
  PageHead,
  Panel,
  RadialRing,
  fmtRelative,
  outcomeLabel,
  titleCase,
} from "../components/ui";
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
interface CaseRow {
  id: string;
  priority: string;
  status: string;
  category: string;
  customer_ref: string;
  sla_due_at: string | null;
  sla_breached: boolean;
  assigned_agent_name: string | null;
}

const OUTCOME_COLORS: Record<string, string> = {
  CLOSED: "var(--ok)",
  RESOLVED: "var(--ok)",
  CALLBACK_SCHEDULED: "var(--brand-2)",
  ESCALATED: "var(--warn)",
  NO_RESPONSE: "var(--bad)",
  ABANDONED: "var(--text-4)",
};

export function OverviewPage() {
  const { can } = useAuth();
  const { data, error, loading, reload } = useApi<Overview>("/api/reports/overview");
  const cases = useApi<CaseRow[]>(can("case:read") ? "/api/escalations" : null);

  if (loading && !data) return <><PageHead title="Overview" /><Loading rows={6} /></>;
  if (error || !data) return <><PageHead title="Overview" /><ErrorNote error={error ?? "No data"} onRetry={reload} /></>;

  const t = data.today;
  const max = Math.max(1, ...data.dailyVolume.map((d) => d.calls));
  const dailyCalls = data.dailyVolume.map((d) => d.calls);
  const dailyResolved = data.dailyVolume.map((d) => d.resolved);
  const totalVolume = dailyCalls.reduce((a, b) => a + b, 0);
  const totalResolved = dailyResolved.reduce((a, b) => a + b, 0);
  const resolvedRate = t.calls > 0 ? Math.round((100 * t.resolvedByAi) / t.calls) : totalVolume > 0 ? Math.round((100 * totalResolved) / totalVolume) : 0;

  const outcomes = Object.entries(data.outcomes14d).sort((a, b) => b[1] - a[1]);
  const outcomeTotal = outcomes.reduce((s, [, n]) => s + n, 0);

  const attention = (cases.data ?? [])
    .filter((c) => !["RESOLVED", "CLOSED", "CANCELLED"].includes(c.status))
    .sort((a, b) => Number(b.sla_breached) - Number(a.sla_breached) || (a.sla_due_at ?? "").localeCompare(b.sla_due_at ?? ""))
    .slice(0, 6);

  const q = data.queues;
  const agentUtilization = data.team.total > 0 ? Math.round((100 * data.team.available) / data.team.total) : 0;

  return (
    <>
      <PageHead
        title="Overview"
        sub="Today's AI calling, queues awaiting people, and real-time operational readiness."
        actions={<StatusLine />}
      />

      {(q.slaBreached > 0 || q.dueCallbacks > 0 || data.notifications.failedDeliveries > 0) && (
        <div className="alert warn" role="status" style={{ borderLeft: "4px solid var(--warn)" }}>
          <Warning size={20} color="var(--warn)" weight="fill" />
          <span className="grow">
            {[
              q.slaBreached && `${q.slaBreached} case${q.slaBreached > 1 ? "s" : ""} past SLA`,
              q.dueCallbacks && `${q.dueCallbacks} callback${q.dueCallbacks > 1 ? "s" : ""} due now`,
              data.notifications.failedDeliveries && `${data.notifications.failedDeliveries} failed notification deliveries`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
          <Link className="btn sm primary" to="/work">
            Open Work Queue
          </Link>
        </div>
      )}

      {/* Modern KPI Strip with Sparklines & Radial Gauges */}
      <div className="kpis">
        <Kpi
          label="Calls today"
          value={t.calls}
          hint={`${t.connected} connected · ${t.calls - t.connected} missed`}
          spark={dailyCalls}
          trend={dailyCalls.length > 1 ? { dir: "up", label: "14d active" } : undefined}
        />
        <Kpi
          label="Resolved by AI"
          value={
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>{t.resolvedByAi}</span>
              <RadialRing percent={resolvedRate} size={36} color="var(--ok)" />
            </div>
          }
          hint={t.calls ? `${resolvedRate}% of today's calls` : "Overall resolution rate"}
          spark={dailyResolved}
        />
        <Kpi
          label="Escalated to staff"
          value={t.escalated}
          hint={`${t.callbacksBooked} callbacks booked`}
          tone={t.escalated > 5 ? "warn" : undefined}
          spark={dailyCalls.map((c, i) => Math.max(0, c - (dailyResolved[i] ?? 0)))}
        />
        <Kpi
          label="Open cases"
          value={q.openCases}
          hint={`${q.unassignedCases} unassigned · ${q.slaBreached} breached`}
          tone={q.slaBreached > 0 ? "alert" : undefined}
          trend={q.slaBreached > 0 ? { dir: "down", label: "SLA alert" } : undefined}
        />
        <Kpi
          label="Callbacks due"
          value={q.dueCallbacks}
          hint={`${q.scheduledCallbacks} scheduled · ${q.callbacksNeedingTime} need slot`}
          tone={q.dueCallbacks > 0 ? "warn" : undefined}
        />
        <Kpi
          label="Agents available"
          value={
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span>{`${data.team.available}/${data.team.total}`}</span>
              <RadialRing percent={agentUtilization} size={36} color="var(--brand-2)" />
            </div>
          }
          hint={`${data.team.onCall} on call · ${data.team.total - data.team.available - data.team.onCall} away`}
        />
      </div>

      {/* Grid: Call Volume & Outcomes */}
      <div className="grid cols-3">
        <Panel
          title="Call volume trend"
          sub={`Last 14 days · ${totalVolume} total calls · ${totalResolved} AI resolved`}
        >
          {data.dailyVolume.every((d) => d.calls === 0) ? (
            <Empty
              icon={<ChartBar size={24} />}
              title="No calls in the last 14 days"
              text="Volume appears here once Voice Studio sessions or campaign calls take place."
              action={
                can("voice:operate") ? (
                  <Link className="btn primary" to="/test-console">
                    <Headset size={16} /> Open Voice Studio
                  </Link>
                ) : undefined
              }
            />
          ) : (
            <>
              <div className="bars" role="img" aria-label="Daily calls, with resolved calls highlighted">
                {data.dailyVolume.map((d) => (
                  <div
                    className="bar"
                    key={d.date}
                    title={`${d.date}: ${d.calls} calls (${d.connected} connected, ${d.resolved} resolved)`}
                  >
                    <i style={{ height: `${(d.calls / max) * 100}%` }}>
                      <b style={{ height: d.calls ? `${(d.resolved / d.calls) * 100}%` : 0 }} />
                    </i>
                  </div>
                ))}
              </div>
              <div className="bar-x">
                {data.dailyVolume.map((d, i) => (
                  <span key={d.date}>{i % 2 === 0 ? d.date.slice(8) : ""}</span>
                ))}
              </div>
              <div style={{ display: "flex", gap: 16, marginTop: 14, fontSize: 12, color: "var(--text-3)" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: "var(--brand-soft)", border: "1px solid var(--line)" }} />
                  Total calls
                </span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 10, height: 10, borderRadius: 2, background: "var(--brand-2)" }} />
                  Resolved by AI
                </span>
              </div>
            </>
          )}
        </Panel>

        <Panel
          title="Call outcomes"
          sub={`14-day distribution · ${outcomeTotal} calls`}
          actions={<RadialRing percent={resolvedRate} size={32} color="var(--ok)" />}
        >
          {outcomeTotal === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              No completed calls yet.
            </p>
          ) : (
            outcomes.map(([k, n]) => {
              const pct = Math.round((100 * n) / outcomeTotal);
              const col = OUTCOME_COLORS[k.toUpperCase()] ?? "var(--brand-2)";
              return (
                <div key={k} style={{ marginBottom: 10 }}>
                  <div className="legend-row">
                    <span style={{ fontWeight: 550 }}>{outcomeLabel(k)}</span>
                    <span className="num muted">
                      {n} · {pct}%
                    </span>
                  </div>
                  <div className="meter" style={{ height: 7 }}>
                    <i style={{ width: `${pct}%`, background: col }} />
                  </div>
                </div>
              );
            })
          )}
        </Panel>
      </div>

      <div style={{ height: 16 }} />

      {/* Needs Attention: Priority-Striped Escalations */}
      {can("case:read") && (
        <Panel
          title="Needs attention"
          sub="Open escalations ordered by SLA breach risk"
          actions={<Link className="btn sm" to="/work">View all in Work Queue</Link>}
          flush
        >
          {cases.loading ? (
            <Loading />
          ) : attention.length === 0 ? (
            <Empty
              icon={<CheckCircle size={24} color="var(--ok)" />}
              title="All clear — no open cases"
              text="Escalations raised by Subbu or banking operators appear here with SLA countdowns."
            />
          ) : (
            <div className="rows">
              {attention.map((c) => {
                const stripeClass =
                  c.priority?.toLowerCase() === "urgent"
                    ? "stripe-urgent"
                    : c.priority?.toLowerCase() === "high"
                    ? "stripe-high"
                    : "stripe-normal";
                return (
                  <Link
                    to={`/work?case=${c.id}`}
                    key={c.id}
                    className={`row-item click ${stripeClass}`}
                    style={{ color: "inherit", textDecoration: "none" }}
                  >
                    <Badge value={c.priority?.toUpperCase()} />
                    <div className="grow">
                      <b style={{ fontSize: 13.5 }}>
                        {titleCase(c.category)} · {c.customer_ref}
                      </b>
                      <span>
                        Case ID: {c.id} · Owner: {c.assigned_agent_name ?? "Unassigned"}
                      </span>
                    </div>
                    {c.sla_breached ? (
                      <span className="badge bad" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                        <WarningOctagon size={13} weight="fill" /> Breached {fmtRelative(c.sla_due_at)}
                      </span>
                    ) : (
                      <span className="badge plain" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                        <Clock size={13} /> Due {fmtRelative(c.sla_due_at)}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          )}
        </Panel>
      )}
    </>
  );
}
