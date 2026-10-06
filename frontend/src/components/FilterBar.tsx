import { FunnelSimple, X } from "@phosphor-icons/react";
import { useDashboard } from "../hooks/DashboardContext";

export function FilterBar() {
  const { filters, setFilters, snapshot } = useDashboard();
  if (!snapshot) return <div className="ops-filter-skeleton" />;
  const update = (key: keyof typeof filters, value: string) => setFilters({ ...filters, [key]: value });
  const reset = () => setFilters({ range: "30D", campaign: "ALL", language: "ALL", region: "ALL" });
  const hasFilters = filters.campaign !== "ALL" || filters.language !== "ALL" || filters.region !== "ALL";
  return <div className="ops-filter-bar"><span className="ops-filter-label"><FunnelSimple size={15} />FILTERS</span>
    <label><span>Date range</span><select value={filters.range} onChange={(event) => update("range", event.target.value)}><option value="7D">Last 7 days</option><option value="30D">Last 30 days</option><option value="60D">Last 60 days</option><option value="ALL">All time</option></select></label>
    <label><span>Campaign</span><select value={filters.campaign} onChange={(event) => update("campaign", event.target.value)}><option value="ALL">All campaigns</option>{snapshot.campaigns.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    <label><span>Language</span><select value={filters.language} onChange={(event) => update("language", event.target.value)}><option value="ALL">All languages</option>{[...new Set(snapshot.calls.map((call) => call.language))].sort().map((value) => <option key={value}>{value}</option>)}</select></label>
    <label><span>Region</span><select value={filters.region} onChange={(event) => update("region", event.target.value)}><option value="ALL">All regions</option>{[...new Set(snapshot.calls.map((call) => call.region))].sort().map((value) => <option key={value}>{value}</option>)}</select></label>
    {hasFilters && <button className="ops-reset-button" onClick={reset}><X size={13} />Clear</button>}
    <span className="ops-filter-time">All times in IST</span>
  </div>;
}
