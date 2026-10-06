import { CheckSquareOffset, Columns, MagnifyingGlass, SlidersHorizontal } from "@phosphor-icons/react";
import { createColumnHelper } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { ColumnDef } from "@tanstack/react-table";
import { CallDetailDrawer } from "../components/CallDetailDrawer";
import { DataTable } from "../components/DataTable";
import { ExportButtons } from "../components/ExportButtons";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { StatusPill } from "../components/StatusPill";
import { dashboardApi } from "../services/dashboardApi";
import { filterCalls, formatDateTime, formatDuration } from "../services/selectors";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import type { CallRecord } from "../types";

const helper = createColumnHelper<CallRecord>();
const allColumns: Array<{ id: string; label: string; column: ColumnDef<CallRecord, any> }> = [
  { id: "id", label: "Call ID", column: helper.accessor("id", { header: "CALL ID", cell: (info) => <span className="ops-mono">{info.getValue()}</span> }) },
  { id: "time", label: "Time", column: helper.accessor("startedAt", { header: "TIME · IST", cell: (info) => <span className="ops-mono">{formatDateTime(info.getValue())}</span> }) },
  { id: "customer", label: "Customer", column: helper.accessor("customerRef", { header: "MASKED CUSTOMER", cell: (info) => <span>{info.getValue()}<small className="ops-cell-sub">{info.row.original.maskedPhone}</small></span> }) },
  { id: "campaign", label: "Campaign", column: helper.accessor("campaignName", { header: "CAMPAIGN" }) },
  { id: "language", label: "Language", column: helper.accessor("language", { header: "LANGUAGE" }) },
  { id: "duration", label: "Duration", column: helper.accessor("durationSec", { header: "DURATION", cell: (info) => formatDuration(info.getValue()) }) },
  { id: "disposition", label: "Disposition", column: helper.accessor((row) => row.disposition ?? row.status, { id: "disposition", header: "DISPOSITION", cell: (info) => <StatusPill value={info.getValue()} /> }) },
  { id: "app", label: "App status", column: helper.accessor((row) => row.appInstalled ? row.appUpdated ? "Installed · updated" : "Installed · update due" : "Not installed", { id: "appStatus", header: "APP STATUS" }) },
  { id: "sentiment", label: "Sentiment", column: helper.accessor("sentiment", { header: "SENTIMENT", cell: (info) => <span className={info.getValue() < 0 ? "ops-negative-value" : "ops-positive-value"}>{info.getValue() >= 0 ? "+" : ""}{info.getValue().toFixed(2)}</span> }) },
  { id: "issue", label: "Issue", column: helper.accessor("issueCategory", { header: "ISSUE CATEGORY", cell: (info) => info.getValue() ?? "—" }) },
  { id: "callback", label: "Callback", column: helper.accessor((row) => row.callbackId ? "SCHEDULED" : "NONE", { id: "callback", header: "CALLBACK", cell: (info) => <StatusPill value={info.getValue()} /> }) },
  { id: "escalation", label: "Escalation", column: helper.accessor((row) => row.escalationId ? "ESCALATED" : "NONE", { id: "escalation", header: "ESCALATION", cell: (info) => <StatusPill value={info.getValue()} /> }) },
  { id: "flags", label: "Compliance flags", column: helper.accessor((row) => row.complianceFlags.join(", ") || "CLEAR", { id: "flags", header: "COMPLIANCE", cell: (info) => info.getValue() === "CLEAR" ? <span className="ops-positive-value">Clear</span> : <StatusPill value="BLOCKED" /> }) },
];
const defaultColumns = ["id", "time", "customer", "campaign", "language", "duration", "disposition", "app", "sentiment", "issue", "callback", "escalation", "flags"];
type ViewPreset = "ALL" | "CALLBACK_SCHEDULED" | "ESCALATED" | "DND" | "NOT_INTERESTED";

export function CallLogPage() {
  const { snapshot, loading, error, refresh, filters } = useDashboard();
  const [role] = useRole();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedCall, setSelectedCall] = useState<CallRecord | null>(null);
  const [query, setQuery] = useState(searchParams.get("query") ?? "");
  const [preset, setPreset] = useState<ViewPreset>((searchParams.get("disposition") as ViewPreset) ?? "ALL");
  const [visible, setVisible] = useState<string[]>(defaultColumns);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const columns = useMemo(() => [helper.display({ id: "select", header: "", cell: (info) => <input aria-label={`Select ${info.row.original.id}`} type="checkbox" checked={selectedIds.includes(info.row.original.id)} onClick={(event) => event.stopPropagation()} onChange={(event) => setSelectedIds((current) => event.target.checked ? [...current, info.row.original.id] : current.filter((id) => id !== info.row.original.id))} /> }), ...allColumns.filter((item) => visible.includes(item.id)).map((item) => item.column)], [selectedIds, visible]);
  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  let calls = filterCalls(snapshot.calls, filters, preset === "ALL" ? undefined : preset);
  const search = query.trim().toLowerCase();
  if (search) calls = calls.filter((call) => [call.id, call.customerRef, call.maskedPhone, call.campaignName, call.issueCategory ?? ""].some((value) => value.toLowerCase().includes(search)));
  const exportRows = calls.map((call) => ({ callId: call.id, timestampIst: formatDateTime(call.startedAt), customerRef: call.customerRef, maskedPhone: call.maskedPhone, campaign: call.campaignName, language: call.language, duration: formatDuration(call.durationSec), disposition: call.disposition ?? call.status, appStatus: call.appInstalled ? call.appUpdated ? "Installed and updated" : "Installed; update due" : "Not installed", sentiment: call.sentiment, issue: call.issueCategory ?? "", callback: call.callbackId ? "Requested" : "None", escalation: call.escalationId ? "Escalated" : "None", complianceFlags: call.complianceFlags.join("; ") || "Clear" }));
  function choosePreset(value: ViewPreset) { setPreset(value); if (value === "ALL") setSearchParams({}); else setSearchParams({ disposition: value }); }
  function toggleColumn(id: string) { setVisible((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]); }
  async function reviewSelected() {
    await Promise.all(selectedIds.map((id) => dashboardApi.recordAudit("BULK_REVIEW", "CALL", id, role, "Selected call reviewed from call log")));
    setNotice(`${selectedIds.length} call records marked reviewed in the demo audit feed.`); setSelectedIds([]);
  }
  return <>
    <PageHeading eyebrow="SHARED OPERATIONS DATA" title="Call log" description="Sortable call records shared across campaigns, agent work and compliance views." actions={<ExportButtons role={role} rows={exportRows} name="call-log" title="KURAL call log" />} />
    {notice && <div className="ops-notice-banner" role="status">{notice}<button onClick={() => setNotice("")}>Dismiss</button></div>}
    <div className="ops-table-toolbar"><label className="ops-inline-search"><MagnifyingGlass size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search call ID, customer ref or campaign" /></label>
      <label className="ops-view-select"><SlidersHorizontal size={15} /><select value={preset} onChange={(event) => choosePreset(event.target.value as ViewPreset)}><option value="ALL">All calls</option><option value="CALLBACK_SCHEDULED">Callbacks</option><option value="ESCALATED">Escalations</option><option value="DND">DND suppressed</option><option value="NOT_INTERESTED">Not interested</option></select></label>
      <details className="ops-column-picker"><summary><Columns size={15} />Columns</summary><div>{allColumns.map((item) => <label key={item.id}><input type="checkbox" checked={visible.includes(item.id)} onChange={() => toggleColumn(item.id)} />{item.label}</label>)}</div></details>
      {selectedIds.length > 0 && <button className="ops-button ops-button-secondary" onClick={() => void reviewSelected()}><CheckSquareOffset size={15} />Review {selectedIds.length} selected</button>}
      <span className="ops-record-count">{calls.length.toLocaleString("en-IN")} records</span>
    </div>
    <section className="ops-panel ops-call-log-panel"><div className="ops-panel-body"><DataTable data={calls} columns={columns} rowId={(call) => call.id} onRowClick={setSelectedCall} pageSize={15} emptyTitle="No calls match" emptyText="Try another saved view or adjust the global filters." /></div></section>
    <div className="ops-table-note">Customer numbers are masked. Opening a call detail creates a local demo transcript-view audit event.</div>
    {selectedCall && <CallDetailDrawer call={selectedCall} role={role} onClose={() => setSelectedCall(null)} />}
  </>;
}
