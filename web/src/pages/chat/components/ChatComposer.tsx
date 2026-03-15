import type {
  ChangeEvent,
  ClipboardEvent,
  FormEvent,
  KeyboardEvent,
  RefObject,
} from "react";
import {
  ArrowUp,
  ImagePlus,
  Loader2,
  Paperclip,
  Plus,
  Square,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import type { ReactContextUsageSummary } from "@/utils/api";

import type { PendingUploadItem } from "../types";
import { AttachmentList } from "./AttachmentList";
import { ContextUsageRing } from "./ContextUsageRing";

interface ChatComposerProps {
  inputMessage: string;
  error: string | null;
  replyTaskId: string | null;
  pendingFiles: PendingUploadItem[];
  canSendMessage: boolean;
  isStreaming: boolean;
  isConversationEmpty: boolean;
  hasUploadingFiles: boolean;
  contextUsage: ReactContextUsageSummary | null;
  isContextUsageLoading: boolean;
  supportsImageInput: boolean;
  imageInputRef: RefObject<HTMLInputElement>;
  documentInputRef: RefObject<HTMLInputElement>;
  onInputChange: (value: string) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onStop: () => void;
  onCancelReply: () => void;
  onImageInputChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onDocumentInputChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemovePendingFile: (clientId: string) => void | Promise<void>;
}

/**
 * Owns the composer UI while receiving all state from the container to keep behavior explicit.
 */
export function ChatComposer({
  inputMessage,
  error,
  replyTaskId,
  pendingFiles,
  canSendMessage,
  isStreaming,
  isConversationEmpty,
  hasUploadingFiles,
  contextUsage,
  isContextUsageLoading,
  supportsImageInput,
  imageInputRef,
  documentInputRef,
  onInputChange,
  onKeyDown,
  onPaste,
  onSubmit,
  onStop,
  onCancelReply,
  onImageInputChange,
  onDocumentInputChange,
  onRemovePendingFile,
}: ChatComposerProps) {
  return (
    <div
      className={`mx-auto w-full max-w-3xl bg-gradient-to-t from-background via-background to-transparent px-4 pb-4 pt-3 transition-transform duration-100 ease-out ${
        isConversationEmpty
          ? "-translate-y-[12vh] sm:-translate-y-[18vh]"
          : "translate-y-0"
      }`}
    >
      {error && (
        <div className="mb-2 rounded-lg border border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">
          {error}
        </div>
      )}

      {replyTaskId && (
        <div className="mb-2 flex items-center justify-between rounded-lg border border-border/50 bg-muted/50 px-3 py-1.5 text-xs">
          <span className="text-foreground/70">↳ Replying to question</span>
          <button
            onClick={onCancelReply}
            className="text-muted-foreground transition-colors hover:text-foreground"
            title="Cancel reply"
          >
            <XCircle className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <form
        onSubmit={onSubmit}
        className="relative overflow-hidden rounded-2xl border bg-background shadow-lg transition-all focus-within:border-ring"
      >
        <input
          ref={imageInputRef}
          type="file"
          accept="image/jpeg,image/jpg,image/png,image/webp"
          multiple
          className="hidden"
          onChange={onImageInputChange}
        />
        <input
          ref={documentInputRef}
          type="file"
          accept=".pdf,.docx,.pptx,.xlsx,.md,.markdown"
          multiple
          className="hidden"
          onChange={onDocumentInputChange}
        />

        <AttachmentList
          attachments={pendingFiles}
          variant="composer"
          onRemovePendingFile={onRemovePendingFile}
        />

        <Textarea
          value={inputMessage}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          placeholder={replyTaskId ? "Reply to question..." : "Ask anything"}
          className="min-h-[60px] w-full resize-none border-0 p-4 shadow-none focus:shadow-none focus:outline-none focus-visible:ring-0 focus-visible:shadow-none"
          disabled={isStreaming}
        />

        <div className="flex items-center justify-between px-4 pb-3">
          <DropdownMenu modal={false}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full">
                <Plus className="h-4 w-4" />
                <span className="sr-only">Attach</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="z-[60]">
              {supportsImageInput && (
                <DropdownMenuItem
                  onClick={() => imageInputRef.current?.click()}
                >
                  <ImagePlus className="mr-2 h-4 w-4" />
                  <span>Upload image</span>
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onClick={() => documentInputRef.current?.click()}
              >
                <Paperclip className="mr-2 h-4 w-4" />
                <span>Upload file</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex items-center gap-2">
            {hasUploadingFiles && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                <span>Processing attachments...</span>
              </div>
            )}
            <ContextUsageRing
              usage={contextUsage}
              isLoading={isContextUsageLoading}
            />
            {isStreaming ? (
              <Button
                type="button"
                onClick={onStop}
                size="icon"
                className="h-8 w-8 rounded-full bg-destructive/90 text-destructive-foreground hover:bg-destructive"
                title="Stop execution"
              >
                <Square className="h-4 w-4" fill="currentColor" />
              </Button>
            ) : (
              <Button
                type="submit"
                disabled={!canSendMessage}
                size="icon"
                className="h-8 w-8 rounded-full"
                title="Send message"
              >
                <ArrowUp className="h-4 w-4" />
                <span className="sr-only">Send</span>
              </Button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
