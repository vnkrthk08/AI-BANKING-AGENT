import { flexRender, getCoreRowModel, getPaginationRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { CaretDown, CaretLeft, CaretRight, CaretUp } from "@phosphor-icons/react";
import { useState } from "react";

export function DataTable<TData>({ data, columns, rowId, onRowClick, pageSize = 12, emptyTitle = "No records match these filters", emptyText = "Adjust the filters to see more records." }: {
  data: TData[]; columns: ColumnDef<TData, any>[]; rowId: (row: TData) => string; onRowClick?: (row: TData) => void; pageSize?: number; emptyTitle?: string; emptyText?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({ data, columns, state: { sorting }, onSortingChange: setSorting, getRowId: rowId, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getPaginationRowModel: getPaginationRowModel(), initialState: { pagination: { pageSize } } });
  if (!data.length) return <div className="ops-empty"><strong>{emptyTitle}</strong><span>{emptyText}</span></div>;
  return <div className="ops-table-wrap"><table className="ops-table"><thead>{table.getHeaderGroups().map((group) => <tr key={group.id}>{group.headers.map((header) => <th key={header.id} aria-sort={header.column.getIsSorted() ? header.column.getIsSorted() === "asc" ? "ascending" : "descending" : "none"}>
    {header.isPlaceholder ? null : <button className="ops-th-button" disabled={!header.column.getCanSort()} onClick={header.column.getToggleSortingHandler()}>{flexRender(header.column.columnDef.header, header.getContext())}{header.column.getIsSorted() === "asc" ? <CaretUp size={12} /> : header.column.getIsSorted() === "desc" ? <CaretDown size={12} /> : null}</button>}
  </th>)}</tr>)}</thead><tbody>{table.getRowModel().rows.map((row) => <tr key={row.id} className={onRowClick ? "ops-row-clickable" : ""} onClick={() => onRowClick?.(row.original)}>{row.getVisibleCells().map((cell) => <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>)}</tr>)}</tbody></table>
  <div className="ops-table-footer"><span>{data.length.toLocaleString("en-IN")} records · page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}</span><div><button className="ops-small-icon" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()} aria-label="Previous page"><CaretLeft size={15} /></button><button className="ops-small-icon" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()} aria-label="Next page"><CaretRight size={15} /></button></div></div></div>;
}
