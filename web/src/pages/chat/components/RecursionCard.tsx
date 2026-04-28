import { useEffect, useRef, useState } from "react";

import {
  AlertCircle,
  Brain,
  Check,
  CheckCircle2,
  ChevronRight,
  Copy,
  Loader2,
  Square,
  XCircle,
} from "@/lib/lucide";
import { toast } from "sonner";

import type { RecursionRecord } from "../types";
import {
  calculateDuration,
  formatTokenCount,
  getRecursionStatus,
} from "../utils/chatSelectors";
import { RecursionStateViewer } from "./RecursionStateViewer";
import { ThinkingWordTicker } from "./ThinkingWordTicker";
import { TokenUsageLabel } from "./TokenUsageLabel";

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
type ToolExecutionItemSnapshot = {
  key: string;
  call: ToolCallSnapshot;
  result?: ToolResultSnapshot;
  isPreparing: boolean;
};

interface RecursionCardProps {
  messageId: string;
  recursion: RecursionRecord;
  taskId?: string;
  isExpanded: boolean;
  onToggle: (messageId: string, recursionUid: string) => void;
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

function ToolExecutionSummary({ call }: { call: ToolCallSnapshot }) {
  const args = getToolArgumentRecord(call.arguments);
  const path = getStringArgument(args, "path");
  const dirPath = getStringArgument(args, "dir_path");
  const command = getStringArgument(args, "command");
  const query = getStringArgument(args, "query");

  if (
    (call.name === "write_file" ||
      call.name === "edit_file" ||
      call.name === "read_file") &&
    path
  ) {
    return <span className="min-w-0 truncate font-mono text-muted-foreground">{path}</span>;
  }

  if (call.name === "list_directories" && dirPath) {
    return (
      <span className="min-w-0 truncate font-mono text-muted-foreground">
        {dirPath}
      </span>
    );
  }

  if (call.name === "run_bash" && command) {
    return (
      <span
        className="min-w-0 truncate font-mono text-muted-foreground"
        title={command}
      >
        {command}
      </span>
    );
  }

  if (call.name === "search") {
    return (
      <>
        {path ? (
          <span className="shrink-0 font-mono text-muted-foreground">{path}</span>
        ) : null}
        {query ? (
          <span
            className="min-w-0 truncate font-mono text-muted-foreground"
            title={query}
          >
            {query}
          </span>
        ) : null}
      </>
    );
  }

  return null;
}

function ToolPayloadSection({
  label,
  value,
}: {
  label: "Arguments" | "Result";
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
      await navigator.clipboard.writeText(value);
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

function ToolExecutionItem({
  call,
  result,
  isPreparing,
}: {
  call: ToolCallSnapshot;
  result?: ToolResultSnapshot;
  isPreparing: boolean;
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
  const argumentText = formatToolValue(call.arguments);
  const resultText =
    resultPayload === null ? "Waiting for tool result..." : formatToolValue(resultPayload);

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
              <ToolExecutionSummary call={call} />
            </span>
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
                <ToolPayloadSection label="Arguments" value={argumentText} />
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
  const [open, setOpen] = useState(hasPendingTools);
  const autoOpenedForPendingRef = useRef(hasPendingTools);
  const statusLabel = getToolGroupStatus(items);

  useEffect(() => {
    if (hasPendingTools) {
      autoOpenedForPendingRef.current = true;
      setOpen(true);
      return;
    }
    if (autoOpenedForPendingRef.current) {
      autoOpenedForPendingRef.current = false;
      setOpen(false);
    }
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
            {items.map(({ key, call, result, isPreparing }) => (
              <ToolExecutionItem
                key={key}
                call={call}
                result={result}
                isPreparing={isPreparing}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusIcon({
  status,
  iconKey,
  runningOffsetClassName = "top-px",
}: {
  status: ReturnType<typeof getRecursionStatus>;
  iconKey: string;
  runningOffsetClassName?: string;
}) {
  if (status === "running") {
    return (
      <Loader2
        key={`${iconKey}-running`}
        className={`relative h-3.5 w-3.5 flex-shrink-0 animate-spin text-sidebar-foreground/60 ${runningOffsetClassName}`}
      />
    );
  }
  if (status === "completed") {
    return (
      <CheckCircle2
        key={`${iconKey}-completed`}
        className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-muted-foreground opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100"
      />
    );
  }
  if (status === "warning") {
    return (
      <AlertCircle
        key={`${iconKey}-warning`}
        className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-warning"
      />
    );
  }
  if (status === "error") {
    return (
      <XCircle
        key={`${iconKey}-error`}
        className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-danger"
      />
    );
  }
  return (
    <Square
      key={`${iconKey}-stopped`}
      className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-muted-foreground"
    />
  );
}

function DetailBarIcon() {
  return (
    <span className="flex h-3.5 w-3.5 items-center justify-center">
      <span className="h-3.5 w-1 rounded-full bg-muted-foreground" />
    </span>
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

function DetailBlock({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5 rounded-md bg-background/60 p-2">
      <div className="flex items-center gap-1.5">
        {icon}
        <span className="text-xs font-semibold text-foreground">{label}</span>
      </div>
      <div className="pl-5 text-xs leading-relaxed text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

function hasExecutionDetails(recursion: RecursionRecord) {
  const nonToolEvents = recursion.events.filter(
    (event) => event.type === "reflect" || event.type === "error",
  );

  return (
    Boolean(recursion.observe) ||
    Boolean(recursion.reason) ||
    Boolean(recursion.action) ||
    nonToolEvents.length > 0 ||
    Boolean(recursion.errorLog)
  );
}

function ExecutionDetails({
  recursion,
  taskId,
}: {
  recursion: RecursionRecord;
  taskId?: string;
}) {
  const nonToolEvents = recursion.events.filter(
    (event) => event.type === "reflect" || event.type === "error",
  );

  if (!hasExecutionDetails(recursion)) {
    return null;
  }

  return (
    <div className="space-y-1">
      {recursion.observe && (
        <DetailBlock icon={<DetailBarIcon />} label="Observe">
          {recursion.observe}
        </DetailBlock>
      )}

      {recursion.reason && (
        <DetailBlock icon={<DetailBarIcon />} label="Reason">
          {recursion.reason}
        </DetailBlock>
      )}

      {recursion.action && (
        <DetailBlock icon={<DetailBarIcon />} label="Action">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-primary">{recursion.action}</span>
            {taskId && (
              <RecursionStateViewer
                taskId={taskId}
                iteration={recursion.iteration}
              />
            )}
          </div>
        </DetailBlock>
      )}

      {nonToolEvents.map((event, index) => {
        if (event.type === "reflect") {
          const reflectData = event.data as { summary?: string } | undefined;

          return (
            <DetailBlock
              key={`reflect-${index}`}
              icon={<Brain className="h-3.5 w-3.5 text-indigo-500" />}
              label="Reflect"
            >
              {reflectData?.summary || "Reflecting on current state..."}
            </DetailBlock>
          );
        }

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

function ToolTimeline({ events }: { events: RecursionRecord["events"] }) {
  const toolEvents = events
    .map((event, index) => ({ event, index }))
    .filter(
      ({ event }) => event.type === "tool_call" || event.type === "tool_result",
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

  if (toolEvents.length === 0) {
    return null;
  }

  const callById = new Map<string, ToolCallSnapshot>();
  const resultById = new Map<string, ToolResultSnapshot>();
  const preparingById = new Map<string, boolean>();
  const orderedIds: string[] = [];

  for (const event of toolEvents) {
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
      }
    }
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
 * Renders one recursion row and its expandable execution details.
 */
export function RecursionCard({
  messageId,
  recursion,
  taskId,
  isExpanded,
  onToggle,
}: RecursionCardProps) {
  const key = `${messageId}-${recursion.uid}`;
  const effectiveStatus = getRecursionStatus(recursion);
  const hasStableRunningLabel = Boolean(
    recursion.summary || recursion.reason || recursion.observe || recursion.action,
  );
  const shouldShowPendingTicker =
    effectiveStatus === "running" && !hasStableRunningLabel;
  const stableRunningLabel =
    recursion.summary ||
    recursion.reason ||
    recursion.observe ||
    recursion.action ||
    "Working...";
  const completedLabel =
    recursion.summary ||
    recursion.reason ||
    recursion.observe ||
    recursion.action ||
    "Completed step";
  const canExpandDetails = hasExecutionDetails(recursion);

  return (
    <div className="mb-2 space-y-1">
      <ThinkingSection recursion={recursion} />

      <button
        onClick={() => {
          if (canExpandDetails) {
            onToggle(messageId, recursion.uid);
          }
        }}
        className="group flex w-full items-start justify-between gap-3 rounded-md bg-muted/20 px-3 py-2 text-left transition-colors hover:bg-muted/30"
        aria-expanded={canExpandDetails ? isExpanded : undefined}
      >
        <div className="flex min-w-0 flex-1 gap-2">
          <div className="pt-0.5">
            <StatusIcon
              status={effectiveStatus}
              iconKey={key}
              runningOffsetClassName={
                shouldShowPendingTicker ? "top-[4px]" : "top-px"
              }
            />
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            {effectiveStatus === "running" ? (
              shouldShowPendingTicker ? (
                <ThinkingWordTicker className="truncate text-xs font-semibold text-muted-foreground" />
              ) : (
                <div
                  className="break-words text-xs font-semibold leading-relaxed text-foreground"
                  title={stableRunningLabel}
                >
                  {stableRunningLabel}
                </div>
              )
            ) : (
              <div
                className="break-words text-xs font-semibold leading-relaxed text-foreground"
                title={completedLabel}
              >
                {completedLabel}
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2.5 pt-0.5">
          {recursion.endTime && (
            <span className="text-xs tabular-nums text-muted-foreground">
              {calculateDuration(recursion.startTime, recursion.endTime)}s
            </span>
          )}
          {recursion.status === "running" &&
          typeof recursion.liveTokensPerSecond === "number" ? (
            <span
              className="whitespace-nowrap text-xs tabular-nums text-muted-foreground"
              title={
                typeof recursion.estimatedCompletionTokens === "number"
                  ? `Estimated output: ${formatTokenCount(recursion.estimatedCompletionTokens)} tokens`
                  : undefined
              }
            >
              {recursion.liveTokensPerSecond.toFixed(1)} tokens/s
            </span>
          ) : (
            recursion.tokens && (
              <TokenUsageLabel
                tokens={recursion.tokens}
                label={`${formatTokenCount(recursion.tokens.total_tokens)} tokens`}
              />
            )
          )}
          {canExpandDetails && (
            <ChevronRight
              className={`h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200 ${
                isExpanded ? "rotate-90" : ""
              }`}
            />
          )}
        </div>
      </button>

      {canExpandDetails && (
        <div
          className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
            isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
          }`}
        >
          <div className="overflow-hidden">
            <div className="px-1 pb-1 pt-1">
              <ExecutionDetails recursion={recursion} taskId={taskId} />
            </div>
          </div>
        </div>
      )}

      <ToolTimeline events={recursion.events} />
    </div>
  );
}
