import { zipSync, strToU8 } from "fflate";
import jsPDF from "jspdf";
import autoTable from "jspdf-autotable";

export type ExportRow = Record<string, string | number | boolean | null | undefined>;
const safe = (value: unknown) => {
  const text = String(value ?? "");
  return /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
};
const xml = (value: unknown) => safe(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&apos;");
function columnName(index: number): string {
  let name = "";
  for (let value = index + 1; value > 0; value = Math.floor((value - 1) / 26)) name = String.fromCharCode(65 + ((value - 1) % 26)) + name;
  return name;
}
function sheetCell(value: unknown, column: number, row: number): string {
  const ref = `${columnName(column)}${row}`;
  return typeof value === "number" && Number.isFinite(value) ? `<c r="${ref}"><v>${value}</v></c>` : `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${xml(value)}</t></is></c>`;
}

export function downloadXlsx(rows: ExportRow[], filename: string, sheetName = "Call records"): void {
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const safeSheet = sheetName.replace(/[\\/?*\[\]:]/g, " ").slice(0, 31) || "Sheet1";
  const body = [headers.map((value, col) => sheetCell(value, col, 1)).join(""), ...rows.map((row, index) => headers.map((key, col) => sheetCell(row[key], col, index + 2)).join(""))].map((cells, index) => `<row r="${index + 1}">${cells}</row>`).join("");
  const files = {
    "[Content_Types].xml": strToU8(`<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>`),
    "_rels/.rels": strToU8(`<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`),
    "xl/workbook.xml": strToU8(`<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${xml(safeSheet)}" sheetId="1" r:id="rId1"/></sheets></workbook>`),
    "xl/_rels/workbook.xml.rels": strToU8(`<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>`),
    "xl/worksheets/sheet1.xml": strToU8(`<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${body}</sheetData><autoFilter ref="A1:${columnName(Math.max(0, headers.length - 1))}${rows.length + 1}"/></worksheet>`),
  };
  const blob = new Blob([zipSync(files)], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  saveBlob(blob, filename.endsWith(".xlsx") ? filename : `${filename}.xlsx`);
}

export function downloadCsv(rows: ExportRow[], filename: string): void {
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const quote = (value: unknown) => `"${safe(value).replaceAll('"', '""')}"`;
  const content = [headers.map(quote).join(","), ...rows.map((row) => headers.map((key) => quote(row[key])).join(","))].join("\r\n");
  saveBlob(new Blob(["\ufeff", content], { type: "text/csv;charset=utf-8" }), filename.endsWith(".csv") ? filename : `${filename}.csv`);
}

export function downloadPdf(rows: ExportRow[], filename: string, title: string): void {
  const doc = new jsPDF({ orientation: "landscape", unit: "pt", format: "a4" });
  doc.setFont("helvetica", "bold"); doc.setFontSize(16); doc.text(title, 40, 38);
  doc.setFont("helvetica", "normal"); doc.setFontSize(9); doc.text(`Town Bank Confidential · Generated ${new Date().toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST`, 40, 54);
  const headers = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  autoTable(doc, { startY: 70, head: [headers], body: rows.map((row) => headers.map((key) => safe(row[key]))), styles: { fontSize: 7, cellPadding: 4 }, headStyles: { fillColor: [23, 38, 61] }, alternateRowStyles: { fillColor: [244, 247, 250] } });
  doc.save(filename.endsWith(".pdf") ? filename : `${filename}.pdf`);
}

function saveBlob(blob: Blob, filename: string): void {
  const link = document.createElement("a");
  const url = URL.createObjectURL(blob);
  link.href = url; link.download = filename; link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
