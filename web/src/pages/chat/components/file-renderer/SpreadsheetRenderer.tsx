import { useEffect, useMemo, useState } from "react";
import * as XLSX from "xlsx";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RendererEmpty, RendererError, RendererLoading } from "./renderer-states";

/**
 * Cap on rendered body rows. Real-world exports can be tens of thousands of
 * rows; rendering all of them produces a multi-megabyte DOM tree that janks
 * the draggable dialog. We render the first slice and tell the user how many
 * were hidden. Virtualized scrolling is a follow-up if this ceiling bites.
 */
const MAX_RENDERED_ROWS = 2000;

interface SheetData {
  name: string;
  rows: unknown[][];
}

interface SpreadsheetRendererProps {
  /** Raw spreadsheet/CSV blob. SheetJS parses xlsx/xls/csv from the same call. */
  blob: Blob;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? "" : value.toLocaleString();
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function SpreadsheetSheet({ sheet }: { sheet: SheetData }) {
  const { headerCells, bodyRows, columnCount, truncated, totalBodyRows } =
    useMemo(() => {
      const allRows = sheet.rows;
      const headerCells = allRows.length > 0 ? allRows[0] : [];
      const rest = allRows.length > 1 ? allRows.slice(1) : [];
      const totalBodyRows = rest.length;
      const truncated = totalBodyRows > MAX_RENDERED_ROWS;
      const bodyRows = truncated ? rest.slice(0, MAX_RENDERED_ROWS) : rest;
      const columnCount = Math.max(
        headerCells.length,
        ...bodyRows.map((row) => row.length),
        1,
      );
      return { headerCells, bodyRows, columnCount, truncated, totalBodyRows };
    }, [sheet]);

  if (sheet.rows.length === 0) {
    return <RendererEmpty message="This sheet is empty." />;
  }

  return (
    <div className="flex h-full flex-col">
      {truncated ? (
        <div className="shrink-0 border-b border-border bg-muted/40 px-3 py-1.5 text-[11px] text-muted-foreground">
          Showing first {MAX_RENDERED_ROWS.toLocaleString()} of{" "}
          {totalBodyRows.toLocaleString()} rows.
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10">
            <tr className="bg-muted text-muted-foreground">
              {Array.from({ length: columnCount }).map((_, ci) => (
                <th
                  key={ci}
                  className="border-b border-border px-2.5 py-1.5 text-left font-semibold whitespace-nowrap"
                >
                  {formatCell(headerCells[ci])}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, ri) => (
              <tr
                key={ri}
                className={ri % 2 === 1 ? "bg-muted/30" : undefined}
              >
                {Array.from({ length: columnCount }).map((_, ci) => (
                  <td
                    key={ci}
                    className="border-b border-border/60 px-2.5 py-1 align-top break-words"
                  >
                    {formatCell(row[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Renders xlsx/xls/csv as a table. Multi-sheet workbooks get a tab bar; CSV is
 * always single-sheet. Parsed purely client-side via SheetJS.
 */
export default function SpreadsheetRenderer({ blob }: SpreadsheetRendererProps) {
  const [sheets, setSheets] = useState<SheetData[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeSheet, setActiveSheet] = useState("0");

  useEffect(() => {
    let cancelled = false;
    setSheets(null);
    setError(null);
    setActiveSheet("0");

    const parse = async () => {
      try {
        const buffer = await blob.arrayBuffer();
        const workbook = XLSX.read(new Uint8Array(buffer), {
          type: "array",
          cellDates: true,
        });
        const parsed: SheetData[] = workbook.SheetNames.map((name) => {
          const ws = workbook.Sheets[name];
          const rows = ws
            ? XLSX.utils.sheet_to_json<unknown[]>(ws, {
                header: 1,
                raw: false,
                defval: "",
                blankrows: false,
              })
            : [];
          return { name, rows };
        });
        if (cancelled) {
          return;
        }
        const withContent = parsed.filter((s) => s.rows.length > 0);
        const result = withContent.length > 0 ? withContent : parsed;
        if (result.length === 0) {
          setError("This file does not contain any sheets.");
          return;
        }
        setSheets(result);
      } catch (err) {
        if (cancelled) {
          return;
        }
        setError(
          err instanceof Error
            ? err.message
            : "Failed to read this spreadsheet.",
        );
      }
    };

    void parse();
    return () => {
      cancelled = true;
    };
  }, [blob]);

  if (error) {
    return <RendererError message={error} />;
  }
  if (!sheets) {
    return <RendererLoading />;
  }

  const activeIndex = Number(activeSheet);
  const activeSheetData = sheets[activeIndex] ?? sheets[0];

  if (sheets.length === 1) {
    return (
      <div className="h-full">
        <SpreadsheetSheet sheet={activeSheetData} />
      </div>
    );
  }

  return (
    <Tabs
      value={activeSheet}
      onValueChange={setActiveSheet}
      className="flex h-full flex-col"
    >
      <TabsList
        variant="line"
        className="w-full shrink-0 justify-start overflow-x-auto px-2"
      >
        {sheets.map((sheet, idx) => (
          <TabsTrigger key={idx} value={String(idx)}>
            {sheet.name || `Sheet ${idx + 1}`}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent
        value={activeSheet}
        className="mt-0 min-h-0 flex-1 overflow-hidden"
      >
        <SpreadsheetSheet sheet={activeSheetData} />
      </TabsContent>
    </Tabs>
  );
}
