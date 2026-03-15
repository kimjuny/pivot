import {
  CheckCircle2,
  Loader2,
  MessageSquare,
  XCircle,
} from "lucide-react";

import { formatTimestamp } from "@/utils/timestamp";

import type { ChatMessage } from "../types";
import {
  formatTokenCount,
  isClarifyMessage,
} from "../utils/chatSelectors";
import { FormattedAnswerContent } from "./FormattedAnswerContent";
import { RecursionCard } from "./RecursionCard";
import { SkillSelectionCard } from "./SkillSelectionCard";
import { TokenUsageLabel } from "./TokenUsageLabel";

interface AssistantMessageBlockProps {
  message: ChatMessage;
  expandedRecursions: Record<string, boolean>;
  onToggleRecursion: (messageId: string, recursionUid: string) => void;
  onReplyTask: (taskId: string | null) => void;
}

/**
 * Renders the assistant side of the timeline, including skill resolution, recursions, and final answer state.
 */
export function AssistantMessageBlock({
  message,
  expandedRecursions,
  onToggleRecursion,
  onReplyTask,
}: AssistantMessageBlockProps) {
  const clarifyMessage = isClarifyMessage(message);

  return (
    <div className="space-y-2">
      {message.skillSelection && (
        <SkillSelectionCard skillSelection={message.skillSelection} />
      )}

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

      {message.content && (
        <div className="rounded-lg border border-border bg-background/50 p-3">
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
            {clarifyMessage && message.task_id && (
              <button
                onClick={() => onReplyTask(message.task_id || null)}
                className="text-xs text-muted-foreground transition-colors hover:text-info"
              >
                REPLY
              </button>
            )}
          </div>
          <div className="pl-5 text-sm leading-relaxed text-foreground">
            <FormattedAnswerContent content={message.content} />
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 px-3">
        {message.status === "skill_resolving" && (
          <>
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
            <span
              className="animate-thinking-wave truncate text-xs font-semibold"
              style={{
                background:
                  "linear-gradient(90deg, #9ca3af 0%, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%, #9ca3af 100%)",
                backgroundClip: "text",
                backgroundSize: "400% 100%",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
              }}
            >
              Matching Skills...
            </span>
          </>
        )}
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
        <span className="ml-auto text-xs text-muted-foreground">
          {formatTimestamp(message.timestamp)}
        </span>
      </div>
    </div>
  );
}
