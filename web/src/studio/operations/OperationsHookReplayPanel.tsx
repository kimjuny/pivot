import { useCallback, useEffect, useState } from "react";

import { Eye, RefreshCcw } from "@/lib/lucide";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getExtensionHookExecutions,
  replayExtensionHookExecution,
  type ExtensionHookExecution,
  type ExtensionHookReplayResult,
} from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";
import type { OperationsTaskMessage } from "@/studio/operations/api";
import { toast } from "sonner";

interface OperationsHookReplayPanelProps {
  /** Session whose packaged hook executions should be inspected. */
  sessionId: string;
  /** Session tasks used to build task-level quick filters. */
  tasks: OperationsTaskMessage[];
  /** Optional externally requested focus used by diagnostics shortcuts. */
  focusRequest?: {
    taskId?: string | null;
    traceId?: string | null;
    iteration?: number | null;
  } | null;
}

/**
 * Render hook execution inspection and safe replay controls in Operations.
 *
 * Why: operators triage failures from the session detail page, so hook replay
 * needs to live close to session and task diagnostics instead of only inside a
 * global Extensions inventory screen.
 */
export function OperationsHookReplayPanel({
  sessionId,
  tasks,
  focusRequest,
}: OperationsHookReplayPanelProps) {
  const [selectedTaskId, setSelectedTaskId] = useState<string>("");
  const [selectedTraceId, setSelectedTraceId] = useState<string>("");
  const [selectedIteration, setSelectedIteration] = useState<number | null>(null);
  const [executions, setExecutions] = useState<ExtensionHookExecution[]>([]);
  const [selectedExecutionId, setSelectedExecutionId] = useState<number | null>(null);
  const [latestReplayResult, setLatestReplayResult] = useState<ExtensionHookReplayResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [replayingExecutionId, setReplayingExecutionId] = useState<number | null>(null);

  const availableTraces = tasks
    .filter((task) => selectedTaskId === "" || task.task_id === selectedTaskId)
    .flatMap((task) => task.recursions.map((recursion) => recursion.trace_id))
    .filter((traceId, index, values) => values.indexOf(traceId) === index)
    .slice(0, 8);

  const availableIterations = tasks
    .filter((task) => selectedTaskId === "" || task.task_id === selectedTaskId)
    .flatMap((task) =>
      task.recursions
        .filter((recursion) => selectedTraceId === "" || recursion.trace_id === selectedTraceId)
        .map((recursion) => recursion.iteration),
    )
    .filter((iteration, index, values) => values.indexOf(iteration) === index)
    .sort((left, right) => left - right)
    .slice(0, 8);

  const loadExecutions = useCallback(async () => {
    setLoading(true);
    try {
      const nextExecutions = await getExtensionHookExecutions({
        sessionId,
        taskId: selectedTaskId || undefined,
        traceId: selectedTraceId || undefined,
        iteration: selectedIteration ?? undefined,
        limit: 25,
      });
      setExecutions(nextExecutions);
    } catch (error) {
      console.error("Failed to load operations hook executions:", error);
      toast.error("Failed to load hook executions");
    } finally {
      setLoading(false);
    }
  }, [selectedIteration, selectedTaskId, selectedTraceId, sessionId]);

  useEffect(() => {
    void loadExecutions();
  }, [loadExecutions]);

  useEffect(() => {
    if (!focusRequest) {
      return;
    }
    setSelectedTaskId(focusRequest.taskId ?? "");
    setSelectedTraceId(focusRequest.traceId ?? "");
    setSelectedIteration(focusRequest.iteration ?? null);
    setSelectedExecutionId(null);
    setLatestReplayResult(null);
  }, [focusRequest]);

  const handleSelectTask = (taskId: string) => {
    setSelectedTaskId(taskId);
    setSelectedTraceId("");
    setSelectedIteration(null);
  };

  const handleSelectTrace = (traceId: string) => {
    setSelectedTraceId(traceId);
    setSelectedIteration(null);
  };

  const handleReplay = async (execution: ExtensionHookExecution) => {
    setReplayingExecutionId(execution.id);
    setSelectedExecutionId(execution.id);
    setLatestReplayResult(null);
    try {
      const replayResult = await replayExtensionHookExecution(execution.id);
      setLatestReplayResult(replayResult);
      toast.success(`Replayed ${execution.hook_event}`);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to replay hook execution",
      );
    } finally {
      setReplayingExecutionId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="space-y-2">
        <CardTitle className="text-sm font-semibold text-foreground">
          Hook Executions
        </CardTitle>
        <CardDescription>
          Inspect packaged lifecycle hook runs for this session and safely replay one exact
          historical invocation without re-emitting live task events.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant={selectedTaskId === "" ? "default" : "outline"}
            onClick={() => handleSelectTask("")}
          >
            All Tasks
          </Button>
          {tasks.slice(0, 8).map((task) => (
            <Button
              key={task.task_id}
              type="button"
              size="sm"
              variant={selectedTaskId === task.task_id ? "default" : "outline"}
              onClick={() => handleSelectTask(task.task_id)}
              className="max-w-[220px] truncate"
              title={task.user_message}
            >
              {task.task_id}
            </Button>
          ))}
        </div>

        {availableTraces.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant={selectedTraceId === "" ? "default" : "outline"}
              onClick={() => handleSelectTrace("")}
            >
              All Traces
            </Button>
            {availableTraces.map((traceId) => (
              <Button
                key={traceId}
                type="button"
                size="sm"
                variant={selectedTraceId === traceId ? "default" : "outline"}
                onClick={() => handleSelectTrace(traceId)}
                className="max-w-[220px] truncate"
                title={traceId}
              >
                {traceId}
              </Button>
            ))}
          </div>
        )}

        {availableIterations.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant={selectedIteration === null ? "default" : "outline"}
              onClick={() => setSelectedIteration(null)}
            >
              All Iterations
            </Button>
            {availableIterations.map((iteration) => (
              <Button
                key={iteration}
                type="button"
                size="sm"
                variant={selectedIteration === iteration ? "default" : "outline"}
                onClick={() => setSelectedIteration(iteration)}
              >
                Iteration {iteration}
              </Button>
            ))}
          </div>
        )}

        {loading ? (
          <div className="text-sm text-muted-foreground">Loading hook executions…</div>
        ) : executions.length === 0 ? (
          <div className="rounded-md border bg-background/60 px-4 py-3 text-sm text-muted-foreground">
            No packaged hook executions were recorded for the current session filter.
          </div>
        ) : (
          <div className="space-y-3">
            {executions.map((execution) => {
              const isSelected = selectedExecutionId === execution.id;
              const replayResult =
                latestReplayResult?.execution_id === execution.id ? latestReplayResult : null;

              return (
                <div
                  key={execution.id}
                  className="rounded-md border bg-background/60 px-3 py-3"
                >
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge
                          variant={execution.status === "succeeded" ? "default" : "outline"}
                        >
                          {execution.status}
                        </Badge>
                        <span className="text-sm font-medium text-foreground">
                          {execution.hook_event}
                        </span>
                        <Badge variant="outline">{execution.extension_package_id}</Badge>
                        <Badge variant="outline">{execution.extension_version}</Badge>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Task <code>{execution.task_id}</code>
                        {" · "}
                        Callable <code>{execution.hook_callable}</code>
                        {" · "}
                        Trace <code>{execution.trace_id ?? "n/a"}</code>
                        {" · "}
                        Iteration {execution.iteration}
                        {" · "}
                        {execution.duration_ms} ms
                      </div>
                      <div className="text-xs text-muted-foreground">
                        Ran {formatTimestamp(execution.started_at)}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setSelectedExecutionId(isSelected ? null : execution.id);
                          if (!isSelected) {
                            setLatestReplayResult(null);
                          }
                        }}
                      >
                        <Eye className="mr-2 h-4 w-4" />
                        {isSelected ? "Hide" : "Inspect"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => {
                          void handleReplay(execution);
                        }}
                        disabled={replayingExecutionId !== null}
                      >
                        <RefreshCcw className="mr-2 h-4 w-4" />
                        {replayingExecutionId === execution.id ? "Replaying…" : "Replay"}
                      </Button>
                    </div>
                  </div>

                  {isSelected && (
                    <div className="mt-4 grid gap-4 xl:grid-cols-2">
                      <div>
                        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                          Hook Context
                        </div>
                        <pre className="mt-2 max-h-72 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
                          {JSON.stringify(execution.hook_context ?? {}, null, 2)}
                        </pre>
                      </div>
                      <div>
                        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                          Live Result
                        </div>
                        <pre className="mt-2 max-h-72 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
                          {JSON.stringify({
                            effects: execution.effects,
                            error: execution.error,
                          }, null, 2)}
                        </pre>
                      </div>
                      {replayResult && (
                        <div className="xl:col-span-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                              Replay Result
                            </div>
                            <Badge
                              variant={replayResult.status === "succeeded" ? "default" : "outline"}
                            >
                              {replayResult.status}
                            </Badge>
                            <span className="text-xs text-muted-foreground">
                              Replayed {formatTimestamp(replayResult.replayed_at)}
                            </span>
                          </div>
                          <pre className="mt-2 max-h-72 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
                            {JSON.stringify({
                              effects: replayResult.effects,
                              error: replayResult.error,
                            }, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
