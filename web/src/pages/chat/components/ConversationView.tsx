import { memo } from "react";
import { MessageSquare } from "lucide-react";

import { parseUtcTimestamp } from "@/utils/timestamp";

import type { ChatMessage, SkillChangeApprovalRequest } from "../types";
import { getChatMessageRenderKey } from "../utils/chatData";
import { AssistantMessageBlock } from "./AssistantMessageBlock";
import { UserMessageBubble } from "./UserMessageBubble";

interface ConversationViewProps {
  messages: ChatMessage[];
  agentName?: string;
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
 * Renders the conversation empty state and the full message timeline.
 */
export const ConversationView = memo(function ConversationView({
  messages,
  agentName,
  expandedRecursions,
  isStreaming,
  onToggleRecursion,
  onReplyTask,
  onApproveSkillChange,
  onRejectSkillChange,
}: ConversationViewProps) {
  const timelineItems = [...messages].sort((left, right) => {
    const leftTimestamp = parseUtcTimestamp(left.timestamp).getTime();
    const rightTimestamp = parseUtcTimestamp(right.timestamp).getTime();

    // Same task: user before assistant — but only for the original exchange,
    // not clarify sub-dialogs where the assistant question precedes the reply.
    if (
      left.task_id &&
      right.task_id &&
      left.task_id === right.task_id &&
      left.role !== right.role
    ) {
      const isClarifyReply =
        left.id.includes("-clarify-reply-") ||
        right.id.includes("-clarify-reply-");
      if (!isClarifyReply) {
        return left.role === "user" ? -1 : 1;
      }
    }

    if (leftTimestamp !== rightTimestamp) {
      return leftTimestamp - rightTimestamp;
    }

    // Same timestamp, different tasks (or no task_id): user before assistant
    if (left.role !== right.role) {
      return left.role === "user" ? -1 : 1;
    }

    return 0;
  });
  const isConversationEmpty = timelineItems.length === 0;
  const normalizedAgentName = agentName?.trim() || "ReAct Agent";

  if (isConversationEmpty) {
    return (
      <div className="mt-12 flex min-h-[36vh] flex-col items-center justify-center text-center text-muted-foreground animate-fade-in">
        <div className="mb-4">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-muted">
            <MessageSquare className="h-8 w-8 text-muted-foreground" />
          </div>
          <p className="mb-2 text-base font-medium text-foreground">
            Chat with {normalizedAgentName}
          </p>
          <p className="text-sm opacity-70">
            Ask questions or give tasks. I&apos;ll show you my reasoning process.
          </p>
        </div>
      </div>
    );
  }

  return (
    <>
      {timelineItems.map((item) => (
        <div
          key={getChatMessageRenderKey(item)}
          data-message-id={item.id}
          data-role={item.role}
          className="mb-6 space-y-2 last:mb-0"
        >
          {item.role === "user" ? (
            <UserMessageBubble message={item} />
          ) : (
            <AssistantMessageBlock
              message={item}
              expandedRecursions={expandedRecursions}
              isStreaming={isStreaming}
              onToggleRecursion={onToggleRecursion}
              onReplyTask={onReplyTask}
              onApproveSkillChange={onApproveSkillChange}
              onRejectSkillChange={onRejectSkillChange}
            />
          )}
        </div>
      ))}
    </>
  );
});
