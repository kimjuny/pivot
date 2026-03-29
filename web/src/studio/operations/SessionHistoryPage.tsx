/**
 * Studio Operations — Session History list page.
 *
 * Displays a paginated, filterable table of all sessions across every user
 * and agent so administrators can inspect production traffic.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getAgents } from "@/utils/api";
import type { Agent } from "@/types";
import {
  listOperationsSessions,
  type OperationsSession,
} from "@/studio/operations/api";
import { formatTimestamp } from "@/utils/timestamp";
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
import { ChevronLeft, ChevronRight, FileText } from "@/lib/lucide";

/** Session status badge color mapping. */
const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  active: "default",
  waiting_input: "secondary",
  closed: "outline",
};

const PAGE_SIZE = 20;

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

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Session History</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          All consumer and test session activity across the workspace
        </p>
      </div>

      {/* Filters */}
      <div className="mb-4 flex items-center gap-3">
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
        <Table containerClassName="overflow-hidden">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[180px]">Agent</TableHead>
              <TableHead className="w-[100px]">User</TableHead>
              <TableHead>Title</TableHead>
              <TableHead className="w-[110px]">Status</TableHead>
              <TableHead className="w-[80px]">Version</TableHead>
              <TableHead className="w-[70px]">Tasks</TableHead>
              <TableHead className="w-[160px]">Last Activity</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
                  Loading…
                </TableCell>
              </TableRow>
            ) : sessions.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-24 text-center text-muted-foreground">
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
                  className="cursor-pointer"
                  onClick={() =>
                    navigate(`/studio/operations/sessions/${session.session_id}`)
                  }
                >
                  <TableCell className="font-medium">
                    {session.agent_name}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {session.user}
                  </TableCell>
                  <TableCell className="max-w-[300px] truncate text-muted-foreground">
                    {session.title || "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[session.status] ?? "outline"}>
                      {session.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {session.release_version != null
                      ? `v${session.release_version}`
                      : "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {session.task_count}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatTimestamp(session.updated_at)}
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
