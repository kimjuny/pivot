import { useEffect, useRef, useState } from "react";

import { Check, ChevronRight, Copy, XCircle } from "lucide-react";
import { toast } from "sonner";

import type { RecursionRecord } from "../types";
import { copyTextToClipboard } from "@/utils/clipboard";
import { StreamingFieldExtractor } from "@/utils/streamingFieldExtractor";

interface ToolExecutionSnapshot {
  toolCalls: Array<{
    id: string;
    name: string;
    arguments: Record<string, unknown> | string;
  }>;
  toolResults: Array<{
    tool_call_id: string;
    name: string;
    arguments?: Record<string, unknown> | string;
    result?: unknown;
    error?: string;
    success: boolean;
  }>;
  pendingArguments: boolean;
  pendingResultCount: number;
  isWaiting: boolean;
}

type ToolCallSnapshot = ToolExecutionSnapshot["toolCalls"][number];
type ToolResultSnapshot = ToolExecutionSnapshot["toolResults"][number];
type LiveToolPayloadSnapshot = {
  arguments: Record<string, string>;
  finalArguments: Set<string>;
};
// String argument fields whose in-progress content we surface from the
// raw arguments JSON stream so the UI can render the live filename and
// +N line counter as the LLM writes.  ``path`` is included so the
// basename appears alongside the growing counter before the finalized
// ``tool_call`` event arrives.
const STREAMED_TOOL_ARG_FIELDS = [
  "path",
  "content",
  "diff",
  "old_string",
  "new_string",
];
type ToolExecutionSummaryPart = {
  key: string;
  content: string;
  className: string;
  title?: string;
  isCount?: boolean;
};
type ToolExecutionItemSnapshot = {
  key: string;
  call: ToolCallSnapshot;
  result?: ToolResultSnapshot;
  isPreparing: boolean;
  livePayload?: LiveToolPayloadSnapshot;
};

interface RecursionCardProps {
  recursion: RecursionRecord;
}

/**
 * Normalizes streamed tool payloads so the card can render pending tool work
 * before result events arrive from the backend.
 */
function getToolExecutionSnapshot(eventData: unknown): ToolExecutionSnapshot {
  const normalized =
    typeof eventData === "object" && eventData !== null
      ? (eventData as {
          tool_calls?: Array<{
            id: string;
            name: string;
            arguments: Record<string, unknown> | string;
          }>;
          tool_results?: Array<{
            tool_call_id: string;
            name: string;
            arguments?: Record<string, unknown> | string;
            result?: unknown;
            error?: string;
            success: boolean;
          }>;
          pending_arguments?: boolean;
        })
      : undefined;

  const toolCalls = Array.isArray(normalized?.tool_calls)
    ? normalized.tool_calls
    : [];
  const toolResults = Array.isArray(normalized?.tool_results)
    ? normalized.tool_results
    : [];
  const pendingResultCount = Math.max(toolCalls.length - toolResults.length, 0);

  return {
    toolCalls,
    toolResults,
    pendingArguments: normalized?.pending_arguments === true,
    pendingResultCount,
    isWaiting: toolCalls.length > 0 && pendingResultCount > 0,
  };
}

function formatToolValue(value: unknown): string {
  if (value === undefined || value === null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return "[Unserializable value]";
  }
}

function getDisplayToolResultPayload(
  toolName: string,
  payload: unknown,
): unknown {
  if (
    (toolName !== "edit_file" && toolName !== "write_file") ||
    payload === null ||
    typeof payload !== "object" ||
    Array.isArray(payload)
  ) {
    return payload;
  }

  const sanitized = { ...(payload as Record<string, unknown>) };
  delete sanitized.diff;
  delete sanitized.content_hash;
  return sanitized;
}

function getToolResultLabel(result: ToolResultSnapshot | undefined): string | null {
  if (!result) {
    return null;
  }
  return result.success ? null : "Failed";
}

function getToolResultBadgeClass(result: ToolResultSnapshot | undefined): string {
  if (!result) {
    return "bg-orange-500/10 text-orange-600";
  }
  return result.success
    ? "bg-success/10 text-success"
    : "bg-danger/10 text-danger";
}

function getToolGroupStatus(
  items: ToolExecutionItemSnapshot[],
): "Failed" | null {
  if (items.some(({ result }) => result?.success === false)) {
    return "Failed";
  }
  return null;
}

function getToolGroupStatusBadgeClass(_status: "Failed"): string {
  return "bg-danger/10 text-danger";
}

function getToolArgumentRecord(
  value: ToolCallSnapshot["arguments"],
): Record<string, unknown> | null {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value) as unknown;
      return parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null;
    } catch (_error) {
      return null;
    }
  }
  return value;
}

function getStringArgument(
  args: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = args?.[key];
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function getRawStringArgument(
  args: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = args?.[key];
  return typeof value === "string" ? value : null;
}

function getRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function getStringField(
  value: Record<string, unknown> | null,
  key: string,
): string | null {
  const field = value?.[key];
  return typeof field === "string" ? field : null;
}

function getPathBasename(path: string): string {
  const normalizedPath = path.replace(/\\/g, "/").replace(/\/+$/, "");
  return normalizedPath.split("/").filter(Boolean).pop() || path;
}

function countTextLines(value: string): number {
  if (value.length === 0) {
    return 0;
  }
  const lines = value.split(/\r\n|\r|\n/);
  const lastLine = lines[lines.length - 1];
  return lastLine === "" ? lines.length - 1 : lines.length;
}

function countDiffLines(value: string): { additions: number; deletions: number } {
  let additions = 0;
  let deletions = 0;
  for (const line of value.split(/\r\n|\r|\n/)) {
    if (line.startsWith("+++") || line.startsWith("---")) {
      continue;
    }
    if (line.startsWith("+")) {
      additions += 1;
    } else if (line.startsWith("-")) {
      deletions += 1;
    }
  }
  return { additions, deletions };
}

function splitDiffLines(value: string): string[] {
  if (value.length === 0) {
    return [];
  }
  const lines = value.split(/\r\n|\r|\n/);
  return lines[lines.length - 1] === "" ? lines.slice(0, -1) : lines;
}

function countReplacementDiffLines(
  oldValue: string,
  newValue: string,
): { additions: number; deletions: number } {
  const oldLines = splitDiffLines(oldValue);
  const newLines = splitDiffLines(newValue);
  const previousRow: number[] = Array.from({ length: newLines.length + 1 }, () => 0);
  const currentRow: number[] = Array.from({ length: newLines.length + 1 }, () => 0);

  for (const oldLine of oldLines) {
    for (let newIndex = 0; newIndex < newLines.length; newIndex += 1) {
      currentRow[newIndex + 1] =
        oldLine === newLines[newIndex]
          ? previousRow[newIndex] + 1
          : Math.max(previousRow[newIndex + 1], currentRow[newIndex]);
    }
    for (let i = 0; i < currentRow.length; i += 1) {
      previousRow[i] = currentRow[i];
      currentRow[i] = 0;
    }
  }

  const unchangedLines = previousRow[newLines.length];
  return {
    additions: newLines.length - unchangedLines,
    deletions: oldLines.length - unchangedLines,
  };
}

function getLiveOrResolvedStringArgument(
  args: Record<string, unknown> | null,
  livePayload: LiveToolPayloadSnapshot | undefined,
  key: string,
): string | null {
  const liveValue = livePayload?.arguments[key];
  if (typeof liveValue === "string") {
    return liveValue;
  }
  return getRawStringArgument(args, key);
}

function normalizeToolPath(path: string): string {
  const trimmed = path.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function getToolExecutionSummaryParts(
  call: ToolCallSnapshot,
  livePayload?: LiveToolPayloadSnapshot,
  result?: ToolResultSnapshot,
): ToolExecutionSummaryPart[] {
  const args = getToolArgumentRecord(call.arguments);
  const rawPath = getLiveOrResolvedStringArgument(args, livePayload, "path");
  const path = rawPath ? normalizeToolPath(rawPath) : null;
  const dirPath = getStringArgument(args, "dir_path");
  const command = getStringArgument(args, "command");
  const query = getStringArgument(args, "query");
  const content = getLiveOrResolvedStringArgument(args, livePayload, "content");
  const diff = getLiveOrResolvedStringArgument(args, livePayload, "diff");
  const oldString = getLiveOrResolvedStringArgument(args, livePayload, "old_string");
  const newString = getLiveOrResolvedStringArgument(args, livePayload, "new_string");
  const resultRecord = getRecord(result?.result);
  const resultDiff = getStringField(resultRecord, "diff");
  const agentAlias = getStringArgument(args, "agent");
  const delegationInstruction = getStringArgument(args, "instruction");

  const delegationContextId = getStringArgument(args, "delegation_context_id");
  const delegationResponse = getStringArgument(args, "response");

  if (call.name === "delegate_to_agent" && delegationContextId) {
    return [
      {
        key: "mode",
        content: "Resume",
        className: "shrink-0 font-mono text-amber-400",
      },
      ...(delegationResponse
        ? [
            {
              key: "response",
              content:
                delegationResponse.length > 60
                  ? `${delegationResponse.slice(0, 60)}...`
                  : delegationResponse,
              className: "min-w-0 truncate text-muted-foreground",
              title: delegationResponse,
            },
          ]
        : []),
    ];
  }

  if (call.name === "delegate_to_agent" && agentAlias) {
    return [
      {
        key: "agent",
        content: agentAlias,
        className: "min-w-0 truncate font-mono text-violet-400",
      },
      ...(delegationInstruction
        ? [
            {
              key: "instruction",
              content:
                delegationInstruction.length > 60
                  ? `${delegationInstruction.slice(0, 60)}...`
                  : delegationInstruction,
              className: "min-w-0 truncate text-muted-foreground",
              title: delegationInstruction,
            },
          ]
        : []),
    ];
  }

  if (
    (call.name === "write_file" ||
      call.name === "edit_file") &&
    path
  ) {
    const parts: ToolExecutionSummaryPart[] = [
      {
        key: "path",
        content: getPathBasename(path),
        className: "min-w-0 truncate font-mono text-muted-foreground",
        title: path,
      },
    ];
    if (call.name === "write_file" && content !== null) {
      parts.push({
        key: "additions",
        content: `+${countTextLines(content)}`,
        className: "shrink-0 font-mono text-success",
        isCount: true,
      });
    }
    if (call.name === "edit_file") {
      const diffText = resultDiff ?? diff;
      const diffCounts =
        diffText !== null
          ? countDiffLines(diffText)
          : oldString !== null && newString !== null
            ? countReplacementDiffLines(oldString, newString)
            : null;
      if (diffCounts === null) {
        return parts;
      }
      parts.push(
        {
          key: "additions",
          content: `+${diffCounts.additions}`,
          className: "shrink-0 font-mono text-success",
          isCount: true,
        },
        {
          key: "deletions",
          content: `-${diffCounts.deletions}`,
          className: "shrink-0 font-mono text-danger",
          isCount: true,
        },
      );
    }
    return parts;
  }

  if (call.name === "read_file" && path) {
    return [
      {
        key: "path",
        content: path,
        className: "min-w-0 truncate font-mono text-muted-foreground",
      },
    ];
  }

  if (call.name === "list_directories" && dirPath) {
    return [
      {
        key: "dir_path",
        content: dirPath,
        className: "min-w-0 truncate font-mono text-muted-foreground",
      },
    ];
  }

  if (call.name === "run_bash" && command) {
    return [
      {
        key: "command",
        content: command,
        className: "min-w-0 truncate font-mono text-muted-foreground",
        title: command,
      },
    ];
  }

  if (call.name === "search") {
    return [
      ...(path
        ? [
            {
              key: "path",
              content: path,
              className: "shrink-0 font-mono text-muted-foreground",
            },
          ]
        : []),
      ...(query
        ? [
            {
              key: "query",
              content: query,
              className: "min-w-0 truncate font-mono text-muted-foreground",
              title: query,
            },
          ]
        : []),
    ];
  }

  return [];
}

function ToolPayloadSection({
  label,
  value,
}: {
  label: "Arguments" | "Result" | "Full Result";
  value: string;
}) {
  const [hasCopied, setHasCopied] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  const handleCopy = async () => {
    try {
      await copyTextToClipboard(value);
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
      setHasCopied(true);
      copyResetTimeoutRef.current = window.setTimeout(() => {
        setHasCopied(false);
        copyResetTimeoutRef.current = null;
      }, 2000);
    } catch {
      toast.error(`Failed to copy ${label.toLowerCase()}`);
    }
  };

  return (
    <div className="group/payload">
      <div className="mb-1 flex items-center justify-between gap-3 font-semibold text-zinc-300">
        <span>{label}:</span>
        <button
          type="button"
          onClick={() => {
            void handleCopy();
          }}
          className="flex h-6 w-6 items-center justify-center rounded-md bg-transparent text-zinc-400 opacity-0 transition-[background-color,color,opacity] duration-150 hover:bg-white/10 hover:text-zinc-100 focus-visible:bg-white/10 focus-visible:text-zinc-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-400/60 group-hover/payload:opacity-100"
          aria-label={hasCopied ? `Copied ${label}` : `Copy ${label}`}
          title={hasCopied ? "Copied" : `Copy ${label}`}
        >
          {hasCopied ? (
            <Check className="h-3.5 w-3.5" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
      <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-zinc-100">
        {value}
      </pre>
    </div>
  );
}

function getWindowedLines(value: string, maxLines = 420): {
  lines: string[];
  startLine: number;
  totalLines: number;
  isTruncated: boolean;
} {
  const lines = value.split(/\r\n|\r|\n/);
  if (lines.length <= maxLines) {
    return {
      lines,
      startLine: 1,
      totalLines: lines.length,
      isTruncated: false,
    };
  }
  return {
    lines: lines.slice(lines.length - maxLines),
    startLine: lines.length - maxLines + 1,
    totalLines: lines.length,
    isTruncated: true,
  };
}

type DiffPreviewLine = {
  content: string;
  oldLineNumber: number | null;
};

function parseUnifiedDiffLines(value: string): DiffPreviewLine[] {
  const lines = value.split(/\r\n|\r|\n/);
  const parsedLines: DiffPreviewLine[] = [];
  let currentOldLine: number | null = null;

  for (const line of lines) {
    if (line.startsWith("@@")) {
      const headerMatch = /^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@/.exec(line);
      currentOldLine = headerMatch ? Number.parseInt(headerMatch[1], 10) : null;
      parsedLines.push({ content: line, oldLineNumber: null });
      continue;
    }

    if (line.startsWith("---") || line.startsWith("+++")) {
      parsedLines.push({ content: line, oldLineNumber: null });
      continue;
    }

    if (line.startsWith("+")) {
      parsedLines.push({ content: line, oldLineNumber: null });
      continue;
    }

    if (
      (line.startsWith(" ") || line.startsWith("-")) &&
      currentOldLine !== null
    ) {
      parsedLines.push({ content: line, oldLineNumber: currentOldLine });
      currentOldLine += 1;
      continue;
    }

    parsedLines.push({ content: line, oldLineNumber: null });
  }

  return parsedLines;
}

function getWindowedDiffLines(value: string, maxLines = 420): {
  lines: DiffPreviewLine[];
  startLine: number;
  totalLines: number;
  isTruncated: boolean;
} {
  const lines = parseUnifiedDiffLines(value);
  if (lines.length <= maxLines) {
    return {
      lines,
      startLine: 1,
      totalLines: lines.length,
      isTruncated: false,
    };
  }
  return {
    lines: lines.slice(lines.length - maxLines),
    startLine: lines.length - maxLines + 1,
    totalLines: lines.length,
    isTruncated: true,
  };
}

function ToolCodePreview({
  value,
  emptyLabel,
}: {
  value: string;
  emptyLabel: string;
}) {
  const preview = value ? getWindowedLines(value) : null;
  const lines = preview?.lines ?? [];

  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-3 font-semibold text-zinc-300">
        <span>Preview:</span>
        {preview?.isTruncated ? (
          <span className="text-[11px] font-normal text-zinc-500">
            Showing lines {preview.startLine}-{preview.totalLines} of {preview.totalLines}
          </span>
        ) : null}
      </div>
      <div className="tool-preview-scroll max-h-80 overflow-auto rounded border border-white/10 bg-zinc-950/80 py-2 font-mono text-xs leading-relaxed">
        {lines.length > 0 ? (
          lines.map((line, index) => (
            <div key={`${index}-${line}`} className="flex min-w-0">
              <span className="w-10 shrink-0 select-none pr-3 text-right text-zinc-500">
                {(preview?.startLine ?? 1) + index}
              </span>
              <span className="min-w-0 flex-1 whitespace-pre text-zinc-100">
                {line || " "}
              </span>
            </div>
          ))
        ) : (
          <div className="px-3 text-zinc-500">{emptyLabel}</div>
        )}
      </div>
    </div>
  );
}

function ToolDiffPreview({ value }: { value: string }) {
  const preview = value ? getWindowedDiffLines(value) : null;
  const lines = preview?.lines ?? [];

  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-3 font-semibold text-zinc-300">
        <span>Diff:</span>
        {preview?.isTruncated ? (
          <span className="text-[11px] font-normal text-zinc-500">
            Showing lines {preview.startLine}-{preview.totalLines} of {preview.totalLines}
          </span>
        ) : null}
      </div>
      <div className="tool-preview-scroll max-h-80 overflow-auto rounded border border-white/10 bg-zinc-950/80 py-2 font-mono text-xs leading-relaxed">
        {lines.length > 0 ? (
          <div className="min-w-full w-max">
            {lines.map((line, index) => {
              const lineClassName = line.content.startsWith("+") && !line.content.startsWith("+++")
                ? "bg-success/10 text-emerald-200"
                : line.content.startsWith("-") && !line.content.startsWith("---")
                  ? "bg-danger/10 text-red-200"
                  : line.content.startsWith("@@")
                    ? "bg-sky-500/10 text-sky-200"
                    : "text-zinc-100";

              return (
                <div
                  key={`${index}-${line.content}`}
                  className={`flex w-full ${lineClassName}`}
                >
                  <span className="w-10 shrink-0 select-none pr-3 text-right text-zinc-500">
                    {line.oldLineNumber ?? ""}
                  </span>
                  <span className="whitespace-pre pr-3">
                    {line.content || " "}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="px-3 text-zinc-500">Waiting for diff...</div>
        )}
      </div>
    </div>
  );
}

function ToolReplacementPreview({
  oldString,
  newString,
}: {
  oldString: string | null;
  newString: string | null;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-wide text-zinc-500">
        <span>Replacement:</span>
      </div>
      <div className="space-y-2 overflow-x-auto rounded border border-zinc-800 bg-zinc-950/80 p-3">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-red-300">
            old_string
          </div>
          <pre className="max-h-40 overflow-auto whitespace-pre text-red-100">
            {oldString ?? "Waiting for old_string..."}
          </pre>
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-emerald-300">
            new_string
          </div>
          <pre className="max-h-40 overflow-auto whitespace-pre text-emerald-100">
            {newString ?? "Waiting for new_string..."}
          </pre>
        </div>
      </div>
    </div>
  );
}

function ToolExecutionItem({
  call,
  result,
  isPreparing,
  livePayload,
}: {
  call: ToolCallSnapshot;
  result?: ToolResultSnapshot;
  isPreparing: boolean;
  livePayload?: LiveToolPayloadSnapshot;
}) {
  const [open, setOpen] = useState(false);
  const statusLabel = getToolResultLabel(result);
  const executionLabel = result ? "Ran" : isPreparing ? "Preparing" : "Running";
  const resultPayload =
    result?.result !== undefined
      ? result.result
      : result?.error
        ? { error: result.error }
        : null;
  const displayResultPayload = getDisplayToolResultPayload(
    call.name,
    resultPayload,
  );
  const argumentText = formatToolValue(call.arguments);
  const resultText =
    displayResultPayload === null
      ? "Waiting for tool result..."
      : formatToolValue(displayResultPayload);
  const args = getToolArgumentRecord(call.arguments);
  const resultRecord = getRecord(result?.result);
  const writeContent =
    call.name === "write_file"
      ? getLiveOrResolvedStringArgument(args, livePayload, "content")
      : null;
  const editDiff =
    call.name === "edit_file"
      ? (getStringField(resultRecord, "diff") ??
        getLiveOrResolvedStringArgument(args, livePayload, "diff"))
      : null;
  const editOldString =
    call.name === "edit_file"
      ? getLiveOrResolvedStringArgument(args, livePayload, "old_string")
      : null;
  const editNewString =
    call.name === "edit_file"
      ? getLiveOrResolvedStringArgument(args, livePayload, "new_string")
      : null;
  const usesSpecialPreview = call.name === "write_file" || call.name === "edit_file";
  const summaryParts = getToolExecutionSummaryParts(call, livePayload, result);
  const shimmerSummaryParts = summaryParts.filter((part) => !part.isCount);
  const countSummaryParts = summaryParts.filter((part) => part.isCount);

  return (
    <div className="rounded-md bg-background/45">
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        className="group flex w-full items-start justify-between gap-3 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-muted/25"
        aria-expanded={open}
      >
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <ChevronRight
            className={`mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-all duration-200 group-hover:opacity-100 group-focus-visible:opacity-100 ${
              open ? "rotate-90" : ""
            }`}
          />
          <div className="flex min-w-0 flex-1 items-center gap-1.5 text-xs leading-relaxed text-foreground">
            <span
              className={`flex min-w-0 items-center gap-1.5 ${
                result ? "" : "thinking-silver-shimmer"
              }`}
            >
              <span className={`shrink-0 ${result ? "text-muted-foreground" : ""}`}>
                {executionLabel}
              </span>
              <span className="shrink-0 font-semibold">{call.name}</span>
              {shimmerSummaryParts.map((part) => (
                <span
                  key={part.key}
                  className={part.className}
                  title={part.title}
                >
                  {part.content}
                </span>
              ))}
            </span>
            {countSummaryParts.map((part) => (
              <span key={part.key} className={part.className} title={part.title}>
                {part.content}
              </span>
            ))}
            {statusLabel && (
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${getToolResultBadgeClass(
                  result,
                )}`}
              >
                {statusLabel}
              </span>
            )}
          </div>
        </div>
      </button>

      <div
        className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="px-3 pb-2.5 pl-8">
            <div className="rounded-md border border-border/70 bg-black/90 p-3 font-mono text-xs leading-relaxed text-zinc-100 shadow-inner">
              <div className="space-y-3">
                {usesSpecialPreview ? (
                  call.name === "write_file" ? (
                    <ToolCodePreview
                      value={writeContent ?? ""}
                      emptyLabel="Waiting for file content..."
                    />
                  ) : (
                    editDiff !== null ? (
                      <ToolDiffPreview value={editDiff} />
                    ) : (
                      <ToolReplacementPreview
                        oldString={editOldString}
                        newString={editNewString}
                      />
                    )
                  )
                ) : (
                  <ToolPayloadSection label="Arguments" value={argumentText} />
                )}
                <ToolPayloadSection label="Result" value={resultText} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function ToolExecutionGroup({ items }: { items: ToolExecutionItemSnapshot[] }) {
  const hasPendingTools = items.some(({ result }) => !result);
  const [open, setOpen] = useState(false);
  const autoOpenedForPendingRef = useRef(hasPendingTools);
  const statusLabel = getToolGroupStatus(items);

  useEffect(() => {
    let frameId: number | null = null;
    if (hasPendingTools) {
      autoOpenedForPendingRef.current = true;
      frameId = window.requestAnimationFrame(() => {
        setOpen(true);
      });
      return () => {
        if (frameId !== null) {
          window.cancelAnimationFrame(frameId);
        }
      };
    }
    if (autoOpenedForPendingRef.current) {
      autoOpenedForPendingRef.current = false;
      frameId = window.requestAnimationFrame(() => {
        setOpen(false);
      });
    }
    return () => {
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
      }
    };
  }, [hasPendingTools]);

  return (
    <div className="rounded-md bg-background/45">
      <button
        type="button"
        onClick={() => setOpen((previous) => (hasPendingTools ? true : !previous))}
        className="group flex w-full items-start justify-between gap-3 rounded-md px-3 py-1.5 text-left transition-colors hover:bg-muted/25"
        aria-expanded={open}
      >
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <ChevronRight
            className={`mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-all duration-200 group-hover:opacity-100 group-focus-visible:opacity-100 ${
              open ? "rotate-90" : ""
            }`}
          />
          <div className="flex min-w-0 flex-1 items-center gap-1.5 text-xs leading-relaxed text-foreground">
            <span className="font-normal text-muted-foreground transition-colors duration-200 group-hover:text-muted-foreground/45 group-focus-visible:text-muted-foreground/45">
              {items.length} tools used
            </span>
            {statusLabel && (
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${getToolGroupStatusBadgeClass(
                  statusLabel,
                )}`}
              >
                {statusLabel}
              </span>
            )}
          </div>
        </div>
      </button>

      <div
        className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden" aria-hidden={!open}>
          <div className="space-y-0.5 px-1 pb-0.5 pl-6">
            {items.map(({ key, call, result, isPreparing, livePayload }) => (
              <ToolExecutionItem
                key={key}
                call={call}
                result={result}
                isPreparing={isPreparing}
                livePayload={livePayload}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ThinkingSection({ recursion }: { recursion: RecursionRecord }) {
  const [open, setOpen] = useState(recursion.status === "running");
  const isRunning = recursion.status === "running";

  useEffect(() => {
    setOpen(isRunning);
  }, [isRunning]);

  if (!recursion.thinking) {
    return null;
  }

  return (
    <div className="rounded-md bg-background/50">
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        className="group flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-muted/20"
        aria-expanded={open}
        aria-label="Toggle thinking details"
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-0 transition-all duration-200 group-hover:opacity-100 group-focus-visible:opacity-100 ${
            open ? "rotate-90" : ""
          }`}
        />
        <span
          className={`text-xs font-normal transition-colors duration-200 group-hover:text-muted-foreground/45 group-focus-visible:text-muted-foreground/45 ${
            isRunning ? "thinking-silver-shimmer" : "text-muted-foreground"
          }`}
        >
          Thinking
        </span>
      </button>
      <div
        className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="max-h-64 overflow-y-auto break-words whitespace-pre-wrap px-3 pb-3 pl-9 text-xs leading-relaxed text-muted-foreground">
            {recursion.thinking}
          </div>
        </div>
      </div>
    </div>
  );
}

function RecursionErrors({ recursion }: { recursion: RecursionRecord }) {
  const errorEvents = recursion.events.filter(
    (event) => event.type === "error",
  );

  if (errorEvents.length === 0 && !recursion.errorLog) {
    return null;
  }

  return (
    <div className="space-y-1">
      {errorEvents.map((event, index) => {
        const errorData = event.data as { error?: string } | undefined;

        return (
          <div
            key={`error-${index}`}
            className="rounded-md border border-danger/30 bg-danger/5 p-2"
          >
            <div className="mb-1 flex items-center gap-1.5">
              <XCircle className="h-3.5 w-3.5 text-danger" />
              <span className="text-xs font-semibold text-danger">Error</span>
            </div>
            <div className="pl-5 text-xs text-danger/90">
              {errorData?.error || "Unknown error"}
            </div>
          </div>
        );
      })}

      {recursion.errorLog && (
        <div className="rounded-md border border-danger/30 bg-danger/5 p-2">
          <div className="mb-1 flex items-center gap-1.5">
            <XCircle className="h-3.5 w-3.5 text-danger" />
            <span className="text-xs font-semibold text-danger">Error log</span>
          </div>
          <div className="pl-5 text-xs leading-relaxed text-danger/90">
            {recursion.errorLog}
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Renders the agent's optional progress note as a lightweight aside line in
 * the operation stream. Returns null when there is no message, so pure-tool
 * iterations leave no fallback label behind (this is what retires the
 * "CALL_TOOL" placeholder the previous shell-based layout leaked).
 */
function AsideRow({ text }: { text: string }) {
  // Left padding aligns the text with Thinking rows and tool rows, which
  // both reserve a hidden expand chevron (14px) + gap (8px) after the
  // shared 12px container padding — so the message body starts at 34px,
  // matching its siblings instead of drifting left.
  return (
    <p className="pl-[34px] pr-3 text-xs font-semibold leading-relaxed text-foreground">
      {text}
    </p>
  );
}


type ToolStreamingState = {
  // One streaming extractor per tool call, kept alive across renders so the
  // char-level JSON state machine isn't reset on every event.  Without this,
  // re-running the extractor over the whole event list each render can leave
  // the state machine mid-field (e.g. inside ``content``) and produce wrong
  // field boundaries, which is the root cause of the intermittent
  // "filename / +N counter missing while content streams" race.
  extractors: Map<string, StreamingFieldExtractor>;
  // Accumulated in-progress field values per tool call, fed incrementally.
  payloads: Map<string, LiveToolPayloadSnapshot>;
  // Names seen on tool_payload_delta events, used to build placeholder cards
  // before the first tool_call event arrives (the other half of the race).
  namesByCallId: Map<string, string>;
};

function ToolTimeline({ events }: { events: RecursionRecord["events"] }) {
  const toolEvents = events
    .map((event, index) => ({ event, index }))
    .filter(
      ({ event }) =>
        event.type === "tool_call" ||
        event.type === "tool_payload_delta" ||
        event.type === "tool_result",
    )
    .sort((left, right) => {
      const leftTime = Date.parse(left.event.timestamp);
      const rightTime = Date.parse(right.event.timestamp);
      if (Number.isFinite(leftTime) && Number.isFinite(rightTime)) {
        return leftTime === rightTime ? left.index - right.index : leftTime - rightTime;
      }
      return left.index - right.index;
    })
    .map(({ event }) => event);

  const streamingRef = useRef<ToolStreamingState>({
    extractors: new Map(),
    payloads: new Map(),
    namesByCallId: new Map(),
  });
  const streaming = streamingRef.current;

  // Feed raw-argument fragments to the persistent per-call extractors.
  // The events array is append-only for a given recursion, so a cursor over
  // its index makes re-feeds idempotent: each render only processes the
  // tool_payload_delta events that arrived since the last render.  This is
  // what keeps the char-level extractor state machine stable across renders
  // (re-feeding every delta every render can leave it mid-field and corrupt
  // field boundaries -- the root cause of the intermittent
  // "filename / +N counter missing while content streams" race).
  const processedEventsRef = useRef(0);
  // Detect array replacement (e.g. history replay rebuilding the recursion):
  // when the new events are shorter, the cursor is stale and must reset.
  if (events.length < processedEventsRef.current) {
    streaming.extractors.clear();
    streaming.payloads.clear();
    streaming.namesByCallId.clear();
    processedEventsRef.current = 0;
  }
  for (let i = processedEventsRef.current; i < events.length; i += 1) {
    const event = events[i];
    if (event.type !== "tool_payload_delta") {
      continue;
    }
    const data =
      event.data && typeof event.data === "object" && !Array.isArray(event.data)
        ? (event.data as { tool_call_id?: unknown; tool_name?: unknown; delta?: unknown })
        : null;
    const toolCallId = data?.tool_call_id;
    const delta = data?.delta;
    if (
      typeof toolCallId !== "string" ||
      toolCallId.length === 0 ||
      typeof delta !== "string" ||
      delta.length === 0
    ) {
      continue;
    }
    if (typeof data?.tool_name === "string" && data.tool_name.length > 0) {
      streaming.namesByCallId.set(toolCallId, data.tool_name);
    }
    let extractor = streaming.extractors.get(toolCallId);
    if (!extractor) {
      extractor = new StreamingFieldExtractor(STREAMED_TOOL_ARG_FIELDS);
      streaming.extractors.set(toolCallId, extractor);
    }
    let livePayload = streaming.payloads.get(toolCallId);
    if (!livePayload) {
      livePayload = { arguments: {}, finalArguments: new Set<string>() };
      streaming.payloads.set(toolCallId, livePayload);
    }
    for (const fieldDelta of extractor.feed(delta)) {
      if (fieldDelta.delta) {
        livePayload.arguments[fieldDelta.fieldName] = `${
          livePayload.arguments[fieldDelta.fieldName] ?? ""
        }${fieldDelta.delta}`;
      }
      if (fieldDelta.isFinal) {
        livePayload.finalArguments.add(fieldDelta.fieldName);
      }
    }
  }
  processedEventsRef.current = events.length;

  if (toolEvents.length === 0) {
    return null;
  }

  const callById = new Map<string, ToolCallSnapshot>();
  const resultById = new Map<string, ToolResultSnapshot>();
  const preparingById = new Map<string, boolean>();
  const orderedIds: string[] = [];

  for (const event of toolEvents) {
    if (event.type === "tool_payload_delta") {
      continue;
    }

    const toolSnapshot = getToolExecutionSnapshot(event.data);

    for (const call of toolSnapshot.toolCalls) {
      const id = call.id || `${orderedIds.length}`;
      if (!callById.has(id)) {
        orderedIds.push(id);
      }
      callById.set(id, { ...call, id });
      preparingById.set(id, toolSnapshot.pendingArguments && !resultById.has(id));
    }

    for (const result of toolSnapshot.toolResults) {
      const id = result.tool_call_id;
      if (!id) {
        continue;
      }
      resultById.set(id, result);
      preparingById.set(id, false);
      if (!callById.has(id)) {
        orderedIds.push(id);
        callById.set(id, {
          id,
          name: result.name,
          arguments: result.arguments ?? {},
        });
      } else if (result.arguments !== undefined) {
        callById.set(id, {
          ...callById.get(id)!,
          arguments: result.arguments,
        });
      }
    }
  }

  // Placeholder cards for tool calls whose arguments are still streaming:
  // tool_payload_delta can arrive before the first tool_call event, and a
  // finalized tool_call may only land once the whole arguments JSON parses.
  // Without this, the live payload (and the +N counter derived from it) has
  // nothing to attach to, so both filename and counter vanish even while
  // content streams into the expanded preview.
  for (const [callId, payload] of streaming.payloads) {
    if (callById.has(callId) || orderedIds.includes(callId)) {
      continue;
    }
    // Only build a placeholder once we actually have streamed data (e.g. a
    // path), so empty/partial pre-path deltas don't create phantom cards.
    if (
      Object.keys(payload.arguments).length === 0 &&
      payload.finalArguments.size === 0
    ) {
      continue;
    }
    orderedIds.push(callId);
    callById.set(callId, {
      id: callId,
      name: streaming.namesByCallId.get(callId) ?? "tool",
      arguments: {},
    });
    preparingById.set(callId, true);
  }

  const toolItems = orderedIds.flatMap<ToolExecutionItemSnapshot>((id) => {
    const call = callById.get(id);
    if (!call) {
      return [];
    }
    return [
      {
        key: id,
        call,
        result: resultById.get(id),
        isPreparing: preparingById.get(id) ?? false,
        livePayload: streaming.payloads.get(id),
      },
    ];
  });

  if (toolItems.length === 0) {
    return null;
  }

  if (toolItems.length === 1) {
    const [item] = toolItems;
    return (
      <div className="space-y-1">
        <ToolExecutionItem
          call={item.call}
          result={item.result}
          isPreparing={item.isPreparing}
          livePayload={item.livePayload}
        />
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <ToolExecutionGroup items={toolItems} />
    </div>
  );
}

/**
 * Renders one recursion as a shell-less step in a flat operation stream.
 *
 * The previous design wrapped every iteration in a titled card whose label
 * fell back to the raw ``action`` enum (``CALL_TOOL`` / ``ANSWER`` / ...),
 * which surfaced internal protocol values to users whenever the agent
 * skipped its progress note. This version renders only the step's actual
 * content — reasoning (thinking), an optional progress note (message),
 * any errors, and the tool timeline — so pure-tool iterations show up as
 * nothing but their tool rows, the way Claude Code / Codex present them.
 */
export function RecursionCard({
  recursion,
}: RecursionCardProps) {
  const hasThinking = Boolean(recursion.thinking);
  const hasMessage = Boolean(recursion.message);
  const hasErrors =
    recursion.events.some((event) => event.type === "error") ||
    Boolean(recursion.errorLog);

  // Avoid emitting an empty container for the brief window between
  // recursion_start and the first content event — keeps the stream clean.
  if (!hasThinking && !hasMessage && !hasErrors) {
    const hasToolEvents = recursion.events.some(
      (event) =>
        event.type === "tool_call" ||
        event.type === "tool_payload_delta" ||
        event.type === "tool_result",
    );
    if (!hasToolEvents) {
      return null;
    }
  }

  return (
    <div className="space-y-1.5">
      <ThinkingSection recursion={recursion} />
      {hasMessage && <AsideRow text={recursion.message!} />}
      <RecursionErrors recursion={recursion} />
      <ToolTimeline events={recursion.events} />
    </div>
  );
}
