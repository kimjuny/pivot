import { memo } from "react";
import { MessageSquare } from "@/lib/lucide";

import type { ChatMessage, SkillChangeApprovalRequest } from "../types";
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
      {messages.map((message) => (
        <div key={message.id} className="mb-6 space-y-2 last:mb-0">
          {message.role === "user" ? (
            <UserMessageBubble message={message} />
          ) : (
            <AssistantMessageBlock
              message={message}
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
