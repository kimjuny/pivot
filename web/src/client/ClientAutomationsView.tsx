import { useCallback, useEffect, useState } from "react";
import {
  Clock,
  Loader2,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Square,
  Trash2,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
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
  deleteClientAutomation,
  getClientAutomations,
  updateClientAutomation,
} from "@/client/api";
import type { Agent } from "@/types";
import { AutomationCreateDialog } from "@/components/AutomationCreateDialog";

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

    const [, hour, dayOfMonth, month, dayOfWeek] = parts;

    if (dayOfWeek !== "*" && dayOfMonth === "*" && month === "*") {
      const days = dayOfWeek.split(",").length;
      if (days === 5 && dayOfWeek.includes("-")) return `Weekdays at ${hour}:00`;
      if (days === 7 || dayOfWeek === "*") return `Daily at ${hour}:00`;
      return `Custom at ${hour}:00`;
    }
    if (dayOfMonth !== "*" && dayOfWeek === "*") return `Monthly at ${hour}:00`;
    if (dayOfMonth === "*" && dayOfWeek === "*" && month === "*") return `Daily at ${hour}:00`;
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
}

/**
 * Displays the user's automations with CRUD controls, triggered from the
 * Client sidebar "Automations" navigation item.
 */
export function ClientAutomationsView({ agents, defaultAgentId }: ClientAutomationsViewProps) {
  const [automations, setAutomations] = useState<ClientAutomation[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  const fetchAutomations = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await getClientAutomations(statusFilter || undefined);
      setAutomations(response.automations);
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
    } catch (err) {
      toast.error("Failed to update automation");
    }
  };

  const handleDelete = async (automation: ClientAutomation) => {
    try {
      await deleteClientAutomation(automation.automation_id);
      toast.success("Automation deleted");
      await fetchAutomations();
    } catch (err) {
      toast.error("Failed to delete automation");
    }
  };

  const agentMap = new Map(agents.map((a) => [a.id, a]));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 pb-5 md:flex-row md:items-center md:justify-between">
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

      {isLoading ? (
        <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Loading automations…</span>
        </div>
      ) : error ? (
        <div className="py-12 text-sm text-destructive">{error}</div>
      ) : automations.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <Clock className="h-10 w-10 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground">
            {statusFilter
              ? `No ${statusFilter} automations.`
              : "No automations yet. Create one to schedule recurring agent tasks."}
          </p>
          {!statusFilter && (
            <Button variant="outline" size="sm" onClick={() => setIsCreateOpen(true)}>
              <Plus className="mr-1 h-4 w-4" />
              Create Automation
            </Button>
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {automations.map((automation) => {
            const agent = agentMap.get(automation.agent_id);
            return (
              <Card key={automation.id}>
                <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-2">
                  <div className="flex items-center gap-3">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                      <Clock className="size-4 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-sm font-medium">
                        {automation.name}
                      </CardTitle>
                      {agent && (
                        <p className="text-xs text-muted-foreground">
                          Agent: {agent.name}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
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
                        <Button variant="ghost" size="icon" className="size-8">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() => void handlePauseResume(automation)}
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
                          onClick={() => {
                            toast.info("Manual trigger coming soon");
                          }}
                        >
                          <Zap className="mr-2 h-4 w-4" />
                          Trigger Now
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          className="text-destructive"
                          onClick={() => void handleDelete(automation)}
                        >
                          <Trash2 className="mr-2 h-4 w-4" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </CardHeader>
                <CardContent className="pb-3 pt-1">
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span>{cronToLabel(automation.trigger_config)}</span>
                    <span>
                      Last: {formatScheduleTime(automation.last_run_at)}
                    </span>
                    <span>
                      Next: {formatScheduleTime(automation.next_run_at)}
                    </span>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
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
