import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  CirclePlay,
  Clock,
  Loader2,
  Pencil,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  type ClientAutomation,
  type ClientAutomationRun,
  getClientAutomationRuns,
  triggerClientAutomation,
} from "@/client/api";
import type { Agent } from "@/types";
import { AutomationCreateDialog } from "@/components/AutomationCreateDialog";
import { LLMBrandAvatar } from "@/components/LLMBrandAvatar";
import { MarkdownRenderer } from "@/pages/chat/components/MarkdownRenderer";

/** Format an ISO timestamp into a short local string. */
function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Compute a human-readable duration between two ISO timestamps. */
function formatDuration(started: string | null, finished: string | null): string {
  if (!started || !finished) return "—";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms}ms`;
  const sec = Math.round(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const remSec = sec % 60;
  return `${min}m ${remSec}s`;
}

/** Map a run status to a Badge variant. */
function statusVariant(
  status: ClientAutomationRun["status"],
): "default" | "secondary" | "outline" | "destructive" {
  switch (status) {
    case "completed":
      return "default";
    case "running":
      return "outline";
    case "failed":
    case "timeout":
      return "destructive";
    default:
      return "secondary";
  }
}

/** Derive a short human-readable label from a cron expression. */
function cronToLabel(triggerConfig: string): string {
  try {
    const config = JSON.parse(triggerConfig) as { cron?: string };
    return config.cron ?? "Custom schedule";
  } catch {
    return "Custom schedule";
  }
}

interface ClientAutomationDetailViewProps {
  automation: ClientAutomation;
  agents: Agent[];
  onBack: () => void;
  onTriggered: () => void;
  /** Called when automation data is updated (edit save). */
  onUpdated?: () => void;
  /** Navigate to a specific session's chat view. */
  onNavigateToSession?: (agentId: number, sessionUuid: string) => void;
}

/** Detail view for a single automation with run history table. */
export function ClientAutomationDetailView({
  automation,
  agents,
  onBack,
  onTriggered,
  onUpdated,
  onNavigateToSession,
}: ClientAutomationDetailViewProps) {
  const [runs, setRuns] = useState<ClientAutomationRun[]>([]);
  const [totalRuns, setTotalRuns] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isTriggering, setIsTriggering] = useState(false);
  const [isEditOpen, setIsEditOpen] = useState(false);

  const agentName =
    agents.find((a) => a.id === automation.agent_id)?.name ?? "Unknown";

  const agent = agents.find((a) => a.id === automation.agent_id);

  const scheduleLabel = cronToLabel(automation.trigger_config);

  const fetchRuns = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await getClientAutomationRuns(automation.automation_id, 50, 0);
      setRuns(res.runs);
      setTotalRuns(res.total);
    } catch {
      toast.error("Failed to load run history");
    } finally {
      setIsLoading(false);
    }
  }, [automation.automation_id]);

  useEffect(() => {
    void fetchRuns();
  }, [fetchRuns]);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /** Poll a run until it reaches a terminal state, then show a toast. */
  const startPollingForRun = useCallback(
    (runId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);

      pollRef.current = setInterval(() => {
        void (async () => {
        try {
          const res = await getClientAutomationRuns(automation.automation_id, 50, 0);
          const run = res.runs.find((r) => r.run_id === runId);
          if (!run) return;

          if (run.status === "completed" || run.status === "failed" || run.status === "timeout") {
            if (pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
            await fetchRuns();

            const duration = formatDuration(run.started_at, run.finished_at);
            const isSuccess = run.status === "completed";
            const canView = run.session_uuid && onNavigateToSession;

            toast.custom(() => (
              <div
                className="flex w-full max-w-sm items-center gap-3 rounded-lg border bg-background p-3 shadow-lg"
                role="alert"
              >
                <div className="shrink-0">
                  <LLMBrandAvatar
                    model={agent?.model_name}
                    containerClassName="flex size-9 items-center justify-center rounded-lg bg-primary/10"
                    imageClassName="size-4"
                    fallback={<Bot className="size-4 text-primary" aria-hidden="true" />}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {automation.name}
                  </p>
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    {isSuccess ? (
                      <CheckCircle2 className="size-3 text-green-500" aria-hidden="true" />
                    ) : (
                      <XCircle className="size-3 text-destructive" aria-hidden="true" />
                    )}
                    <span className={isSuccess ? "text-green-600" : "text-destructive"}>
                      {isSuccess ? "Completed" : run.status === "timeout" ? "Timed out" : "Failed"}
                    </span>
                    <span>· {duration}</span>
                  </div>
                </div>
                {canView && (
                  <button
                    type="button"
                    className="shrink-0 text-xs font-medium text-primary hover:underline"
                    onClick={() => onNavigateToSession(automation.agent_id, run.session_uuid!)}
                  >
                    View →
                  </button>
                )}
              </div>
            ), { duration: 10000 });
          }
        } catch {
          // Silently retry on transient errors
        }
        })();
      }, 3000);
    },
    [automation.automation_id, automation.agent_id, automation.name, agent?.model_name, fetchRuns, onNavigateToSession],
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleTrigger = async () => {
    setIsTriggering(true);
    try {
      const run = await triggerClientAutomation(automation.automation_id);
      toast.success("Automation triggered");
      onTriggered();
      await fetchRuns();
      startPollingForRun(run.run_id);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to trigger automation",
      );
    } finally {
      setIsTriggering(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Header row: back + actions */}
      <div
        className="staggered-fade-in-card flex items-center justify-between"
        style={{ "--stagger-index": 0, "--list-card-stagger-step": "40ms", "--list-card-stagger-max-delay": "200ms" } as React.CSSProperties}
      >
        <Button asChild variant="ghost" className="-ml-3 w-fit">
          <button type="button" onClick={onBack}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Automations
          </button>
        </Button>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setIsEditOpen(true)}
          >
            <Pencil className="mr-1 h-3 w-3" />
            Edit
          </Button>
          <Button
            size="sm"
            onClick={() => void handleTrigger()}
            disabled={isTriggering || automation.status !== "active"}
          >
            {isTriggering ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <CirclePlay className="mr-1 h-3 w-3" />
            )}
            Trigger
          </Button>
        </div>
      </div>

      {/* Hero card — avatar, title, info fields */}
      <Card
        className="staggered-fade-in-card"
        style={{ "--stagger-index": 1, "--list-card-stagger-step": "40ms", "--list-card-stagger-max-delay": "200ms" } as React.CSSProperties}
      >
        <CardHeader className="space-y-4">
          <div className="flex items-start gap-4">
            <LLMBrandAvatar
              model={agent?.model_name}
              containerClassName="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10"
              imageClassName="size-6"
              fallback={<Bot className="size-5 text-primary" aria-hidden="true" />}
            />
            <div className="min-w-0 flex-1 space-y-1.5">
              <CardTitle className="min-w-0 text-xl">{automation.name}</CardTitle>
              <CardDescription className="text-sm">
                {automation.description || agentName}
              </CardDescription>
            </div>
          </div>
        </CardHeader>

        <Separator />

        <CardContent className="pt-4">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Status</p>
              <div className="text-sm">
                <Badge
                  variant={automation.status === "active" ? "default" : "secondary"}
                >
                  {automation.status}
                </Badge>
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Schedule</p>
              <div className="text-sm">
                <span className="inline-flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                  {scheduleLabel}
                </span>
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Context Strategy</p>
              <div className="text-sm">
                {automation.session_strategy === "reuse" ? "Continuous" : "Independent"}
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Timeout</p>
              <div className="text-sm">{automation.timeout_seconds}s</div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Last Run</p>
              <div className="text-sm">{formatTime(automation.last_run_at)}</div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground">Next Run</p>
              <div className="text-sm">{formatTime(automation.next_run_at)}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Card 2 — Prompt Template */}
      <Card
        className="staggered-fade-in-card"
        style={{ "--stagger-index": 2, "--list-card-stagger-step": "40ms", "--list-card-stagger-max-delay": "200ms" } as React.CSSProperties}
      >
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Prompt Template</CardTitle>
        </CardHeader>
        <CardContent>
          <MarkdownRenderer content={automation.prompt_template} />
        </CardContent>
      </Card>

      {/* Card 3 — Run History */}
      <Card
        className="staggered-fade-in-card"
        style={{ "--stagger-index": 3, "--list-card-stagger-step": "40ms", "--list-card-stagger-max-delay": "200ms" } as React.CSSProperties}
      >
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Run History ({totalRuns})</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : runs.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              No runs yet
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">#</TableHead>
                  <TableHead className="w-28">Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead className="w-20">Tokens</TableHead>
                  <TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((run, i) => {
                  let tokenCount = "—";
                  if (run.token_usage) {
                    try {
                      const usage = JSON.parse(run.token_usage) as {
                        prompt?: number;
                        completion?: number;
                      };
                      const total =
                        (usage.prompt ?? 0) + (usage.completion ?? 0);
                      tokenCount = total.toLocaleString();
                    } catch {
                      // keep "—"
                    }
                  }

                  const canViewChat =
                    !!run.session_uuid && !!onNavigateToSession;

                  return (
                    <TableRow
                      key={run.run_id}
                      className={canViewChat ? "cursor-pointer hover:bg-accent/50" : undefined}
                      onClick={() => {
                        if (canViewChat && run.session_uuid) {
                          onNavigateToSession(automation.agent_id, run.session_uuid);
                        }
                      }}
                    >
                      <TableCell className="text-muted-foreground">
                        {totalRuns - i}
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(run.status)}>
                          {run.status === "running" && (
                            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                          )}
                          {run.status}
                        </Badge>
                      </TableCell>
                      <TableCell>{formatTime(run.started_at)}</TableCell>
                      <TableCell>
                        {formatDuration(run.started_at, run.finished_at)}
                      </TableCell>
                      <TableCell>{tokenCount}</TableCell>
                      <TableCell className="max-w-[200px] truncate text-destructive">
                        {run.error_message || "—"}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Edit dialog */}
      <AutomationCreateDialog
        open={isEditOpen}
        automation={automation}
        agents={agents}
        onClose={() => setIsEditOpen(false)}
        onUpdated={() => {
          setIsEditOpen(false);
          onUpdated?.();
        }}
      />
    </div>
  );
}
