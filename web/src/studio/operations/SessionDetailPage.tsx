/**
 * Studio Operations — Session Detail page.
 *
 * Read-only inspection of one session's full conversation history,
 * rendered with the same ConversationView used by the live chat.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getOperationsSessionDetail,
  type OperationsSessionDetail,
  type OperationsTaskMessage,
} from "@/studio/operations/api";
import { buildOperationsDetailDiagnostics } from "@/studio/operations/diagnostics";
import type { TaskMessage } from "@/utils/api";
import { buildMessagesFromHistory } from "@/pages/chat/utils/chatData";
import { ConversationView } from "@/pages/chat/components/ConversationView";
import { formatTimestamp } from "@/utils/timestamp";
import type { ChatMessage } from "@/pages/chat/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Copy,
  FileText,
  History,
} from "@/lib/lucide";

/**
 * Maps the Operations task shape into the TaskMessage format that
 * buildMessagesFromHistory() expects.
 *
 * The operations API returns the same task shape as the user-scoped
 * full-history endpoint, so a broad cast is safe here.
 */
function adaptTasks(opsTasks: OperationsTaskMessage[]): TaskMessage[] {
  return opsTasks as unknown as TaskMessage[];
}

/**
 * Read-only session detail page for Studio Operations.
 */
export default function SessionDetailPage() {
  const navigate = useNavigate();
  const { sessionId } = useParams<{ sessionId: string }>();

  const [sessionMeta, setSessionMeta] = useState<OperationsSessionDetail | null>(null);
  const [tasks, setTasks] = useState<OperationsTaskMessage[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [expandedRecursions, setExpandedRecursions] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  /** Fetch session detail and transform into renderable messages. */
  const loadDetail = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await getOperationsSessionDetail(sessionId);
      setSessionMeta(response.session);
      setTasks(response.tasks);
      const adapted = adaptTasks(response.tasks);
      setMessages(buildMessagesFromHistory(adapted));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  /** Toggle recursion expansion for a given assistant message. */
  const toggleRecursion = (_messageId: string, recursionUid: string) => {
    setExpandedRecursions((prev) => ({
      ...prev,
      [recursionUid]: !prev[recursionUid],
    }));
  };
  const diagnosticsSummary = sessionMeta
    ? buildOperationsDetailDiagnostics(sessionMeta.diagnostics, tasks)
    : null;

  const handleCopyDiagnosticsContext = async () => {
    if (!sessionMeta || diagnosticsSummary === null) {
      return;
    }

    const payload = [
      `session_id: ${sessionMeta.session_id}`,
      `session_status: ${sessionMeta.status}`,
      `agent: ${sessionMeta.agent_name}`,
      `latest_error_task_id: ${diagnosticsSummary.latestError?.task_id ?? "n/a"}`,
      `latest_error_trace_id: ${diagnosticsSummary.latestError?.trace_id ?? "n/a"}`,
      `latest_error_at: ${diagnosticsSummary.latestError?.timestamp ?? "n/a"}`,
      `latest_error_message: ${diagnosticsSummary.latestError?.message ?? "n/a"}`,
    ].join("\n");

    try {
      await navigator.clipboard.writeText(payload);
      toast.success("Copied diagnostics context");
    } catch {
      toast.error("Failed to copy diagnostics context");
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Back button */}
      <Button
        variant="ghost"
        size="sm"
        className="mb-4 -ml-2 gap-1.5 text-muted-foreground"
        onClick={() => navigate("/studio/operations/sessions")}
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        Back to Session History
      </Button>

      {loading && (
        <div className="flex items-center justify-center py-20 text-muted-foreground">
          Loading session…
        </div>
      )}

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {!loading && !error && sessionMeta && (
        <>
          {/* Session header card */}
          <div className="mb-6 rounded-lg border bg-card p-4">
            <div className="flex items-center gap-3">
              <h2 className="text-base font-semibold">
                {sessionMeta.agent_name}
              </h2>
              <Badge variant="secondary">{sessionMeta.type}</Badge>
              <Badge variant="outline">{sessionMeta.status}</Badge>
              {sessionMeta.release_version != null && (
                <span className="text-xs text-muted-foreground">
                  v{sessionMeta.release_version}
                </span>
              )}
            </div>
            {sessionMeta.title && (
              <p className="mt-1 text-sm text-muted-foreground">
                {sessionMeta.title}
              </p>
            )}
            <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
              <span>User: {sessionMeta.user}</span>
              <span>
                Created: {formatTimestamp(sessionMeta.created_at)}
              </span>
              <span>
                Last activity: {formatTimestamp(sessionMeta.updated_at)}
              </span>
              <span>{messages.filter((m) => m.role === "user").length} tasks</span>
            </div>
          </div>

          {diagnosticsSummary && (
            <Tabs defaultValue="overview">
              <TabsList>
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="conversation">Conversation</TabsTrigger>
              </TabsList>

              <TabsContent value="overview" className="space-y-6">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-lg border bg-card p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <AlertTriangle className="h-4 w-4 text-warning" />
                      Attention Tasks
                    </div>
                    <div className="mt-2 text-2xl font-semibold">
                      {diagnosticsSummary.attentionTaskCount}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Failed or blocked tasks that should be triaged first
                    </p>
                  </div>
                  <div className="rounded-lg border bg-card p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <FileText className="h-4 w-4 text-danger" />
                      Failed Recursions
                    </div>
                    <div className="mt-2 text-2xl font-semibold">
                      {diagnosticsSummary.failedRecursionCount}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Execution loops that ended with an error signal
                    </p>
                  </div>
                  <div className="rounded-lg border bg-card p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <History className="h-4 w-4 text-primary" />
                      Waiting Input
                    </div>
                    <div className="mt-2 text-2xl font-semibold">
                      {diagnosticsSummary.waitingInputTaskCount}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Tasks paused until a human responds
                    </p>
                  </div>
                  <div className="rounded-lg border bg-card p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                      <CheckCircle2 className="h-4 w-4 text-success" />
                      Total Tokens
                    </div>
                    <div className="mt-2 text-2xl font-semibold">
                      {diagnosticsSummary.totalTokens.toLocaleString("en-US")}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Total token consumption across all tasks in this session
                    </p>
                  </div>
                </div>

                <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,0.95fr)]">
                  <div className="rounded-lg border bg-card p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-sm font-semibold text-foreground">
                          Latest Error
                        </h3>
                        <p className="mt-1 text-xs text-muted-foreground">
                          Copy this context when you need to jump into logs or ask for help
                        </p>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-1.5"
                        onClick={() => void handleCopyDiagnosticsContext()}
                      >
                        <Copy className="h-3.5 w-3.5" />
                        Copy Context
                      </Button>
                    </div>

                    {diagnosticsSummary.latestError ? (
                      <div className="mt-4 space-y-3">
                        <div className="rounded-md border border-danger/30 bg-danger/5 px-4 py-3">
                          <p className="text-sm font-medium text-danger">
                            {diagnosticsSummary.latestError.message}
                          </p>
                          <div className="mt-2 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                            <span>
                              Task: {diagnosticsSummary.latestError.task_id ?? "n/a"}
                            </span>
                            <span>
                              Trace: {diagnosticsSummary.latestError.trace_id ?? "n/a"}
                            </span>
                            <span>
                              Timestamp: {formatTimestamp(
                                diagnosticsSummary.latestError.timestamp ?? undefined,
                              )}
                            </span>
                            <span>
                              Failed recursions: {diagnosticsSummary.failedRecursionCount}
                            </span>
                          </div>
                        </div>
                        <div className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-2">
                          <div className="rounded-md border bg-background/60 px-3 py-2">
                            <div className="text-xs uppercase tracking-wide text-muted-foreground">
                              Task mix
                            </div>
                            <div className="mt-1">
                              {diagnosticsSummary.failedTaskCount} failed,{" "}
                              {diagnosticsSummary.waitingInputTaskCount} waiting,{" "}
                              {diagnosticsSummary.activeTaskCount} active
                            </div>
                          </div>
                          <div className="rounded-md border bg-background/60 px-3 py-2">
                            <div className="text-xs uppercase tracking-wide text-muted-foreground">
                              Session identifiers
                            </div>
                            <div className="mt-1 break-all font-mono text-[12px]">
                              {sessionMeta.session_id}
                            </div>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-4 flex items-center gap-2 rounded-md border border-success/30 bg-success/5 px-4 py-3 text-sm text-muted-foreground">
                        <CheckCircle2 className="h-4 w-4 text-success" />
                        No persisted error signal has been recorded for this session yet.
                      </div>
                    )}
                  </div>

                  <div className="rounded-lg border bg-card p-4">
                    <h3 className="text-sm font-semibold text-foreground">
                      Tasks With Issues
                    </h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Most recent blocked or failing tasks in this session
                    </p>

                    {diagnosticsSummary.issueTasks.length > 0 ? (
                      <div className="mt-4 space-y-3">
                        {diagnosticsSummary.issueTasks.slice(0, 6).map((task) => (
                          <div
                            key={task.taskId}
                            className="rounded-md border bg-background/60 px-3 py-3"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <Badge
                                variant={
                                  task.status === "failed" ? "destructive" : "secondary"
                                }
                              >
                                {task.status}
                              </Badge>
                              <span className="text-xs text-muted-foreground">
                                {formatTimestamp(task.updatedAt)}
                              </span>
                            </div>
                            <p
                              className="mt-2 line-clamp-2 text-sm text-foreground"
                              title={task.userMessage}
                            >
                              {task.userMessage}
                            </p>
                            <div className="mt-2 text-xs text-muted-foreground">
                              Task ID: <span className="font-mono">{task.taskId}</span>
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              Failed recursions: {task.failedRecursionCount}
                            </div>
                            {task.latestError?.message && (
                              <p
                                className="mt-2 line-clamp-2 text-xs text-danger/90"
                                title={task.latestError.message}
                              >
                                {task.latestError.message}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-4 rounded-md border border-success/30 bg-success/5 px-4 py-3 text-sm text-muted-foreground">
                        No failed or blocked tasks in this session.
                      </div>
                    )}
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="conversation">
                <div className="rounded-lg border bg-card">
                  <div className="border-b px-4 py-2.5">
                    <span className="text-xs font-medium text-muted-foreground">
                      Conversation (read-only)
                    </span>
                  </div>
                  <div className="px-4 py-4">
                    <ConversationView
                      messages={messages}
                      agentName={sessionMeta.agent_name}
                      expandedRecursions={expandedRecursions}
                      isStreaming={false}
                      onToggleRecursion={toggleRecursion}
                      onReplyTask={() => {}}
                      onApproveSkillChange={() => {}}
                      onRejectSkillChange={() => {}}
                    />
                  </div>
                </div>
              </TabsContent>
            </Tabs>
          )}
        </>
      )}
    </div>
  );
}
