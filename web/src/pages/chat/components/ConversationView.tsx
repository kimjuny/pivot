import { memo } from "react";
import { MessageSquare } from "lucide-react";

import type {
  ChatMessage,
  CompactTimelineItem,
  SkillChangeApprovalRequest,
} from "../types";
import { getChatMessageRenderKey } from "../utils/chatData";
import { AssistantMessageBlock } from "./AssistantMessageBlock";
import { CompactTimelineSeparator } from "./CompactTimelineSeparator";
import { UserMessageBubble } from "./UserMessageBubble";

interface ConversationViewProps {
  messages: ChatMessage[];
  compactTimelineItems?: CompactTimelineItem[];
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
  compactTimelineItems = [],
  agentName,
  expandedRecursions,
  isStreaming,
  onToggleRecursion,
  onReplyTask,
  onApproveSkillChange,
  onRejectSkillChange,
}: ConversationViewProps) {
  const timelineItems = [...messages, ...compactTimelineItems].sort((left, right) => {
    const leftIsMessage = "role" in left;
    const rightIsMessage = "role" in right;

    // ChatMessages always come before CompactTimelineItems
    if (leftIsMessage !== rightIsMessage) {
      return leftIsMessage ? -1 : 1;
    }

    const leftTimestamp = Date.parse(left.timestamp);
    const rightTimestamp = Date.parse(right.timestamp);

    // Same task: user before assistant, regardless of timestamp drift
    if (leftIsMessage && rightIsMessage) {
      if (
        left.task_id &&
        right.task_id &&
        left.task_id === right.task_id &&
        left.role !== right.role
      ) {
        return left.role === "user" ? -1 : 1;
      }
    }

    if (leftTimestamp !== rightTimestamp) {
      return leftTimestamp - rightTimestamp;
    }

    // Same timestamp, different tasks (or no task_id): user before assistant
    if (leftIsMessage && rightIsMessage && left.role !== right.role) {
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
      {timelineItems.map((item) => {
        return "role" in item ? (
          <div
            key={getChatMessageRenderKey(item)}
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
        ) : (
          <CompactTimelineSeparator key={item.id} item={item} />
        );
      })}
    </>
  );
});
