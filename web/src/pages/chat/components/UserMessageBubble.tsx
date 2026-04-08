import { formatTimestamp } from "@/utils/timestamp";
import { Badge } from "@/components/ui/badge";

import type { ChatMessage } from "../types";
import { AttachmentList } from "./AttachmentList";

interface UserMessageBubbleProps {
  message: ChatMessage;
  currentSessionId: string | null;
}

/**
 * Renders the user side of the conversation with the existing timestamp and attachment treatment.
 */
export function UserMessageBubble({
  message,
  currentSessionId,
}: UserMessageBubbleProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-none bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-90">
          YOU
        </div>
        <div className="mb-1 font-mono text-[10px] opacity-70">
          {formatTimestamp(message.timestamp)}
        </div>
        {message.mandatorySkills && message.mandatorySkills.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {message.mandatorySkills.map((skill) => (
              <Badge
                key={skill.name}
                variant="secondary"
                className="border border-primary-foreground/15 bg-primary-foreground/10 px-2 py-0 text-[10px] font-medium text-primary-foreground"
              >
                {skill.name}
              </Badge>
            ))}
          </div>
        )}
        {message.attachments && message.attachments.length > 0 && (
          <AttachmentList
            attachments={message.attachments}
            currentSessionId={currentSessionId}
          />
        )}
        {message.content && (
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            {message.content}
          </div>
        )}
      </div>
    </div>
  );
}
