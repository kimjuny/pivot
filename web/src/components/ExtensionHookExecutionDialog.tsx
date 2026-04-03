import { RefreshCcw } from "@/lib/lucide";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type {
  ExtensionHookExecution,
  ExtensionHookReplayResult,
} from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

interface ExtensionHookExecutionDialogProps {
  /** Whether the inspection dialog is visible. */
  open: boolean;
  /** Historical execution currently being inspected. */
  execution: ExtensionHookExecution | null;
  /** Latest safe replay result for the selected execution. */
  latestReplayResult: ExtensionHookReplayResult | null;
  /** Whether the dialog is waiting for a replay response. */
  isReplaying: boolean;
  /** Toggle callback controlled by the parent page or panel. */
  onOpenChange: (open: boolean) => void;
  /** Trigger one safe replay for the selected execution. */
  onReplay: (execution: ExtensionHookExecution) => void | Promise<void>;
}

/**
 * Render the full historical hook payload plus optional replay output.
 *
 * Why: extension authors need the exact structured payload that reached the
 * hook runtime so they can compare live behavior with replay behavior without
 * reconstructing state from unrelated logs.
 */
export default function ExtensionHookExecutionDialog({
  open,
  execution,
  latestReplayResult,
  isReplaying,
  onOpenChange,
  onReplay,
}: ExtensionHookExecutionDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !isReplaying) {
          onOpenChange(false);
        }
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Hook Execution Details</DialogTitle>
          <DialogDescription>
            Inspect the recorded hook context, returned effects, and an optional safe replay
            result for one packaged lifecycle hook.
          </DialogDescription>
        </DialogHeader>

        {execution ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/30 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={execution.status === "succeeded" ? "default" : "outline"}>
                  {execution.status}
                </Badge>
                <Badge variant="outline">{execution.extension_package_id}</Badge>
                <Badge variant="outline">{execution.extension_version}</Badge>
                <Badge variant="outline">{execution.hook_event}</Badge>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Task <code>{execution.task_id}</code>
                {" · "}
                Callable <code>{execution.hook_callable}</code>
                {" · "}
                Iteration {execution.iteration}
                {" · "}
                {execution.duration_ms} ms
              </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-border p-3">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Hook Context
                </div>
                <pre className="mt-3 max-h-80 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
                  {JSON.stringify(execution.hook_context ?? {}, null, 2)}
                </pre>
              </div>
              <div className="rounded-lg border border-border p-3">
                <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Live Result
                </div>
                <pre className="mt-3 max-h-80 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
                  {JSON.stringify(
                    {
                      effects: execution.effects,
                      error: execution.error,
                    },
                    null,
                    2,
                  )}
                </pre>
              </div>
            </div>

            {latestReplayResult && latestReplayResult.execution_id === execution.id ? (
              <div className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Replay Result
                  </div>
                  <Badge
                    variant={latestReplayResult.status === "succeeded" ? "default" : "outline"}
                  >
                    {latestReplayResult.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    Replayed {formatTimestamp(latestReplayResult.replayed_at)}
                  </span>
                </div>
                <pre className="mt-3 max-h-80 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
                  {JSON.stringify(
                    {
                      effects: latestReplayResult.effects,
                      error: latestReplayResult.error,
                    },
                    null,
                    2,
                  )}
                </pre>
              </div>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isReplaying}
          >
            Close
          </Button>
          <Button
            type="button"
            onClick={() => {
              if (execution) {
                void onReplay(execution);
              }
            }}
            disabled={execution === null || isReplaying}
          >
            <RefreshCcw className="mr-2 h-4 w-4" />
            {isReplaying ? "Replaying…" : "Replay Hook"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
