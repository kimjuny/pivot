import { useCallback, useEffect, useState } from "react";

import { Eye, RefreshCcw, Search } from "@/lib/lucide";
import { toast } from "sonner";

import ExtensionHookExecutionDialog from "@/components/ExtensionHookExecutionDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  getExtensionHookExecutions,
  replayExtensionHookExecution,
  type ExtensionHookExecution,
  type ExtensionHookReplayResult,
} from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

interface ExtensionHookReplayPanelProps {
  /** Canonical package id such as `@acme/memory`. */
  packageId: string;
}

interface HookExecutionFilters {
  /** Optional task identifier used to narrow one package's logs. */
  taskId: string;
  /** Optional hook event name filter such as `task.completed`. */
  hookEvent: string;
}

/**
 * Render package-scoped hook execution logs and safe replay actions.
 *
 * Why: extension-level debugging belongs with the package that owns the hooks,
 * while Operations keeps the session-first diagnostics workflow.
 */
export default function ExtensionHookReplayPanel({
  packageId,
}: ExtensionHookReplayPanelProps) {
  const [filters, setFilters] = useState<HookExecutionFilters>({
    taskId: "",
    hookEvent: "",
  });
  const [executions, setExecutions] = useState<ExtensionHookExecution[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedExecution, setSelectedExecution] = useState<ExtensionHookExecution | null>(null);
  const [latestReplayResult, setLatestReplayResult] = useState<ExtensionHookReplayResult | null>(
    null,
  );
  const [isReplaying, setIsReplaying] = useState(false);

  const loadExecutions = useCallback(async () => {
    setIsLoading(true);
    try {
      const nextExecutions = await getExtensionHookExecutions({
        extensionPackageId: packageId,
        taskId: filters.taskId.trim() || undefined,
        hookEvent: filters.hookEvent.trim() || undefined,
        limit: 25,
      });
      setExecutions(nextExecutions);
    } catch (error) {
      console.error("Failed to load package hook executions:", error);
      toast.error("Failed to load hook executions");
    } finally {
      setIsLoading(false);
    }
  }, [filters.hookEvent, filters.taskId, packageId]);

  useEffect(() => {
    void loadExecutions();
  }, [loadExecutions]);

  const handleReplay = async (execution: ExtensionHookExecution) => {
    setIsReplaying(true);
    setSelectedExecution(execution);
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
      setIsReplaying(false);
    }
  };

  return (
    <>
      <Card>
        <CardHeader className="space-y-2">
          <CardTitle className="text-base">Hook Replay</CardTitle>
          <CardDescription>
            Inspect lifecycle hooks that belong to this package and safely replay one exact
            historical invocation without re-emitting live task events.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row">
            <Input
              placeholder="Filter by task id…"
              value={filters.taskId}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  taskId: event.target.value,
                }))
              }
              aria-label="Filter extension hook executions by task id"
              autoComplete="off"
            />
            <Input
              placeholder="Filter by hook event…"
              value={filters.hookEvent}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  hookEvent: event.target.value,
                }))
              }
              aria-label="Filter extension hook executions by hook event"
              autoComplete="off"
            />
            <Button type="button" variant="outline" onClick={() => void loadExecutions()}>
              <Search className="mr-2 h-4 w-4" />
              {isLoading ? "Loading…" : "Load Logs"}
            </Button>
          </div>

          {isLoading ? (
            <div className="text-sm text-muted-foreground">Loading hook executions…</div>
          ) : executions.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              No hook executions found for this extension and the current filters.
            </div>
          ) : (
            <div className="space-y-3">
              {executions.map((execution) => (
                <div
                  key={execution.id}
                  className="flex flex-col gap-3 rounded-lg border border-border p-3 lg:flex-row lg:items-start lg:justify-between"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={execution.status === "succeeded" ? "default" : "outline"}>
                        {execution.status}
                      </Badge>
                      <span className="text-sm font-medium text-foreground">
                        {execution.hook_event}
                      </span>
                      <Badge variant="outline">{execution.extension_version}</Badge>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      Task <code>{execution.task_id}</code>
                      {" · "}
                      Callable <code>{execution.hook_callable}</code>
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
                        setSelectedExecution(execution);
                        setLatestReplayResult(null);
                      }}
                    >
                      <Eye className="mr-2 h-4 w-4" />
                      Inspect
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => {
                        void handleReplay(execution);
                      }}
                      disabled={isReplaying}
                    >
                      <RefreshCcw className="mr-2 h-4 w-4" />
                      {isReplaying && selectedExecution?.id === execution.id
                        ? "Replaying…"
                        : "Replay"}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <ExtensionHookExecutionDialog
        open={selectedExecution !== null}
        execution={selectedExecution}
        latestReplayResult={latestReplayResult}
        isReplaying={isReplaying}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedExecution(null);
            setLatestReplayResult(null);
          }
        }}
        onReplay={handleReplay}
      />
    </>
  );
}
