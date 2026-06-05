import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy, Pencil, X, Play, ChevronDown, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { copyTextToClipboard } from "@/utils/clipboard";
import { formatTimestamp } from "@/utils/timestamp";

import type { ChatMessage } from "../types";
import { AttachmentList } from "./AttachmentList";

export type RewindScope = "conversation" | "full";

interface UserMessageBubbleProps {
  message: ChatMessage;
  isStreaming: boolean;
  onEditSubmit: (
    taskId: string,
    newMessage: string,
    rewindScope: RewindScope,
  ) => void | Promise<void>;
}

/**
 * Renders the user side of the conversation with copy and edit affordances.
 */
export const UserMessageBubble = memo(function UserMessageBubble({
  message,
  isStreaming,
  onEditSubmit,
}: UserMessageBubbleProps) {
  const [hasCopied, setHasCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.setSelectionRange(
        textareaRef.current.value.length,
        textareaRef.current.value.length,
      );
    }
  }, [isEditing]);

  const handleCopyMessage = useCallback(async () => {
    if (!message.content) return;
    try {
      await copyTextToClipboard(message.content);
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
  }, [message.content]);

  const handleStartEdit = useCallback(() => {
    setEditText(message.content);
    setIsEditing(true);
  }, [message.content]);

  const handleCancelEdit = useCallback(() => {
    setIsEditing(false);
    setEditText("");
  }, []);

  const handleSubmitEdit = useCallback(
    (scope: RewindScope) => {
      if (!message.task_id || !editText.trim()) return;
      setIsSubmitting(true);
      const result = onEditSubmit(message.task_id, editText.trim(), scope);
      if (result instanceof Promise) {
        void result
          .then(() => {
            setIsEditing(false);
            setIsSubmitting(false);
          })
          .catch(() => {
            toast.error("Failed to edit message");
            setIsSubmitting(false);
          });
      } else {
        setIsEditing(false);
        setIsSubmitting(false);
      }
    },
    [message.task_id, editText, onEditSubmit],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleCancelEdit();
      }
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSubmitEdit("conversation");
      }
    },
    [handleCancelEdit, handleSubmitEdit],
  );

  const canEdit = !!message.task_id && !isStreaming;

  const hasAttachments = !!(
    message.attachments &&
    message.attachments.length > 0
  );
  const showBubble =
    !!message.content ||
    !!(message.mandatorySkills && message.mandatorySkills.length > 0);

  if (isEditing) {
    return (
      <div className="group relative flex justify-end pb-4 pr-2">
        <div className="flex max-w-[85%] flex-col items-end gap-2">
          {hasAttachments && (
            <AttachmentList attachments={message.attachments} />
          )}
          <div className="w-full rounded-2xl rounded-br-none border-2 border-primary bg-background px-3 py-2 shadow-sm">
            <Textarea
              ref={textareaRef}
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              onKeyDown={handleKeyDown}
              className="min-h-[60px] max-h-[240px] resize-none border-0 p-0 text-sm focus-visible:ring-0 focus-visible:ring-offset-0"
              disabled={isSubmitting}
            />
            <div className="mt-2 flex items-center justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleCancelEdit}
                disabled={isSubmitting}
                className="h-7 px-2 text-xs"
              >
                <X className="mr-1 h-3 w-3" />
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => handleSubmitEdit("conversation")}
                disabled={isSubmitting || !editText.trim()}
                className="h-7 px-3 text-xs"
              >
                <Play className="mr-1 h-3 w-3" />
                Rewind & Resend
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={isSubmitting || !editText.trim()}
                    className="h-7 w-7 px-0"
                  >
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onClick={() => handleSubmitEdit("conversation")}
                    disabled={isSubmitting}
                  >
                    <Play className="mr-2 h-3.5 w-3.5" />
                    Rewind conversation only
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => handleSubmitEdit("full")}
                    disabled={isSubmitting}
                  >
                    <Undo2 className="mr-2 h-3.5 w-3.5" />
                    Rewind + Undo file changes
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group relative flex justify-end pb-9 pr-2">
      <div className="flex max-w-[85%] flex-col items-end gap-1.5">
        {hasAttachments && (
          <AttachmentList attachments={message.attachments} />
        )}
        {showBubble && (
          <div className="rounded-2xl rounded-br-none bg-primary px-4 py-2.5 text-primary-foreground shadow-sm">
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
            {message.content && (
              <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
                {message.content}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="pointer-events-none absolute bottom-0 right-0 flex items-center gap-0.5 px-2 pt-2 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
        {canEdit && (
          <button
            type="button"
            onClick={handleStartEdit}
            className="pointer-events-none flex h-7 w-7 items-center justify-center rounded-lg bg-transparent text-muted-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-foreground focus-visible:bg-sidebar-accent focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:pointer-events-auto group-focus-within:pointer-events-auto"
            aria-label="Edit message"
            title="Edit & rewind"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        )}
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
