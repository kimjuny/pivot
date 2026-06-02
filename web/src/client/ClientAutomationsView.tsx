import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  Clock,
  CircleCheck,
  CircleOff,
  CirclePause,
  CirclePlay,
  Pause,
  Play,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

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
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination";
import {
  Table,
  TableBody,
  TableCell,
  TableRow,
} from "@/components/ui/table";
import {
  type ClientAutomation,
  deleteClientAutomation,
  getClientAgents,
  getClientAutomations,
  triggerClientAutomation,
  updateClientAutomation,
} from "@/client/api";
import type { Agent } from "@/types";
import { AutomationCreateDialog } from "@/components/AutomationCreateDialog";
import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import ConfirmationModal from "@/components/ConfirmationModal";
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
      if (days === 5 && dayOfWeek.includes("-")) return `Weekdays ${hour}:${minute.padStart(2, "0")}`;
      if (days === 7 || dayOfWeek === "*") return `Daily ${hour}:${minute.padStart(2, "0")}`;
      return `Custom ${hour}:${minute.padStart(2, "0")}`;
    }
    if (dayOfMonth !== "*" && dayOfWeek === "*") return `Monthly ${hour}:${minute.padStart(2, "0")}`;
    if (dayOfMonth === "*" && dayOfWeek === "*" && month === "*" && hour !== "*") return `Daily ${hour}:${minute.padStart(2, "0")}`;
    return cron;
  } catch {
    return "Custom schedule";
  }
}

const PAGE_SIZE = 10;

type StaggeredRowStyle = CSSProperties & {
  "--stagger-index": number;
  "--list-card-stagger-step": string;
  "--list-card-stagger-max-delay": string;
};

function buildPageList(current: number, total: number): (number | "ellipsis")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | "ellipsis")[] = [1];
  if (current > 3) pages.push("ellipsis");
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) pages.push(i);
  if (current < total - 2) pages.push("ellipsis");
  pages.push(total);
  return pages;
}

interface ClientAutomationsViewProps {
  defaultAgentId?: number;
  onNavigateToSession?: (agentId: number, sessionUuid: string) => void;
}

export function ClientAutomationsView({ defaultAgentId, onNavigateToSession }: ClientAutomationsViewProps) {
  const [automations, setAutomations] = useState<ClientAutomation[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingAgents, setIsLoadingAgents] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [selectedAutomation, setSelectedAutomation] =
    useState<ClientAutomation | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    automation: ClientAutomation | null;
  }>({ isOpen: false, automation: null });

  const fetchAutomations = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await getClientAutomations();
      setAutomations(response.automations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load automations");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAutomations();
  }, [fetchAutomations]);

  const totalPages = Math.max(1, Math.ceil(automations.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedAutomations = useMemo(
    () => automations.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    [automations, safePage],
  );
  const isInitialLoading = isLoading && automations.length === 0;

  const ensureAgentsLoaded = useCallback(async () => {
    if (agents.length > 0) return true;
    try {
      setIsLoadingAgents(true);
      setAgents(await getClientAgents());
      return true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load agents");
      return false;
    } finally {
      setIsLoadingAgents(false);
    }
  }, [agents.length]);

  const handleOpenCreate = async () => {
    if (await ensureAgentsLoaded()) {
      setIsCreateOpen(true);
    }
  };

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

  const confirmDelete = async () => {
    if (!deleteConfirmation.automation) return;
    try {
      await deleteClientAutomation(deleteConfirmation.automation.automation_id);
      setDeleteConfirmation({ isOpen: false, automation: null });
      toast.success("Automation deleted");
      await fetchAutomations();
    } catch {
      setDeleteConfirmation({ isOpen: false, automation: null });
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

  return (
    <div className="flex flex-col gap-6">
      {selectedAutomation ? (
        <ClientAutomationDetailView
          automation={selectedAutomation}
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
            <Button size="sm" onClick={() => void handleOpenCreate()} disabled={isLoadingAgents}>
              <Plus className="mr-1 h-4 w-4" />
              New
            </Button>
          </div>
        </div>

        {isInitialLoading ? (
          <CenteredLoadingIndicator label="Loading automations..." className="min-h-[70vh]" />
        ) : error ? (
          <div className="py-12 text-sm text-destructive">{error}</div>
        ) : automations.length === 0 ? (
          <Empty className="animate-in fade-in-0 slide-in-from-bottom-1 duration-200">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Clock className="size-6" />
              </EmptyMedia>
              <EmptyTitle>No automations yet</EmptyTitle>
              <EmptyDescription>
                Create one to schedule recurring agent tasks.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button size="sm" variant="outline" onClick={() => void handleOpenCreate()} disabled={isLoadingAgents}>
                <Plus className="mr-1 h-4 w-4" />
                Create Automation
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <>
            <Table>
              <TableBody>
                {pagedAutomations.map((automation, index) => {
                  const StatusIcon =
                    automation.status === "active"
                      ? CircleCheck
                      : automation.status === "paused"
                        ? CirclePause
                        : CircleOff;
                  const statusIconClassName =
                    automation.status === "disabled"
                      ? "text-destructive"
                      : "text-muted-foreground";
                  const rowStyle: StaggeredRowStyle = {
                    "--stagger-index": index,
                    "--list-card-stagger-step": "35ms",
                    "--list-card-stagger-max-delay": "160ms",
                  };
                  return (
                    <TableRow
                      key={automation.id}
                      className="staggered-fade-in-card group cursor-pointer hover:bg-muted"
                      style={rowStyle}
                      onClick={() => setSelectedAutomation(automation)}
                    >
                      {/* Name */}
                      <TableCell className="min-w-0 py-2.5">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <StatusIcon
                            className={`size-3.5 shrink-0 ${statusIconClassName}`}
                            aria-label={automation.status}
                          />
                          <span className="min-w-0 truncate text-sm font-medium">
                            {automation.name}
                          </span>
                        </div>
                      </TableCell>

                      {/* Status / Schedule / Last Run — visible by default, hidden on hover */}
                      <TableCell className="w-[300px] py-2.5">
                        <div className="relative flex min-h-7 items-center justify-end">
                          <div className="flex items-center justify-end gap-3 whitespace-nowrap text-xs text-muted-foreground transition-opacity duration-[180ms] group-hover:opacity-0 group-focus-within:opacity-0">
                            <span className="max-w-[120px] truncate">
                              {cronToLabel(automation.trigger_config)}
                            </span>
                            <span className="shrink-0">
                              {formatScheduleTime(automation.last_run_at)}
                            </span>
                          </div>

                          {/* Action buttons — hidden by default, visible on hover */}
                          <div className="absolute right-0 flex items-center gap-0.5 opacity-0 transition-opacity duration-[180ms] group-hover:opacity-100 group-focus-within:opacity-100">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              onClick={(e) => {
                                e.stopPropagation();
                                void handlePauseResume(automation);
                              }}
                            >
                              {automation.status === "active" ? (
                                <Pause className="size-3.5" />
                              ) : (
                                <Play className="size-3.5" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7"
                              onClick={(e) => {
                                e.stopPropagation();
                                void handleTrigger(automation);
                              }}
                            >
                              <CirclePlay className="size-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-7 text-destructive hover:text-destructive"
                              onClick={(e) => {
                                e.stopPropagation();
                                setDeleteConfirmation({ isOpen: true, automation });
                              }}
                            >
                              <Trash2 className="size-3.5" />
                            </Button>
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="mt-2 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  {automations.length} automation{automations.length !== 1 ? "s" : ""}
                </span>
                <Pagination className="w-auto mx-0 justify-end">
                  <PaginationContent>
                    <PaginationItem>
                      <PaginationPrevious
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          if (safePage > 1) setCurrentPage((p) => p - 1);
                        }}
                        className={safePage === 1 ? "pointer-events-none opacity-50" : ""}
                      />
                    </PaginationItem>

                    {buildPageList(safePage, totalPages).map((page, idx) =>
                      page === "ellipsis" ? (
                        <PaginationItem key={`ellipsis-${idx}`}>
                          <PaginationEllipsis />
                        </PaginationItem>
                      ) : (
                        <PaginationItem key={page}>
                          <PaginationLink
                            href="#"
                            isActive={page === safePage}
                            onClick={(e) => {
                              e.preventDefault();
                              setCurrentPage(page);
                            }}
                          >
                            {page}
                          </PaginationLink>
                        </PaginationItem>
                      ),
                    )}

                    <PaginationItem>
                      <PaginationNext
                        href="#"
                        onClick={(e) => {
                          e.preventDefault();
                          if (safePage < totalPages) setCurrentPage((p) => p + 1);
                        }}
                        className={safePage === totalPages ? "pointer-events-none opacity-50" : ""}
                      />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
              </div>
            )}
          </>
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

      <ConfirmationModal
        isOpen={deleteConfirmation.isOpen}
        title="Delete Automation"
        message={`Are you sure you want to delete "${deleteConfirmation.automation?.name}"? This action cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteConfirmation({ isOpen: false, automation: null })}
        variant="danger"
      />
    </div>
  );
}
