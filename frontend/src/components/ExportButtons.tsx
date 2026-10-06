import { ArrowLineDown, FileCsv, FilePdf, Table } from "@phosphor-icons/react";
import { hasAction } from "../config/permissions";
import { useDashboard } from "../hooks/DashboardContext";
import { dashboardApi } from "../services/dashboardApi";
import type { ExportRow } from "../services/exporters";
import type { Role } from "../types";

export function ExportButtons({ role, rows, name = "kural-call-sheet", title = "Call operations report" }: { role: Role; rows: ExportRow[]; name?: string; title?: string }) {
  const { mode, refresh } = useDashboard();
  if (!hasAction(role, "export")) return null;
  async function perform(kind: "CSV" | "XLSX" | "PDF") {
    await dashboardApi.recordAudit(`EXPORT_${kind}`, "REPORT", name, role, `${rows.length} masked rows exported`);
    await refresh();
    const filename = `${name}-${new Date().toISOString().slice(0, 10)}`;
    const exporters = await import("../services/exporters");
    if (kind === "CSV") exporters.downloadCsv(rows, `${filename}.csv`);
    if (kind === "XLSX") exporters.downloadXlsx(rows, `${filename}.xlsx`);
    if (kind === "PDF") exporters.downloadPdf(rows, `${filename}.pdf`, title);
  }
  return <div className="ops-export-group" aria-label="Export options"><button className="ops-button ops-button-secondary" onClick={() => void perform("XLSX")}><Table size={15} />Download sheet</button><details className="ops-export-menu"><summary aria-label="More export formats"><ArrowLineDown size={15} /></summary><div><button onClick={() => void perform("CSV")}><FileCsv size={15} />CSV</button><button onClick={() => void perform("PDF")}><FilePdf size={15} />PDF</button></div></details><span className="ops-export-audit">{mode === "mock" ? "Export view is audit-logged locally" : "Export is audit-logged"}</span></div>;
}
