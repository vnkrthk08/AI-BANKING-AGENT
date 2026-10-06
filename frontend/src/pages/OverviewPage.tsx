import { ArrowRight, ArrowUpRight, CheckCircle, CurrencyInr, Phone, Timer, UsersThree, WarningCircle } from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";
import { DailyTrend, DrillChart, HourlyHeatmap, OutcomeDonut, OutcomeFunnel, RankingBars } from "../charts/OperationsCharts";
import { KpiCard } from "../components/KpiCard";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { Panel } from "../components/Panel";
import { useDashboard } from "../hooks/DashboardContext";
import { filterCalls, formatInr, previousPeriodCalls, summarizeCalls } from "../services/selectors";

function delta(current: number, previous: number): number {
  return previous ? (current - previous) / previous * 100 : 0;
}

export function OverviewPage() {
  const { snapshot, loading, error, refresh, filters } = useDashboard();
  const navigate = useNavigate();
  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  const calls = filterCalls(snapshot.calls, filters);
  const prior = summarizeCalls(previousPeriodCalls(snapshot.calls, filters));
  const current = summarizeCalls(calls);
  const connected = calls.filter((call) => call.connected);
  const installed = calls.filter((call) => call.appInstalled);
  const updated = installed.filter((call) => call.appUpdated);
  const resolvedAi = calls.filter((call) => call.resolutionMode === "AI");
  const resolvedHuman = calls.filter((call) => call.resolutionMode === "HUMAN" && call.disposition === "CLOSED");
  const interest = new Map<string, number>();
  const issueCounts = new Map<string, number>();
  calls.forEach((call) => { call.featureInterest.forEach((item) => interest.set(item, (interest.get(item) ?? 0) + 1)); if (call.issueCategory) issueCounts.set(call.issueCategory, (issueCounts.get(call.issueCategory) ?? 0) + 1); });
  const rankings = (map: Map<string, number>) => [...map].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value).slice(0, 5);
  const drill = () => navigate("/call-log");
  const live = snapshot.calls.filter((call) => call.status === "IN_PROGRESS").length;
  const queueDepth = snapshot.callbacks.filter((callback) => callback.status !== "COMPLETED").length;
  const available = snapshot.agents.filter((agent) => agent.availability === "AVAILABLE").length;
  const funnel = ["Dialed", "Connected", "Consented", "Completed", "Closed"];

  return <>
    <PageHeading eyebrow="OPERATIONS · INDIA" title="Executive overview" description="A reconciled view of outbound service calls, customer outcomes and follow-up demand." actions={<button className="ops-button ops-button-secondary" onClick={drill}>View call log <ArrowRight size={15} /></button>} />
    <div className="ops-live-strip"><span className="ops-live-strip-title"><i />LIVE OPERATIONS</span><span><Phone size={15} /><strong>{live}</strong> calls in progress</span><span><UsersThree size={16} /><strong>{available}</strong> agents available</span><span><Timer size={15} /><strong>{queueDepth}</strong> open follow-ups</span><span className="ops-strip-context">Updates from synthetic records</span></div>
    <div className="ops-section-label">PERFORMANCE SNAPSHOT <span>{calls.length.toLocaleString("en-IN")} calls in selected period</span></div>
    <div className="ops-kpi-grid">
      <KpiCard label="Calls dialed" value={current.callsDialed.toLocaleString("en-IN")} delta={delta(current.callsDialed, prior.callsDialed)} icon={<Phone size={17} />} />
      <KpiCard label="Answer rate" value={`${(current.answerRate * 100).toFixed(1)}%`} delta={delta(current.answerRate, prior.answerRate)} icon={<CheckCircle size={17} />} accent="blue" />
      <KpiCard label="Closed" value={current.closed.toLocaleString("en-IN")} delta={delta(current.closed, prior.closed)} icon={<CheckCircle size={17} />} accent="green" />
      <KpiCard label="Callbacks" value={current.callbacks.toLocaleString("en-IN")} delta={delta(current.callbacks, prior.callbacks)} icon={<Timer size={17} />} accent="amber" />
      <KpiCard label="Escalated" value={current.escalated.toLocaleString("en-IN")} delta={delta(current.escalated, prior.escalated)} icon={<WarningCircle size={17} />} accent="red" />
      <KpiCard label="Refused / DND" value={current.refusedDnd.toLocaleString("en-IN")} delta={delta(current.refusedDnd, prior.refusedDnd)} icon={<UsersThree size={17} />} accent="gray" />
      <KpiCard label="Avg. call duration" value={`${Math.floor(current.averageDurationSec / 60)}m ${Math.round(current.averageDurationSec % 60)}s`} delta={delta(prior.averageDurationSec, current.averageDurationSec)} icon={<Timer size={17} />} accent="blue" />
      <KpiCard label="Avg. sentiment" value={`${current.averageSentiment >= 0 ? "+" : ""}${current.averageSentiment.toFixed(2)}`} delta={delta(current.averageSentiment, prior.averageSentiment)} icon={<ArrowUpRight size={17} />} accent="green" />
      <KpiCard label="Cost per call" value={formatInr(current.costPerCallInr)} delta={undefined} icon={<CurrencyInr size={17} />} accent="gray" footnote="synthetic cost model" />
      <KpiCard label="Cost per resolved" value={formatInr(current.costPerResolvedInr)} delta={undefined} icon={<CurrencyInr size={17} />} accent="gray" footnote="synthetic cost model" />
    </div>

    <div className="ops-grid ops-grid-2-1">
      <Panel title="Call outcome funnel" subtitle="Progression from dial attempt to successful close" actions={<button className="ops-text-button" onClick={drill}>Open call log <ArrowRight size={13} /></button>}>
        <DrillChart onDrill={drill}><OutcomeFunnel calls={calls} /></DrillChart>
        <div className="ops-funnel-footnote">{funnel.map((label, index) => <span key={label}><i className={`funnel-dot funnel-dot-${index}`} />{label}</span>)}</div>
      </Panel>
      <Panel title="Outcomes" subtitle="Completed call disposition mix" actions={<button className="ops-icon-link" aria-label="Drill into calls" onClick={drill}><ArrowUpRight size={16} /></button>}>
        <DrillChart onDrill={drill}><OutcomeDonut calls={calls} /></DrillChart>
        <div className="ops-outcome-legend">{[["Closed", "#27805f"], ["Callback", "#d29132"], ["Escalated", "#b74747"], ["Not interested", "#8793a4"], ["Busy", "#d3b461"], ["No answer / DND", "#aab3c0"]].map(([label, color]) => <span key={label}><i style={{ background: color }} />{label}</span>)}</div>
      </Panel>
    </div>

    <div className="ops-grid ops-grid-equal">
      <Panel title="Daily call trend" subtitle="Dialed and closed · last 14 days" actions={<button className="ops-icon-link" aria-label="Open filtered calls" onClick={drill}><ArrowUpRight size={16} /></button>}><DrillChart onDrill={drill}><DailyTrend calls={calls} /></DrillChart></Panel>
      <Panel title="Calls by hour" subtitle="Local time · permitted calling window 09:00–21:00 IST" actions={<button className="ops-icon-link" aria-label="Open filtered calls" onClick={drill}><ArrowUpRight size={16} /></button>}><DrillChart onDrill={drill}><HourlyHeatmap calls={calls} /></DrillChart></Panel>
    </div>

    <div className="ops-grid ops-grid-equal">
      <Panel title="AI vs human resolution" subtitle="Closed outcomes classified from synthetic call records" actions={<button className="ops-text-button" onClick={drill}>Explore calls <ArrowRight size={13} /></button>}>
        <div className="ops-resolution-compare">{[{label:"AI resolved",rows:resolvedAi,color:"#12817f"},{label:"Human resolved",rows:resolvedHuman,color:"#607fa5"}].map((group)=><div key={group.label}><span>{group.label}</span><strong>{group.rows.length.toLocaleString("en-IN")}</strong><small>Avg. handling {(group.rows.length ? group.rows.reduce((sum,call)=>sum+call.durationSec,0)/group.rows.length/60 : 0).toFixed(1)} min</small><div className="ops-meter"><i style={{width:`${calls.length ? group.rows.length/calls.length*100 : 0}%`,background:group.color}}/></div><small>{calls.length ? (group.rows.length/calls.length*100).toFixed(1) : "0.0"}% of selected calls</small></div>)}</div>
        <p className="ops-helper">Resolution mode is a generated prototype label; it is not production attribution.</p>
      </Panel>
      <Panel title="Human agent workload" subtitle="Availability and service handling indicators" actions={<button className="ops-text-button" onClick={()=>navigate("/team")}>Open team board <ArrowRight size={13} /></button>}>
        <div className="ops-workload-table"><div className="ops-workload-row ops-workload-head"><span>Agent</span><span>Availability</span><span>Cases</span><span>Avg min</span><span>SLA hit</span></div>{snapshot.agents.slice(0,6).map(agent=>{const load=snapshot.workloads.find(item=>item.agentId===agent.id);return <div className="ops-workload-row" key={agent.id}><strong>{agent.name}</strong><span>{agent.availability.replaceAll("_"," ")}</span><span>{load?.assignedCases??0}</span><span>{agent.avgResolutionMin}</span><span>{agent.slaHitPercent}%</span></div>})}</div>
        <p className="ops-helper">Synthetic roster and handling estimates. No real-time agent system is connected.</p>
      </Panel>
    </div>

    <div className="ops-grid ops-grid-equal">
      <Panel title="App adoption" subtitle="Installation and update status among connected customers" actions={<button className="ops-text-button" onClick={drill}>View records <ArrowRight size={13} /></button>}>
        <DrillChart onDrill={drill}>
          <div className="ops-adoption"><div className="ops-adoption-total"><strong>{connected.length.toLocaleString("en-IN")}</strong><span>connected calls</span></div>
            <div className="ops-adoption-row"><div><span>App installed</span><strong>{installed.length.toLocaleString("en-IN")}</strong></div><div className="ops-meter"><i style={{ width: `${connected.length ? installed.length / connected.length * 100 : 0}%` }} /></div><small>{connected.length ? (installed.length / connected.length * 100).toFixed(0) : 0}% of connected</small></div>
            <div className="ops-adoption-row"><div><span>Updated</span><strong>{updated.length.toLocaleString("en-IN")}</strong></div><div className="ops-meter"><i className="ops-meter-blue" style={{ width: `${installed.length ? updated.length / installed.length * 100 : 0}%` }} /></div><small>{installed.length ? (updated.length / installed.length * 100).toFixed(0) : 0}% of installed</small></div>
            <div className="ops-adoption-row"><div><span>Update available</span><strong>{(installed.length - updated.length).toLocaleString("en-IN")}</strong></div><div className="ops-meter"><i className="ops-meter-amber" style={{ width: `${installed.length ? (installed.length - updated.length) / installed.length * 100 : 0}%` }} /></div><small>follow-up opportunity</small></div>
          </div>
        </DrillChart>
      </Panel>
      <Panel title="Feature interest" subtitle="Customer questions and positive signals" actions={<button className="ops-icon-link" aria-label="View feature interest calls" onClick={drill}><ArrowUpRight size={16} /></button>}><DrillChart onDrill={drill}><RankingBars data={rankings(interest)} color="#5a7baa" /></DrillChart></Panel>
    </div>

    <div className="ops-grid ops-grid-1-1">
      <Panel title="Top reported issues" subtitle="Escalation and callback reasons" actions={<button className="ops-text-button" onClick={() => navigate("/escalations")}>Review cases <ArrowRight size={13} /></button>}><DrillChart onDrill={drill}><RankingBars data={rankings(issueCounts)} color="#c48335" /></DrillChart></Panel>
      <section className="ops-summary-panel"><div className="ops-summary-top"><span className="ops-ai-mark">AI</span><span>WEEKLY SUMMARY <b>· DEMO-GENERATED</b></span></div><h2>What the call records show</h2><p>Within this synthetic sample, {(current.answerRate * 100).toFixed(0)}% of dial attempts connected. {current.callbacks.toLocaleString("en-IN")} callbacks and {current.escalated.toLocaleString("en-IN")} escalations are available for team follow-up. The app update cohort is the clearest service opportunity in this view.</p><small>This is a template calculated from mock metrics. No LLM is connected.</small><button className="ops-text-button" onClick={() => navigate("/insights")}>Explore insights <ArrowRight size={13} /></button></section>
    </div>
  </>;
}
