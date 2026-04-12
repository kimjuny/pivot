import { memo, useEffect, useRef, useState } from "react";
import { Check, Copy } from "@/lib/lucide";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { formatTimestamp } from "@/utils/timestamp";

import type { ChatMessage } from "../types";
import { AttachmentList } from "./AttachmentList";

interface UserMessageBubbleProps {
  message: ChatMessage;
}

/**
 * Renders the user side of the conversation with the existing timestamp and attachment treatment.
 */
export const UserMessageBubble = memo(function UserMessageBubble({
  message,
}: UserMessageBubbleProps) {
  const [hasCopied, setHasCopied] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  /**
   * Keeps copy feedback close to the hovered bubble so repeated reuse feels immediate.
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
    <div className="group relative flex justify-end pb-9 pr-2">
      <div className="max-w-[85%] rounded-2xl rounded-br-none bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
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
          <AttachmentList attachments={message.attachments} />
        )}
        {message.content && (
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
            {message.content}
          </div>
        )}
      </div>
      <div className="pointer-events-none absolute bottom-0 right-0 flex items-center gap-1.5 px-2 pt-2 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
        {message.content ? (
          <button
            type="button"
            onClick={() => {
              void handleCopyMessage();
            }}
            className="pointer-events-none flex h-7 w-7 items-center justify-center rounded-lg bg-transparent text-muted-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-foreground focus-visible:bg-sidebar-accent focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:pointer-events-auto group-focus-within:pointer-events-auto"
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
        <div className="text-xs text-muted-foreground">
          {formatTimestamp(message.timestamp)}
        </div>
      </div>
    </div>
  );
});
