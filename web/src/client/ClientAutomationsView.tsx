import { useCallback, useEffect, useState } from "react";
import {
  Clock,
  Loader2,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Trash2,
  CirclePlay,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  type ClientAutomation,
  type ClientAutomationStats,
  deleteClientAutomation,
  getClientAutomations,
  getClientAutomationStats,
  triggerClientAutomation,
  updateClientAutomation,
} from "@/client/api";
import type { Agent } from "@/types";
import { AutomationCreateDialog } from "@/components/AutomationCreateDialog";
import { ClientAutomationDetailView } from "./ClientAutomationDetailView";

/** Format an ISO string into a human-friendly relative/local string. */
function formatScheduleTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Derive a short human-readable label from a cron expression. */
interface TriggerConfig {
  cron?: string;
  timezone?: string;
}

function cronToLabel(triggerConfig: string): string {
  try {
    const config = JSON.parse(triggerConfig) as TriggerConfig;
    const cron = config.cron ?? "";
    const parts = cron.split(/\s+/);
    if (parts.length !== 5) return cron;

    const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

    // Interval patterns: */N in minute or hour position.
    const intervalMin = /^\*\/(\d+)$/.exec(minute);
    const intervalHour = /^\*\/(\d+)$/.exec(hour);
    if (intervalMin && hour === "*" && dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
      return `Every ${intervalMin[1]} min`;
    }
    if (intervalHour && minute !== "*" && dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
      return `Every ${intervalHour[1]}h at :${minute}`;
    }

    if (dayOfWeek !== "*" && dayOfMonth === "*" && month === "*") {
      const days = dayOfWeek.split(",").length;
      if (days === 5 && dayOfWeek.includes("-")) return `Weekdays at ${hour}:${minute.padStart(2, "0")}`;
      if (days === 7 || dayOfWeek === "*") return `Daily at ${hour}:${minute.padStart(2, "0")}`;
      return `Custom at ${hour}:${minute.padStart(2, "0")}`;
    }
    if (dayOfMonth !== "*" && dayOfWeek === "*") return `Monthly at ${hour}:${minute.padStart(2, "0")}`;
    if (dayOfMonth === "*" && dayOfWeek === "*" && month === "*" && hour !== "*") return `Daily at ${hour}:${minute.padStart(2, "0")}`;
    return cron;
  } catch {
    return "Custom schedule";
  }
}

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
] as const;

interface ClientAutomationsViewProps {
  agents: Agent[];
  defaultAgentId?: number;
  onNavigateToSession?: (agentId: number, sessionUuid: string) => void;
}

/**
 * Displays the user's automations with CRUD controls, triggered from the
 * Client sidebar "Automations" navigation item.
 */
export function ClientAutomationsView({ agents, defaultAgentId, onNavigateToSession }: ClientAutomationsViewProps) {
  const [automations, setAutomations] = useState<ClientAutomation[]>([]);
  const [stats, setStats] = useState<ClientAutomationStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [selectedAutomation, setSelectedAutomation] =
    useState<ClientAutomation | null>(null);

  const fetchAutomations = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const [response, statsRes] = await Promise.all([
        getClientAutomations(statusFilter || undefined),
        getClientAutomationStats(),
      ]);
      setAutomations(response.automations);
      setStats(statsRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load automations");
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void fetchAutomations();
  }, [fetchAutomations]);

  const handlePauseResume = async (automation: ClientAutomation) => {
    const newStatus = automation.status === "active" ? "paused" : "active";
    try {
      await updateClientAutomation(automation.automation_id, { status: newStatus });
      toast.success(newStatus === "paused" ? "Automation paused" : "Automation resumed");
      await fetchAutomations();
    } catch {
      toast.error("Failed to update automation");
    }
  };

  const handleDelete = async (automation: ClientAutomation) => {
    try {
      await deleteClientAutomation(automation.automation_id);
      toast.success("Automation deleted");
      await fetchAutomations();
    } catch {
      toast.error("Failed to delete automation");
    }
  };

  const handleTrigger = async (automation: ClientAutomation) => {
    try {
      await triggerClientAutomation(automation.automation_id);
      toast.success("Automation triggered");
      await fetchAutomations();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to trigger automation",
      );
    }
  };

  const agentMap = new Map(agents.map((a) => [a.id, a]));

  return (
    <div className="flex flex-col gap-6">
      {selectedAutomation ? (
        <ClientAutomationDetailView
          automation={selectedAutomation}
          agents={agents}
          onNavigateToSession={onNavigateToSession}
          onBack={() => {
            void fetchAutomations();
            setSelectedAutomation(null);
          }}
          onTriggered={() => void fetchAutomations()}
          onUpdated={() => void fetchAutomations().then(() => {
            setAutomations((prev) => {
              const updated = prev.find((a) => a.id === selectedAutomation.id);
              if (updated) setSelectedAutomation(updated);
              return prev;
            });
          })}
        />
      ) : (
      <>
        <div className="flex flex-col gap-4 pb-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              Automations
            </h1>
            <p className="text-sm text-muted-foreground">
              Schedule recurring tasks with your agents.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex gap-1">
              {STATUS_FILTERS.map((filter) => (
                <Button
                  key={filter.value}
                  variant={statusFilter === filter.value ? "default" : "outline"}
                  size="sm"
                  onClick={() => setStatusFilter(filter.value)}
                >
                  {filter.label}
                </Button>
              ))}
            </div>
            <Button size="sm" onClick={() => setIsCreateOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              New
            </Button>
          </div>
        </div>

        {stats && (
          <div className="flex gap-6 rounded-lg border bg-muted/30 px-4 py-3 text-sm">
            <div>
              <span className="text-muted-foreground">Active</span>{" "}
              <span className="font-medium">{stats.active_count}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Runs (7d)</span>{" "}
              <span className="font-medium">{stats.runs_last_7_days}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Success</span>{" "}
              <span className="font-medium">{stats.success_rate}%</span>
            </div>
            <div>
              <span className="text-muted-foreground">Tokens (7d)</span>{" "}
              <span className="font-medium">{stats.total_tokens_last_7_days.toLocaleString()}</span>
            </div>
          </div>
        )}

        {isLoading ? (
          <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Loading automations...</span>
          </div>
        ) : error ? (
          <div className="py-12 text-sm text-destructive">{error}</div>
        ) : automations.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Clock className="size-6" />
              </EmptyMedia>
              {statusFilter ? (
                <>
                  <EmptyTitle>No {statusFilter} automations</EmptyTitle>
                  <EmptyDescription>
                    No automations match the selected filter.
                  </EmptyDescription>
                </>
              ) : (
                <>
                  <EmptyTitle>No automations yet</EmptyTitle>
                  <EmptyDescription>
                    Create one to schedule recurring agent tasks.
                  </EmptyDescription>
                </>
              )}
            </EmptyHeader>
            {!statusFilter && (
              <EmptyContent>
                <Button size="sm" variant="outline" onClick={() => setIsCreateOpen(true)}>
                  <Plus className="mr-1 h-4 w-4" />
                  Create Automation
                </Button>
              </EmptyContent>
            )}
          </Empty>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {automations.map((automation) => {
              const agent = agentMap.get(automation.agent_id);
              return (
                <Card
                  key={automation.id}
                  className="cursor-pointer transition-colors hover:bg-accent/30"
                  onClick={() => setSelectedAutomation(automation)}
                >
                  <CardHeader className="space-y-2 p-4 pb-2">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                          <Clock className="size-4 text-primary" />
                        </div>
                        <div className="min-w-0 space-y-0.5">
                          <p className="truncate text-sm font-medium">
                            {automation.name}
                          </p>
                          {agent && (
                            <p className="truncate text-xs text-muted-foreground">
                              {agent.name}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        <Badge
                          variant={
                            automation.status === "active"
                              ? "default"
                              : automation.status === "paused"
                                ? "secondary"
                                : "outline"
                          }
                        >
                          {automation.status}
                        </Badge>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                void handlePauseResume(automation);
                              }}
                            >
                              {automation.status === "active" ? (
                                <>
                                  <Pause className="mr-2 h-4 w-4" />
                                  Pause
                                </>
                              ) : (
                                <>
                                  <Play className="mr-2 h-4 w-4" />
                                  Resume
                                </>
                              )}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleTrigger(automation);
                              }}
                            >
                              <CirclePlay className="mr-2 h-4 w-4" />
                              Trigger Now
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              className="text-destructive"
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleDelete(automation);
                              }}
                            >
                              <Trash2 className="mr-2 h-4 w-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="px-4 pb-3 pt-0">
                    <div className="flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{cronToLabel(automation.trigger_config)}</span>
                      {automation.last_run_at && (
                        <span>Last: {formatScheduleTime(automation.last_run_at)}</span>
                      )}
                      {automation.next_run_at && (
                        <span>Next: {formatScheduleTime(automation.next_run_at)}</span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </>
      )}

      <AutomationCreateDialog
        open={isCreateOpen}
        agents={agents}
        defaultAgentId={defaultAgentId}
        onClose={() => setIsCreateOpen(false)}
        onCreated={() => {
          setIsCreateOpen(false);
          void fetchAutomations();
        }}
      />
    </div>
  );
}
