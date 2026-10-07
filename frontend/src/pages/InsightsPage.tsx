import { useNavigate } from "react-router-dom";
import { DrillChart, LanguageBars, RankingBars, DailyTrend, HourlyHeatmap } from "../charts/OperationsCharts";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { Panel } from "../components/Panel";
import { useDashboard } from "../hooks/DashboardContext";
import { filterCalls } from "../services/selectors";

export function InsightsPage() {
  const { snapshot, loading, error, refresh, filters } = useDashboard();
  const navigate = useNavigate();

  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;

  const calls = filterCalls(snapshot.calls, filters);
  const drill = () => navigate("/call-log");

  const map = new Map<string, number>();
  calls.forEach((c) => {
    if (c.issueCategory) map.set(c.issueCategory, (map.get(c.issueCategory) || 0) + 1);
  });
  const issues = [...map].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);

  const features = new Map<string, number>();
  calls.forEach((c) => c.featureInterest.forEach((f) => features.set(f, (features.get(f) || 0) + 1)));
  const ranking = [...features].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);

  const closedCount = calls.filter((c) => c.disposition === "CLOSED").length;
  const escalatedCount = calls.filter((c) => c.disposition === "ESCALATED").length;
  const callbacksCount = calls.filter((c) => c.disposition === "CALLBACK_SCHEDULED").length;

  return (
    <>
      <PageHeading
        eyebrow="PERFORMANCE INTELLIGENCE"
        title="Insights"
        description="Explore service demand, customer intent distribution, and operational quality signals."
      />
      <div className="ops-insight-grid">
        <Panel title="Top customer issues" subtitle="Issue categories in selected calls">
          <DrillChart onDrill={drill}>
            <RankingBars data={issues.slice(0, 6)} color="#d97706" />
          </DrillChart>
        </Panel>

        <Panel title="Feature interest" subtitle="Recorded feature affinity signals">
          <DrillChart onDrill={drill}>
            <RankingBars data={ranking.slice(0, 6)} color="#0d9488" />
          </DrillChart>
        </Panel>

        <Panel title="Close rate by language" subtitle="Closed calls ÷ dialed calls">
          <DrillChart onDrill={drill}>
            <LanguageBars calls={calls} />
          </DrillChart>
        </Panel>

        <Panel title="Daily trend" subtitle="Dialed vs. closed · latest 14 days">
          <DrillChart onDrill={drill}>
            <DailyTrend calls={calls} />
          </DrillChart>
        </Panel>

        <Panel title="Call hour distribution" subtitle="IST · Permitted contact window (09:00 - 21:00)">
          <DrillChart onDrill={drill}>
            <HourlyHeatmap calls={calls} />
          </DrillChart>
        </Panel>

        <section className="ops-summary-panel">
          <div className="ops-summary-top">
            <span className="ops-ai-mark">AI</span>
            <span>QUALITY &amp; RESOLUTION SIGNALS</span>
          </div>
          <h2>Resolution mix</h2>
          <p>
            <strong>{closedCount.toLocaleString("en-IN")}</strong> closed ·{" "}
            <strong>{escalatedCount.toLocaleString("en-IN")}</strong> escalated ·{" "}
            <strong>{callbacksCount.toLocaleString("en-IN")}</strong> callbacks in the selected period.
          </p>
          <small>
            Intent distribution and feature affinity are derived from real-time NLU conversation turn analysis.
          </small>
        </section>
      </div>
    </>
  );
}
