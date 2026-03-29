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
import type { TaskMessage } from "@/utils/api";
import { buildMessagesFromHistory } from "@/pages/chat/utils/chatData";
import { ConversationView } from "@/pages/chat/components/ConversationView";
import { formatTimestamp } from "@/utils/timestamp";
import type { ChatMessage } from "@/pages/chat/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "@/lib/lucide";

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

          {/* Read-only conversation */}
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
        </>
      )}
    </div>
  );
}
