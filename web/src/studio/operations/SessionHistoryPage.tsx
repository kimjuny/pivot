/**
 * Studio Operations — Session History list page.
 *
 * Displays a paginated, filterable table of all sessions across every user
 * and agent so administrators can inspect production traffic.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { cn } from "@/lib/utils";
import { getAgents } from "@/utils/api";
import type { Agent } from "@/types";
import {
  listOperationsSessions,
  type OperationsSession,
} from "@/studio/operations/api";
import { formatTimestamp } from "@/utils/timestamp";
import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  FileText,
  History,
} from "@/lib/lucide";

/** Session status badge color mapping. */
const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  active: "default",
  waiting_input: "secondary",
  closed: "outline",
};

const PAGE_SIZE = 20;

function formatCountLabel(
  count: number,
  singular: string,
  plural: string = `${singular}s`,
): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function buildSessionHealthCopy(session: OperationsSession): string {
  const diagnostics = session.diagnostics;

  if (diagnostics.failed_task_count > 0 || diagnostics.failed_recursion_count > 0) {
    return "Needs attention";
  }
  if (diagnostics.waiting_input_task_count > 0) {
    return "Waiting on user";
  }
  if (diagnostics.active_task_count > 0) {
    return "In progress";
  }
  if (diagnostics.completed_task_count > 0 && diagnostics.attention_task_count === 0) {
    return "Healthy";
  }
  return "Idle";
}

/**
 * Session History list page for Studio Operations.
 *
 * Provides agent, status, and type filters with server-side pagination.
 */
export default function SessionHistoryPage() {
  const navigate = useNavigate();

  // Session data
  const [sessions, setSessions] = useState<OperationsSession[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  /** Fetch paginated sessions from the Operations API. */
  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await listOperationsSessions({
        agent_id: agentFilter !== "all" ? Number(agentFilter) : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        session_type: typeFilter !== "all" ? typeFilter : undefined,
        page,
        page_size: PAGE_SIZE,
      });
      setSessions(result.sessions);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    } finally {
      setLoading(false);
    }
  }, [agentFilter, statusFilter, typeFilter, page]);

  /** Load agent list for the filter dropdown. */
  useEffect(() => {
    void getAgents().then(setAgents).catch(() => setAgents([]));
  }, []);

  /** Reload when filters or page change. */
  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  /** Reset to page 1 when any filter changes. */
  const handleAgentFilterChange = (value: string) => {
    setAgentFilter(value);
    setPage(1);
  };
  const handleStatusFilterChange = (value: string) => {
    setStatusFilter(value);
    setPage(1);
  };
  const handleTypeFilterChange = (value: string) => {
    setTypeFilter(value);
    setPage(1);
  };

  const showingFrom = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const showingTo = Math.min(page * PAGE_SIZE, total);
  const sessionsNeedingAttention = sessions.filter(
    (session) => session.diagnostics.attention_task_count > 0,
  ).length;
  const failedTasksOnPage = sessions.reduce(
    (count, session) => count + session.diagnostics.failed_task_count,
    0,
  );
  const waitingTasksOnPage = sessions.reduce(
    (count, session) => count + session.diagnostics.waiting_input_task_count,
    0,
  );
  const failedRecursionsOnPage = sessions.reduce(
    (count, session) => count + session.diagnostics.failed_recursion_count,
    0,
  );

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Session History</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Triage sessions by failures, waiting input, and recent execution errors
        </p>
      </div>

      <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <AlertTriangle className="h-4 w-4 text-warning" />
            Attention Sessions
          </div>
          <div className="mt-2 text-2xl font-semibold">
            {sessionsNeedingAttention}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Sessions on this page with failures or waiting tasks
          </p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <FileText className="h-4 w-4 text-danger" />
            Failed Tasks
          </div>
          <div className="mt-2 text-2xl font-semibold">{failedTasksOnPage}</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Terminal task failures in the current result set
          </p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <History className="h-4 w-4 text-primary" />
            Waiting Input
          </div>
          <div className="mt-2 text-2xl font-semibold">{waitingTasksOnPage}</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Tasks paused until a human responds
          </p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-foreground">
            <AlertTriangle className="h-4 w-4 text-danger" />
            Failed Recursions
          </div>
          <div className="mt-2 text-2xl font-semibold">
            {failedRecursionsOnPage}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Low-level execution loops that ended in error
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select value={agentFilter} onValueChange={handleAgentFilterChange}>
          <SelectTrigger className="w-[180px]" size="small">
            <SelectValue placeholder="All Agents" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Agents</SelectItem>
            {agents.map((agent) => (
              <SelectItem key={agent.id} value={String(agent.id)}>
                {agent.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={statusFilter} onValueChange={handleStatusFilterChange}>
          <SelectTrigger className="w-[150px]" size="small">
            <SelectValue placeholder="All Statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="waiting_input">Waiting Input</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
          </SelectContent>
        </Select>

        <Select value={typeFilter} onValueChange={handleTypeFilterChange}>
          <SelectTrigger className="w-[150px]" size="small">
            <SelectValue placeholder="All Types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="consumer">Consumer</SelectItem>
            <SelectItem value="studio_test">Studio Test</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Error state */}
      {error && (
        <div className="mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="rounded-md border">
        <Table className="table-fixed" containerClassName="overflow-hidden">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[32%]">Session</TableHead>
              <TableHead className="w-[18%]">Health</TableHead>
              <TableHead className="w-[22%]">Diagnostics</TableHead>
              <TableHead className="w-[18%]">Latest Error</TableHead>
              <TableHead className="w-[160px]">Last Activity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                  <CenteredLoadingIndicator
                    className="min-h-24 bg-transparent"
                    spinnerClassName="h-5 w-5"
                    label="Loading sessions"
                  />
                </TableCell>
              </TableRow>
            ) : sessions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                  <div className="flex flex-col items-center gap-2">
                    <FileText className="h-8 w-8 opacity-40" />
                    <span>No sessions found</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              sessions.map((session) => (
                <TableRow
                  key={session.session_id}
                  className={cn(
                    "cursor-pointer",
                    session.diagnostics.attention_task_count > 0 &&
                      "bg-warning/5 hover:bg-warning/10",
                  )}
                  onClick={() =>
                    navigate(`/studio/operations/sessions/${session.session_id}`)
                  }
                >
                  <TableCell className="align-top">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{session.agent_name}</span>
                        <Badge variant="outline">{session.type}</Badge>
                        {session.release_version != null && (
                          <span className="text-xs text-muted-foreground">
                            v{session.release_version}
                          </span>
                        )}
                      </div>
                      <div
                        className="truncate text-sm text-muted-foreground"
                        title={session.title || "Untitled session"}
                      >
                        {session.title || "Untitled session"}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        User: {session.user}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-wrap gap-1.5">
                      <Badge variant={STATUS_VARIANT[session.status] ?? "outline"}>
                        {session.status}
                      </Badge>
                      <Badge
                        variant={
                          session.diagnostics.attention_task_count > 0
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        {buildSessionHealthCopy(session)}
                      </Badge>
                      {session.diagnostics.active_task_count > 0 && (
                        <Badge variant="outline">
                          {formatCountLabel(
                            session.diagnostics.active_task_count,
                            "active task",
                          )}
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="align-top text-sm text-muted-foreground">
                    <div className="space-y-1">
                      <div>{formatCountLabel(session.task_count, "task")}</div>
                      <div>
                        {formatCountLabel(
                          session.diagnostics.attention_task_count,
                          "issue",
                        )}
                      </div>
                      <div>
                        {formatCountLabel(
                          session.diagnostics.failed_recursion_count,
                          "failed recursion",
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    {session.diagnostics.latest_error?.message ? (
                      <div className="space-y-1">
                        <p
                          className="line-clamp-2 text-sm text-foreground"
                          title={session.diagnostics.latest_error.message}
                        >
                          {session.diagnostics.latest_error.message}
                        </p>
                        <div className="text-xs text-muted-foreground">
                          {formatTimestamp(session.diagnostics.latest_error.timestamp ?? undefined)}
                        </div>
                        {session.diagnostics.latest_error.trace_id && (
                          <div
                            className="truncate font-mono text-[11px] text-muted-foreground"
                            title={session.diagnostics.latest_error.trace_id}
                          >
                            {session.diagnostics.latest_error.trace_id}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                        <CheckCircle2 className="h-4 w-4 text-success" />
                        No recent error
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    <div className="space-y-1">
                      <div>{formatTimestamp(session.updated_at)}</div>
                      <div className="text-xs">
                        Created {formatTimestamp(session.created_at)}
                      </div>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      {total > 0 && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Showing {showingFrom}–{showingTo} of {total}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <span className="px-2 text-xs">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
