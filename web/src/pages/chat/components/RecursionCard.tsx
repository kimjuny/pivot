import { useState } from "react";

import {
  AlertCircle,
  Brain,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Square,
  Wrench,
  XCircle,
} from "@/lib/lucide";

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
    result?: unknown;
    error?: string;
    success: boolean;
  }>;
  pendingResultCount: number;
  isWaiting: boolean;
}

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
            result?: unknown;
            error?: string;
            success: boolean;
          }>;
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
    pendingResultCount,
    isWaiting: toolCalls.length > 0 && pendingResultCount > 0,
  };
}

/** Shared wrapper for collapsible content with 200ms grid-row animation. */
function CollapsePanel({
  defaultOpen = false,
  trigger,
  children,
}: {
  defaultOpen?: boolean;
  trigger: React.ReactNode;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center gap-1 text-left"
      >
        <ChevronRight
          className={`h-3 w-3 shrink-0 transition-transform duration-200 ${
            open ? "rotate-90" : ""
          }`}
        />
        {trigger}
      </button>
      <div
        className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="rounded bg-muted/30 p-2">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Collapsible wrapper for a single tool call's arguments. */
function CollapsibleCallDetail({
  defaultOpen = false,
  label,
  children,
}: {
  defaultOpen?: boolean;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <CollapsePanel
      defaultOpen={defaultOpen}
      trigger={<span className="text-xs font-semibold text-foreground">{label}</span>}
    >
      {children}
    </CollapsePanel>
  );
}

/** Collapsible wrapper for a single tool result's body. */
function CollapsibleResultDetail({
  defaultOpen = false,
  result,
}: {
  defaultOpen?: boolean;
  result: {
    name: string;
    result?: unknown;
    error?: string;
    success: boolean;
  };
}) {
  const hasContent =
    result.result !== undefined && result.result !== null;
  const hasError = Boolean(result.error);

  return (
    <CollapsePanel
      defaultOpen={defaultOpen}
      trigger={
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-foreground">
            📤 Result: {result.name}
          </span>
          {result.success ? (
            <span className="rounded bg-success/10 px-1.5 py-0.5 text-xs text-success">
              ✓
            </span>
          ) : (
            <span className="rounded bg-danger/10 px-1.5 py-0.5 text-xs text-danger">
              ✗
            </span>
          )}
        </div>
      }
    >
      {hasContent && (
        <div className="break-all font-mono text-xs text-muted-foreground">
          {typeof result.result === "string"
            ? result.result
            : JSON.stringify(result.result, null, 2)}
        </div>
      )}
      {hasError && (
        <div className="rounded border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
          {result.error}
        </div>
      )}
    </CollapsePanel>
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
  const toolCallEvents = recursion.events.filter((event) => event.type === "tool_call");
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
    `Iteration ${recursion.iteration + 1}`;

  return (
    <div className="mb-3 overflow-hidden rounded-md bg-muted/20">
      <button
        onClick={() => onToggle(messageId, recursion.uid)}
        className="flex w-full items-center justify-between px-3 py-2 transition-colors hover:bg-muted/30"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {effectiveStatus === "running" && (
            <Loader2
              key={`${key}-running`}
              className="h-3.5 w-3.5 flex-shrink-0 animate-spin text-sidebar-foreground/60"
            />
          )}
          {effectiveStatus === "completed" && (
            <CheckCircle2
              key={`${key}-completed`}
              className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-muted-foreground"
            />
          )}
          {effectiveStatus === "warning" && (
            <AlertCircle
              key={`${key}-warning`}
              className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-warning"
            />
          )}
          {effectiveStatus === "error" && (
            <XCircle
              key={`${key}-error`}
              className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-danger"
            />
          )}
          {effectiveStatus === "stopped" && (
            <Square
              key={`${key}-stopped`}
              className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-muted-foreground"
            />
          )}
          {effectiveStatus === "running" ? (
            shouldShowPendingTicker ? (
              <ThinkingWordTicker className="truncate text-xs font-semibold text-muted-foreground" />
            ) : (
              <span
                className="truncate text-xs font-semibold text-foreground"
                title={stableRunningLabel}
              >
                {stableRunningLabel}
              </span>
            )
          ) : (
            <span
              className="truncate text-xs font-semibold text-foreground"
              title={recursion.summary || `Iteration ${recursion.iteration + 1}`}
            >
              {recursion.summary || `Iteration ${recursion.iteration + 1}`}
            </span>
          )}
          {toolCallEvents.length > 0 && (
            <span className="flex-shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
              {toolCallEvents.length} tool{toolCallEvents.length > 1 ? "s" : ""}
            </span>
          )}
        </div>
        <div className="flex flex-shrink-0 items-center gap-2.5">
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
        </div>
      </button>

      <div
        className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
          isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="overflow-hidden">
          <div className="space-y-2 px-3 pb-3">
          {recursion.thinking && (
            <div className="rounded bg-background/60 p-2">
              <div className="mb-1.5 flex items-center gap-1.5">
                <Brain className="h-3.5 w-3.5 text-primary" />
                <span className="text-xs font-semibold text-foreground">
                  THINKING
                </span>
              </div>
              <div className="max-h-64 overflow-y-auto break-words whitespace-pre-wrap pl-5 pr-1 text-xs leading-relaxed text-muted-foreground">
                {recursion.thinking}
              </div>
            </div>
          )}

          {recursion.observe && (
            <div className="rounded bg-background/50 p-2">
              <div className="mb-1 flex items-center gap-1.5">
                <div className="flex h-3.5 w-3.5 items-center justify-center">
                  <div className="h-4 w-1 rounded-full bg-blue-500" />
                </div>
                <span className="text-xs font-semibold text-foreground">
                  OBSERVE
                </span>
              </div>
              <p className="pl-5 text-xs leading-relaxed text-muted-foreground">
                {recursion.observe}
              </p>
            </div>
          )}

          {recursion.reason && (
            <div className="rounded bg-background/50 p-2">
              <div className="mb-1 flex items-center gap-1.5">
                <Brain className="h-3.5 w-3.5 text-purple-500" />
                <span className="text-xs font-semibold text-foreground">
                  REASON
                </span>
              </div>
              <p className="pl-5 text-xs leading-relaxed text-muted-foreground">
                {recursion.reason}
              </p>
            </div>
          )}

          {recursion.summary && (
            <div className="rounded bg-background/50 p-2">
              <div className="mb-1 flex items-center gap-1.5">
                <div className="flex h-3.5 w-3.5 items-center justify-center">
                  <div className="h-4 w-1 rounded-full bg-amber-500" />
                </div>
                <span className="text-xs font-semibold text-foreground">
                  SUMMARY
                </span>
              </div>
              <p className="pl-5 text-xs leading-relaxed text-muted-foreground">
                {recursion.summary}
              </p>
            </div>
          )}

          {recursion.action && (
            <div className="rounded bg-background/50 p-2">
              <div className="mb-1 flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className="flex h-3.5 w-3.5 items-center justify-center">
                    <div className="h-4 w-1 rounded-full bg-green-500" />
                  </div>
                  <span className="text-xs font-semibold text-foreground">
                    ACTION
                  </span>
                </div>
                {taskId && (
                  <RecursionStateViewer
                    taskId={taskId}
                    iteration={recursion.iteration}
                  />
                )}
              </div>
              <p className="pl-5 font-mono text-xs text-primary">
                {recursion.action}
              </p>
            </div>
          )}

          {recursion.events.map((event, index) => {
            if (event.type === "tool_call") {
              const toolSnapshot = getToolExecutionSnapshot(event.data);

              return (
                <div
                  key={index}
                  className="rounded bg-background/50 p-2"
                >
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <Wrench className="h-3.5 w-3.5 text-orange-500" />
                      <span className="text-xs font-semibold text-foreground">
                        TOOL EXECUTION
                      </span>
                    </div>
                    {toolSnapshot.isWaiting && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-orange-500/10 px-2 py-0.5 text-[11px] font-medium text-orange-600">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Running...
                      </span>
                    )}
                  </div>
                  <div className="space-y-3 pl-5">
                    {toolSnapshot.isWaiting && (
                      <div className="flex items-center gap-2 rounded border border-dashed border-orange-500/30 bg-orange-500/5 px-2.5 py-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-orange-500" />
                        <span>
                          {toolSnapshot.pendingResultCount ===
                          toolSnapshot.toolCalls.length
                            ? "Waiting for tool result..."
                            : `Waiting for ${toolSnapshot.pendingResultCount} tool result${
                                toolSnapshot.pendingResultCount > 1 ? "s" : ""
                              }...`}
                        </span>
                      </div>
                    )}

                    {toolSnapshot.toolCalls.map((call, callIndex) => (
                      <CollapsibleCallDetail
                        key={`call-${callIndex}`}
                        label={`📥 Call: ${call.name}`}
                        defaultOpen={false}
                      >
                        <div className="mb-1 text-[10px] text-muted-foreground/70">
                          Arguments:
                        </div>
                        <div className="font-mono text-xs text-muted-foreground">
                          {typeof call.arguments === "string"
                            ? call.arguments
                            : JSON.stringify(call.arguments, null, 2)}
                        </div>
                      </CollapsibleCallDetail>
                    ))}

                    {toolSnapshot.toolResults.map((result, resultIndex) => (
                      <CollapsibleResultDetail
                        key={`result-${resultIndex}`}
                        result={result}
                      />
                    ))}
                  </div>
                </div>
              );
            }

            if (event.type === "plan_update") {
              return null;
            }

            if (event.type === "reflect") {
              const reflectData = event.data as { summary?: string } | undefined;

              return (
                <div
                  key={index}
                  className="rounded bg-background/50 p-2"
                >
                  <div className="mb-2 flex items-center gap-1.5">
                    <Brain className="h-3.5 w-3.5 text-indigo-500" />
                    <span className="text-xs font-semibold text-foreground">
                      REFLECT
                    </span>
                  </div>
                  <div className="pl-5 text-xs leading-relaxed text-muted-foreground">
                    {reflectData?.summary || "Reflecting on current state..."}
                  </div>
                </div>
              );
            }

            if (event.type === "error") {
              const errorData = event.data as { error?: string } | undefined;

              return (
                <div
                  key={index}
                  className="rounded border border-danger/30 bg-danger/5 p-2"
                >
                  <div className="mb-1 flex items-center gap-1.5">
                    <XCircle className="h-3.5 w-3.5 text-danger" />
                    <span className="text-xs font-semibold text-danger">
                      ERROR
                    </span>
                  </div>
                  <div className="pl-5 text-xs text-danger/90">
                    {errorData?.error || "Unknown error"}
                  </div>
                </div>
              );
            }

            return null;
          })}

          {recursion.errorLog && (
            <div className="rounded border border-danger/30 bg-danger/5 p-2">
              <div className="mb-1 flex items-center gap-1.5">
                <XCircle className="h-3.5 w-3.5 text-danger" />
                <span className="text-xs font-semibold text-danger">
                  ERROR LOG
                </span>
              </div>
              <div className="pl-5 text-xs leading-relaxed text-danger/90">
                {recursion.errorLog}
              </div>
            </div>
          )}
        </div>
        </div>
      </div>
    </div>
  );
}
