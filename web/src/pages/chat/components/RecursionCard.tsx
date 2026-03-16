import {
  AlertCircle,
  Brain,
  CheckCircle2,
  Loader2,
  Wrench,
  XCircle,
} from "lucide-react";

import type { RecursionRecord } from "../types";
import {
  calculateDuration,
  formatTokenCount,
  getRecursionStatus,
} from "../utils/chatSelectors";
import { RecursionStateViewer } from "./RecursionStateViewer";
import { TokenUsageLabel } from "./TokenUsageLabel";

interface RecursionCardProps {
  messageId: string;
  recursion: RecursionRecord;
  taskId?: string;
  isExpanded: boolean;
  onToggle: (messageId: string, recursionUid: string) => void;
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
  const hasStartedGenerating =
    Boolean(
      recursion.observe ||
        recursion.thought ||
        recursion.abstract ||
        recursion.summary ||
        recursion.action,
    ) ||
    recursion.events.some(
      (event) =>
        !["recursion_start", "reasoning", "token_rate"].includes(event.type),
    );

  return (
    <div className="mb-3 overflow-hidden rounded-md border border-border bg-muted/20">
      <button
        onClick={() => onToggle(messageId, recursion.uid)}
        className="flex w-full items-center justify-between px-3 py-2 transition-colors hover:bg-muted/30"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {effectiveStatus === "running" && (
            <Loader2
              key={`${key}-running`}
              className="h-3.5 w-3.5 flex-shrink-0 animate-spin text-primary"
            />
          )}
          {effectiveStatus === "completed" && (
            <CheckCircle2
              key={`${key}-completed`}
              className="status-icon-enter h-3.5 w-3.5 flex-shrink-0 text-success"
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
          {effectiveStatus === "running" ? (
            <span
              className="animate-thinking-wave truncate text-xs font-semibold"
              style={{
                background:
                  "linear-gradient(90deg, #9ca3af 0%, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%, #9ca3af 100%)",
                backgroundClip: "text",
                backgroundSize: "400% 100%",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
              }}
            >
              {hasStartedGenerating ? "Generating..." : "Thinking..."}
            </span>
          ) : (
            <span
              className="truncate text-xs font-semibold text-foreground"
              title={recursion.abstract || `Iteration ${recursion.iteration + 1}`}
            >
              {recursion.abstract || `Iteration ${recursion.iteration + 1}`}
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

      {isExpanded && (
        <div className="space-y-2 px-3 pb-3">
          {recursion.thinking && (
            <div className="rounded border border-border bg-background/60 p-2">
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
            <div className="rounded border border-border bg-background/50 p-2">
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

          {recursion.thought && (
            <div className="rounded border border-border bg-background/50 p-2">
              <div className="mb-1 flex items-center gap-1.5">
                <Brain className="h-3.5 w-3.5 text-purple-500" />
                <span className="text-xs font-semibold text-foreground">
                  THOUGHT
                </span>
              </div>
              <p className="pl-5 text-xs leading-relaxed text-muted-foreground">
                {recursion.thought}
              </p>
            </div>
          )}

          {recursion.summary && (
            <div className="rounded border border-border bg-background/50 p-2">
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
            <div className="rounded border border-border bg-background/50 p-2">
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
              const toolData = event.data as
                | {
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
                  }
                | undefined;

              return (
                <div
                  key={index}
                  className="rounded border border-border bg-background/50 p-2"
                >
                  <div className="mb-2 flex items-center gap-1.5">
                    <Wrench className="h-3.5 w-3.5 text-orange-500" />
                    <span className="text-xs font-semibold text-foreground">
                      TOOL EXECUTION
                    </span>
                  </div>
                  <div className="space-y-3 pl-5">
                    {toolData?.tool_calls?.map((call, callIndex) => (
                      <div key={`call-${callIndex}`} className="space-y-1">
                        <div className="text-xs font-semibold text-foreground">
                          📥 Call: {call.name}
                        </div>
                        <div className="rounded border border-border/50 bg-muted/30 p-2 font-mono text-xs text-muted-foreground">
                          <div className="mb-1 text-[10px] text-muted-foreground/70">
                            Arguments:
                          </div>
                          {typeof call.arguments === "string"
                            ? call.arguments
                            : JSON.stringify(call.arguments, null, 2)}
                        </div>
                      </div>
                    ))}

                    {toolData?.tool_results?.map((result, resultIndex) => (
                      <div key={`result-${resultIndex}`} className="space-y-1">
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
                        {result.result !== undefined && result.result !== null && (
                          <div className="break-all rounded border border-border/50 bg-muted/30 p-2 font-mono text-xs text-muted-foreground">
                            {typeof result.result === "string"
                              ? result.result
                              : JSON.stringify(result.result, null, 2)}
                          </div>
                        )}
                        {result.error && (
                          <div className="rounded border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
                            {result.error}
                          </div>
                        )}
                      </div>
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
                  className="rounded border border-border bg-background/50 p-2"
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
      )}
    </div>
  );
}
