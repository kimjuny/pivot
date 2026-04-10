import { useEffect, useRef, useState } from "react";
import {
  Check,
  CheckCircle2,
  Copy,
  MessageSquare,
  Square,
  XCircle,
} from "@/lib/lucide";
import { toast } from "sonner";

import { formatTimestamp } from "@/utils/timestamp";

import type { ChatMessage, SkillChangeApprovalRequest } from "../types";
import {
  extractSkillChangeApprovalRequest,
  formatTokenCount,
  isClarifyMessage,
} from "../utils/chatSelectors";
import { AssistantAttachmentList } from "./AssistantAttachmentList";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { RecursionCard } from "./RecursionCard";
import { TokenUsageLabel } from "./TokenUsageLabel";

interface AssistantMessageBlockProps {
  message: ChatMessage;
  expandedRecursions: Record<string, boolean>;
  isStreaming: boolean;
  onToggleRecursion: (messageId: string, recursionUid: string) => void;
  onReplyTask: (taskId: string | null) => void;
  onApproveSkillChange: (
    taskId: string,
    request: SkillChangeApprovalRequest,
  ) => void;
  onRejectSkillChange: (
    taskId: string,
    request: SkillChangeApprovalRequest,
  ) => void;
}

/**
 * Renders the assistant side of the timeline, including recursions and final answer state.
 */
export function AssistantMessageBlock({
  message,
  expandedRecursions,
  isStreaming,
  onToggleRecursion,
  onReplyTask,
  onApproveSkillChange,
  onRejectSkillChange,
}: AssistantMessageBlockProps) {
  const clarifyMessage = isClarifyMessage(message);
  const approvalRequest = extractSkillChangeApprovalRequest(message);
  const [hasCopied, setHasCopied] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);
  const canRenderApprovalActions =
    clarifyMessage &&
    typeof message.task_id === "string" &&
    approvalRequest !== undefined;
  const hasFooterMetadata =
    message.status === "completed" ||
    message.status === "error" ||
    message.status === "stopped";

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  /**
   * Keeps answer copying close to the footer metadata so follow-up reuse stays
   * aligned with the same hover target as timestamp and status labels.
   */
  const handleCopyMessage = async () => {
    if (!message.content) {
      return;
    }

    try {
      await navigator.clipboard.writeText(message.content);
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
      setHasCopied(true);
      copyResetTimeoutRef.current = window.setTimeout(() => {
        setHasCopied(false);
        copyResetTimeoutRef.current = null;
      }, 2000);
    } catch {
      toast.error("Failed to copy message");
    }
  };

  return (
    <div className="space-y-2">
      {message.recursions && message.recursions.length > 0 && (
        <div className="space-y-2">
          {message.recursions.map((recursion) => (
            <RecursionCard
              key={`${message.id}-${recursion.uid}`}
              messageId={message.id}
              recursion={recursion}
              taskId={message.task_id}
              isExpanded={expandedRecursions[`${message.id}-${recursion.uid}`] ?? false}
              onToggle={onToggleRecursion}
            />
          ))}
        </div>
      )}

      <div className="group relative pb-8">
        {(message.content || (message.assistantAttachments?.length ?? 0) > 0) && (
          <div className="rounded-lg bg-background/50 p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                {clarifyMessage ? (
                  <>
                    <MessageSquare className="h-3.5 w-3.5 text-info" />
                    <span className="text-xs font-semibold text-foreground">
                      QUESTION
                    </span>
                  </>
                ) : (
                  <>
                    <MessageSquare className="h-3.5 w-3.5 text-success" />
                    <span className="text-xs font-semibold text-foreground">
                      FINAL ANSWER
                    </span>
                  </>
                )}
              </div>
              {canRenderApprovalActions ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={isStreaming}
                    onClick={() =>
                      onRejectSkillChange(message.task_id!, approvalRequest)
                    }
                    className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-danger/30 hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    disabled={isStreaming}
                    onClick={() =>
                      onApproveSkillChange(message.task_id!, approvalRequest)
                    }
                    className="rounded-full border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-medium text-success transition-colors hover:bg-success/15 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Approve
                  </button>
                </div>
              ) : (
                clarifyMessage &&
                message.task_id && (
                  <button
                    type="button"
                    onClick={() => onReplyTask(message.task_id || null)}
                    className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-info/30 hover:text-info"
                  >
                    Reply
                  </button>
                )
              )}
            </div>
            <div className="pl-5 text-sm leading-relaxed text-foreground">
              {message.content && <MarkdownRenderer content={message.content} />}
              <AssistantAttachmentList attachments={message.assistantAttachments} />
            </div>
          </div>
        )}

        {message.status === "error" && message.errorMessage && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-3">
            <div className="mb-2 flex items-center gap-1.5">
              <XCircle className="h-3.5 w-3.5 text-danger" />
              <span className="text-xs font-semibold text-foreground">ERROR</span>
            </div>
            <div className="pl-5 text-sm leading-relaxed text-foreground whitespace-pre-wrap">
              {message.errorMessage}
            </div>
          </div>
        )}

        {hasFooterMetadata ? (
          <div className="pointer-events-none absolute bottom-0 left-0 right-0 flex items-center gap-2 px-3 opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
            {message.status === "completed" && (
              <>
                <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                <span className="text-xs text-muted-foreground">Completed</span>
                {message.totalTokens && (
                  <TokenUsageLabel
                    tokens={message.totalTokens}
                    label={`• Total: ${formatTokenCount(message.totalTokens.total_tokens)} tokens`}
                    className="ml-2 cursor-help whitespace-nowrap text-xs tabular-nums text-muted-foreground underline decoration-dotted underline-offset-2"
                  />
                )}
              </>
            )}
            {message.status === "error" && (
              <>
                <XCircle className="h-3.5 w-3.5 text-danger" />
                <span className="text-xs text-danger">Error</span>
              </>
            )}
            {message.status === "stopped" && (
              <>
                <Square className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">Stopped</span>
              </>
            )}
            <div className="ml-auto flex items-center gap-1.5">
              {message.content ? (
                <button
                  type="button"
                  onClick={() => {
                    void handleCopyMessage();
                  }}
                  className="flex h-7 w-7 items-center justify-center rounded-lg bg-transparent text-muted-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-foreground focus-visible:bg-sidebar-accent focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label={hasCopied ? "Copied message" : "Copy message"}
                  title={hasCopied ? "Copied" : "Copy message"}
                >
                  {hasCopied ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                </button>
              ) : null}
              <span className="text-xs text-muted-foreground">
                {formatTimestamp(message.timestamp)}
              </span>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
