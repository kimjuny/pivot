import type {
  ChangeEvent,
  ClipboardEvent,
  FormEvent,
  KeyboardEvent,
  RefObject,
} from "react";
import { useEffect, useRef } from "react";
import {
  ArrowUp,
  Brain,
  ImagePlus,
  Loader2,
  MessageSquare,
  Paperclip,
  Plus,
  RefreshCw,
  Square,
  XCircle,
  Zap,
} from "@/lib/lucide";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { WebSearchProviderBadge } from "@/components/WebSearchProviderBadge";
import type { ReactContextUsageSummary } from "@/utils/api";
import type { ChatThinkingMode } from "@/utils/llmThinking";

import type {
  ChatReplyTarget,
  ChatWebSearchProviderOption,
  PendingUploadItem,
  TaskPlanSnapshot,
} from "../types";
import { AttachmentList } from "./AttachmentList";
import { ComposerTaskPlan } from "./ComposerTaskPlan";
import { ContextUsageRing } from "./ContextUsageRing";

interface ChatComposerProps {
  inputMessage: string;
  error: string | null;
  compactStatusMessage: string | null;
  replyTarget: ChatReplyTarget | null;
  pendingFiles: PendingUploadItem[];
  canSendMessage: boolean;
  isStreaming: boolean;
  isConversationEmpty: boolean;
  hasUploadingFiles: boolean;
  taskPlan: TaskPlanSnapshot | null;
  contextUsage: ReactContextUsageSummary | null;
  isContextUsageLoading: boolean;
  supportsImageInput: boolean;
  thinkingModes: ChatThinkingMode[];
  selectedThinkingMode: ChatThinkingMode | null;
  webSearchProviders: ChatWebSearchProviderOption[];
  selectedWebSearchProvider: string | null;
  imageInputRef: RefObject<HTMLInputElement>;
  documentInputRef: RefObject<HTMLInputElement>;
  onInputChange: (value: string) => void;
  onThinkingModeChange: (mode: ChatThinkingMode) => void;
  onWebSearchProviderChange: (providerKey: string) => void;
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
  compactStatusMessage,
  replyTarget,
  pendingFiles,
  canSendMessage,
  isStreaming,
  isConversationEmpty,
  hasUploadingFiles,
  taskPlan,
  contextUsage,
  isContextUsageLoading,
  supportsImageInput,
  thinkingModes,
  selectedThinkingMode,
  webSearchProviders,
  selectedWebSearchProvider,
  imageInputRef,
  documentInputRef,
  onInputChange,
  onThinkingModeChange,
  onWebSearchProviderChange,
  onKeyDown,
  onPaste,
  onSubmit,
  onStop,
  onCancelReply,
  onImageInputChange,
  onDocumentInputChange,
  onRemovePendingFile,
}: ChatComposerProps) {
  const hasWebSearchSelector =
    webSearchProviders.length > 0 && selectedWebSearchProvider !== null;
  const hasThinkingSelector =
    thinkingModes.length > 0 && selectedThinkingMode !== null;
  const selectedWebSearchProviderOption =
    webSearchProviders.find(
      (provider) => provider.key === selectedWebSearchProvider,
    ) ?? null;
  const selectedThinkingModeLabel =
    selectedThinkingMode === "thinking"
      ? "Thinking"
      : selectedThinkingMode === "auto"
        ? "Auto"
        : "Fast";
  const SelectedThinkingModeIcon =
    selectedThinkingMode === "thinking"
      ? Brain
      : selectedThinkingMode === "auto"
        ? RefreshCw
        : Zap;
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const replyPreview = replyTarget?.question.replace(/\s+/g, " ").trim() ?? "";

  /**
   * When the assistant asks a clarify question, move focus into the composer
   * immediately so the next user action is answering rather than hunting for
   * an extra reply affordance.
   */
  useEffect(() => {
    if (!replyTarget) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      const nextTextarea = textareaRef.current;
      if (!nextTextarea || nextTextarea.disabled) {
        return;
      }

      nextTextarea.focus();
      const cursorPosition = nextTextarea.value.length;
      nextTextarea.setSelectionRange(cursorPosition, cursorPosition);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [replyTarget]);

  return (
    <div
      className={`mx-auto w-full max-w-3xl bg-gradient-to-t from-background via-background to-transparent px-4 pb-4 pt-1 transition-transform duration-100 ease-out ${
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

      {compactStatusMessage && (
        <div
          className="mb-2 flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/10 px-4 py-2.5 text-sm text-foreground shadow-sm"
          aria-live="polite"
        >
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          <span>{compactStatusMessage}</span>
        </div>
      )}

      <div
        className={`chat-composer-transition-surface ${
          taskPlan ? "chat-composer-transition-surface-with-plan" : ""
        }`}
      >
        {taskPlan && <ComposerTaskPlan taskPlan={taskPlan} />}

        <form
          onSubmit={onSubmit}
          className={`relative overflow-hidden rounded-2xl border bg-background shadow-lg transition-all focus-within:border-ring ${
            taskPlan ? "-mt-px rounded-t-[12px]" : ""
          }`}
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

          {replyTarget && (
            <div className="px-3 pt-3">
              <div className="flex items-center gap-2 rounded-lg border border-border/50 bg-muted/20 px-2.5 py-1.5 text-xs text-muted-foreground">
                <MessageSquare className="h-3.5 w-3.5 shrink-0 text-primary/75" />
                <span className="shrink-0 text-[11px] font-medium text-foreground/75">
                  Replying
                </span>
                <p className="min-w-0 flex-1 truncate text-[12px] text-foreground/65">
                  {replyPreview}
                </p>
                <button
                  type="button"
                  onClick={onCancelReply}
                  className="rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                  title="Clear reply context"
                  aria-label="Clear reply context"
                >
                  <XCircle className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}

          <Textarea
            ref={textareaRef}
            value={inputMessage}
            onChange={(event) => onInputChange(event.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            placeholder={replyTarget ? "Write your answer..." : "Ask anything"}
            className={`min-h-[60px] w-full resize-none border-0 shadow-none focus:shadow-none focus:outline-none focus-visible:ring-0 focus-visible:shadow-none ${
              replyTarget ? "px-4 pb-3 pt-2.5" : "p-4"
            }`}
            disabled={isStreaming}
          />

          <div className="flex items-center justify-between gap-3 px-4 pb-3">
            <div className="flex min-w-0 items-center gap-1.5">
              <DropdownMenu modal={false}>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 rounded-full"
                  >
                    <Plus className="h-4 w-4" />
                    <span className="sr-only">Attach</span>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  size="medium"
                  className="z-[60]"
                >
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

              {hasThinkingSelector && (
                <Select
                  value={selectedThinkingMode}
                  onValueChange={(value) =>
                    onThinkingModeChange(value as ChatThinkingMode)
                  }
                >
                  <SelectTrigger
                    size="medium"
                    aria-label="Thinking mode"
                    className="h-7 w-auto min-w-[5.75rem] rounded-full border-border/70 bg-background px-2 text-[11px] text-foreground shadow-none"
                  >
                    <span className="flex items-center gap-1.5">
                      <SelectedThinkingModeIcon className="h-3.5 w-3.5" />
                      <span>{selectedThinkingModeLabel}</span>
                    </span>
                  </SelectTrigger>
                  <SelectContent size="medium">
                    {thinkingModes.includes("auto") && (
                      <SelectItem value="auto">
                        <div className="flex items-center gap-2">
                          <RefreshCw className="h-3.5 w-3.5" />
                          <span>Auto</span>
                        </div>
                      </SelectItem>
                    )}
                    {thinkingModes.includes("fast") && (
                      <SelectItem value="fast">
                        <div className="flex items-center gap-2">
                          <Zap className="h-3.5 w-3.5" />
                          <span>Fast</span>
                        </div>
                      </SelectItem>
                    )}
                    {thinkingModes.includes("thinking") && (
                      <SelectItem value="thinking">
                        <div className="flex items-center gap-2">
                          <Brain className="h-3.5 w-3.5" />
                          <span>Thinking</span>
                        </div>
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              )}

              {hasWebSearchSelector && (
                <Select
                  value={selectedWebSearchProvider}
                  onValueChange={onWebSearchProviderChange}
                >
                  <SelectTrigger
                    size="medium"
                    aria-label="Web search provider"
                    className="h-7 w-auto min-w-[6.5rem] max-w-[7.25rem] rounded-full border-border/70 bg-background px-2 text-[11px] text-foreground shadow-none"
                  >
                    {selectedWebSearchProviderOption ? (
                      <WebSearchProviderBadge
                        name={selectedWebSearchProviderOption.name}
                        logoUrl={selectedWebSearchProviderOption.logoUrl}
                        textClassName="text-[11px]"
                      />
                    ) : (
                      <SelectValue placeholder="Search" />
                    )}
                  </SelectTrigger>
                  <SelectContent size="medium">
                    {webSearchProviders.map((provider) => (
                      <SelectItem key={provider.key} value={provider.key}>
                        <WebSearchProviderBadge
                          name={provider.name}
                          logoUrl={provider.logoUrl}
                        />
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>

            <div className="flex items-center gap-2">
              {hasUploadingFiles && (
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span>Processing attachments...</span>
                </div>
              )}
              {compactStatusMessage && (
                <div className="hidden items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-1 text-[11px] font-medium text-foreground/80 sm:flex">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                  <span>Compacting...</span>
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
    </div>
  );
}
