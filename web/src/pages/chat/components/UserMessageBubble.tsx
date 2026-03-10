import { formatTimestamp } from "@/utils/timestamp";

import type { ChatMessage } from "../types";
import { AttachmentList } from "./AttachmentList";

interface UserMessageBubbleProps {
  message: ChatMessage;
}

/**
 * Renders the user side of the conversation with the existing timestamp and attachment treatment.
 */
export function UserMessageBubble({ message }: UserMessageBubbleProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-none bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide opacity-90">
          YOU
        </div>
        <div className="mb-1 font-mono text-[10px] opacity-70">
          {formatTimestamp(message.timestamp)}
        </div>
        {message.attachments && message.attachments.length > 0 && (
          <div className="rounded-xl bg-primary-foreground/10 p-2">
            <AttachmentList attachments={message.attachments} />
          </div>
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
