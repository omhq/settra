import { useMemo, useState } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ChatResults } from "@/lib/api";
import { cn } from "@/lib/utils";

type ResultRow = Record<string, unknown>;
type SelectedCell = {
  rowIndex: number;
  columnId: string;
  value: unknown;
};

const columnHelper = createColumnHelper<ResultRow>();

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toLocaleString();
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDetailValue(value: unknown) {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (value instanceof Date) return value.toLocaleString();
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return formatCell(value);
    }
  }
  return String(value);
}

function CellInspector({
  cell,
  onClose,
}: {
  cell: SelectedCell;
  onClose: () => void;
}) {
  return (
    <aside className="min-w-0 border-l border-blue-200 bg-blue-50/40 dark:border-blue-400/20 dark:bg-blue-950/20">
      <div className="flex items-start justify-between gap-2 border-b border-blue-200 bg-blue-100/60 px-3 py-2 dark:border-blue-400/15 dark:bg-blue-950/35">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-blue-950 dark:text-blue-100">
            {cell.columnId}
          </p>
          <p className="mt-0.5 text-[11px] text-blue-700 dark:text-blue-300">
            Row {cell.rowIndex + 1}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Close cell details"
          className="size-6 text-blue-700 hover:bg-blue-200/70 hover:text-blue-950 dark:text-blue-300 dark:hover:bg-blue-400/10 dark:hover:text-blue-100"
          onClick={onClose}
        >
          <X className="size-3.5" />
        </Button>
      </div>
      <div className="max-h-72 overflow-auto p-3">
        <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
          {formatDetailValue(cell.value)}
        </pre>
      </div>
    </aside>
  );
}

export function ChatResultTable({ results }: { results: ChatResults }) {
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null);
  const columns = useMemo<ColumnDef<ResultRow, unknown>[]>(
    () =>
      results.columns.map((column) =>
        columnHelper.accessor((row) => row[column], {
          id: column,
          header: column,
          cell: (info) => formatCell(info.getValue()),
        }),
      ),
    [results.columns],
  );
  const table = useReactTable({
    data: results.rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });
  const totalRowCount = results.row_count;
  const hasRows = totalRowCount > 0;

  if (!results.columns.length) return null;

  return (
    <div className="mt-3 w-full overflow-hidden rounded-lg border border-blue-200 bg-white shadow-sm shadow-blue-950/[0.04] dark:border-blue-400/20 dark:bg-card dark:shadow-black/10">
      <div
        className={cn(
          "grid min-h-0",
          selectedCell
            ? "grid-cols-[minmax(0,1fr)_minmax(14rem,16rem)]"
            : "grid-cols-[minmax(0,1fr)]",
        )}
      >
        <div className="min-w-0">
          <div className="max-h-[min(32rem,70vh)] overflow-auto">
            <table className="min-w-full table-fixed text-xs">
              <thead className="border-b border-blue-200 text-blue-950 dark:border-blue-400/20 dark:text-blue-100">
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th
                        key={header.id}
                        className="sticky top-0 z-10 w-40 border-r border-blue-100 bg-blue-50 px-2.5 py-2 text-left font-semibold last:border-r-0 dark:border-blue-400/10 dark:bg-blue-950/90"
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-blue-100 dark:divide-blue-400/10">
                {table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    className="odd:bg-white even:bg-blue-50/25 dark:odd:bg-card dark:even:bg-blue-950/10"
                  >
                    {row.getVisibleCells().map((cell) => {
                      const value = cell.getValue();
                      const isSelected =
                        selectedCell?.rowIndex === row.index &&
                        selectedCell.columnId === cell.column.id;

                      return (
                        <td
                          key={cell.id}
                          className="max-w-40 border-r border-blue-50 p-0 align-top last:border-r-0 dark:border-blue-400/10"
                        >
                          <button
                            type="button"
                            className={cn(
                              "block w-full truncate px-2.5 py-1.5 text-left text-slate-800 transition-colors hover:bg-blue-100/60 focus-visible:bg-blue-100 focus-visible:outline-none dark:text-foreground dark:hover:bg-blue-400/10 dark:focus-visible:bg-blue-400/10",
                              isSelected &&
                                "bg-blue-100 text-blue-950 ring-1 ring-inset ring-blue-300 dark:bg-blue-400/15 dark:text-blue-100 dark:ring-blue-300/30",
                            )}
                            title={formatCell(value)}
                            onClick={() =>
                              setSelectedCell({
                                rowIndex: row.index,
                                columnId: cell.column.id,
                                value,
                              })
                            }
                          >
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext(),
                            )}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
                {!hasRows && (
                  <tr>
                    <td
                      className="px-2.5 py-2 text-blue-700 dark:text-blue-300"
                      colSpan={results.columns.length}
                    >
                      No rows returned
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {hasRows && results.truncated && (
            <div className="border-t border-blue-200 bg-blue-50/60 px-2.5 py-1.5 text-xs text-blue-700 dark:border-blue-400/20 dark:bg-blue-950/30 dark:text-blue-300">
              Showing first {results.rows.length} rows
            </div>
          )}
        </div>
        {selectedCell && (
          <CellInspector
            cell={selectedCell}
            onClose={() => setSelectedCell(null)}
          />
        )}
      </div>
    </div>
  );
}
