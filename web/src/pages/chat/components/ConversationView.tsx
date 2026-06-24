import { memo } from "react";
import { MessageSquare } from "lucide-react";

import type { ChatMessage, SkillChangeApprovalRequest } from "../types";
import { getChatMessageRenderKey } from "../utils/chatData";
import { AssistantMessageBlock } from "./AssistantMessageBlock";
import { UserMessageBubble } from "./UserMessageBubble";
import type { RewindScope } from "./UserMessageBubble";

interface ConversationViewProps {
  messages: ChatMessage[];
  agentName?: string;
  isStreaming: boolean;
  onReplyTask: (taskId: string | null) => void;
  onEditSubmit: (
    taskId: string,
    newMessage: string,
    rewindScope: RewindScope,
  ) => void | Promise<void>;
  onApproveSkillChange: (
    taskId: string,
    request: SkillChangeApprovalRequest,
  ) => void;
  onRejectSkillChange: (
    taskId: string,
    request: SkillChangeApprovalRequest,
  ) => void;
  onPlanApprove: (taskId: string) => void;
  onPlanReject: (taskId: string) => void;
  onPlanEdit: (taskId: string, newText: string) => void;
  planReviewSubmitting?: boolean;
}

/**
 * Renders the conversation empty state and the full message timeline.
 */
export const ConversationView = memo(function ConversationView({
  messages,
  agentName,
  isStreaming,
  onReplyTask,
  onEditSubmit,
  onApproveSkillChange,
  onRejectSkillChange,
  onPlanApprove,
  onPlanReject,
  onPlanEdit,
  planReviewSubmitting,
}: ConversationViewProps) {
  const isConversationEmpty = messages.length === 0;
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
      {messages.map((item) => (
        <div
          key={getChatMessageRenderKey(item)}
          data-message-id={item.id}
          data-role={item.role}
          className="mb-6 space-y-2 last:mb-0"
        >
          {item.role === "user" ? (
            <UserMessageBubble message={item} isStreaming={isStreaming} onEditSubmit={onEditSubmit} />
          ) : (
            <AssistantMessageBlock
              message={item}
              isStreaming={isStreaming}
              onReplyTask={onReplyTask}
              onApproveSkillChange={onApproveSkillChange}
              onRejectSkillChange={onRejectSkillChange}
              onPlanApprove={onPlanApprove}
              onPlanReject={onPlanReject}
              onPlanEdit={onPlanEdit}
              planReviewSubmitting={planReviewSubmitting}
            />
          )}
        </div>
      ))}
    </>
  );
});
