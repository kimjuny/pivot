import type {
  ChangeEvent,
  ClipboardEvent,
  FormEvent,
  KeyboardEvent,
  RefObject,
  SyntheticEvent,
} from "react";
import { useEffect, useMemo, useRef, useState } from "react";
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

import { Badge } from "@/components/ui/badge";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupText,
  InputGroupTextarea,
} from "@/components/ui/input-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverAnchor,
  PopoverContent,
} from "@/components/ui/popover";
import { WebSearchProviderBadge } from "@/components/WebSearchProviderBadge";
import { cn } from "@/lib/utils";
import type { ReactContextUsageSummary } from "@/utils/api";
import type { ChatThinkingMode } from "@/utils/llmThinking";

import type {
  ChatReplyTarget,
  ChatWebSearchProviderOption,
  MandatorySkillSelection,
  PendingUploadItem,
  TaskPlanSnapshot,
} from "../types";
import { AttachmentList } from "./AttachmentList";
import { ComposerTaskPlan } from "./ComposerTaskPlan";
import { ContextUsageRing } from "./ContextUsageRing";

interface ChatComposerProps {
  inputMessage?: string;
  error: string | null;
  compactStatusMessage: string | null;
  replyTarget: ChatReplyTarget | null;
  pendingFiles: PendingUploadItem[];
  canSendMessage?: boolean;
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
  availableMandatorySkills: MandatorySkillSelection[];
  selectedMandatorySkills: MandatorySkillSelection[];
  imageInputRef: RefObject<HTMLInputElement>;
  documentInputRef: RefObject<HTMLInputElement>;
  resetDraftSignal?: number;
  onInputChange?: (value: string) => void;
  onAddMandatorySkill: (skill: MandatorySkillSelection) => void;
  onRemoveMandatorySkill: (skillName: string) => void;
  onThinkingModeChange: (mode: ChatThinkingMode) => void;
  onWebSearchProviderChange: (providerKey: string) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  onPaste: (event: ClipboardEvent<HTMLTextAreaElement>) => void;
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
  onSubmitMessage?: (message: string) => void | Promise<void>;
  onStop: () => void;
  onCancelReply: () => void;
  onImageInputChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onDocumentInputChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemovePendingFile: (clientId: string) => void | Promise<void>;
}

interface ActiveMandatorySkillMention {
  start: number;
  end: number;
  query: string;
}

/**
 * Detects the active slash-token near the caret so the composer can open the
 * mandatory-skill picker without replacing the native textarea editor.
 */
function getActiveMandatorySkillMention(
  value: string,
  selectionStart: number,
): ActiveMandatorySkillMention | null {
  const safeSelectionStart = Math.max(Math.min(selectionStart, value.length), 0);
  const beforeCaret = value.slice(0, safeSelectionStart);
  const tokenStart = Math.max(beforeCaret.lastIndexOf(" "), beforeCaret.lastIndexOf("\n")) + 1;
  const token = beforeCaret.slice(tokenStart);
  if (!token.startsWith("/")) {
    return null;
  }

  const query = token.slice(1);
  if (query.includes("/") || query.includes(":")) {
    return null;
  }

  return {
    start: tokenStart,
    end: safeSelectionStart,
    query,
  };
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
  availableMandatorySkills,
  selectedMandatorySkills,
  imageInputRef,
  documentInputRef,
  resetDraftSignal = 0,
  onInputChange,
  onAddMandatorySkill,
  onRemoveMandatorySkill,
  onThinkingModeChange,
  onWebSearchProviderChange,
  onKeyDown,
  onPaste,
  onSubmit,
  onSubmitMessage,
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
  const mandatorySkillItemRefs = useRef<
    Record<string, HTMLDivElement | null>
  >({});
  const hasSeenResetSignalRef = useRef(false);
  const [draftMessage, setDraftMessage] = useState(inputMessage ?? "");
  const [composerSelectionStart, setComposerSelectionStart] = useState(0);
  const [highlightedMandatorySkillIndex, setHighlightedMandatorySkillIndex] =
    useState(0);
  const [dismissedMandatorySkillMentionKey, setDismissedMandatorySkillMentionKey] =
    useState<string | null>(null);
  const computedCanSendMessage =
    canSendMessage ??
    (!isStreaming &&
      !hasUploadingFiles &&
      (draftMessage.trim().length > 0 || pendingFiles.length > 0));
  const replyPreview = replyTarget?.question.replace(/\s+/g, " ").trim() ?? "";
  const activeMandatorySkillMention = useMemo(
    () => getActiveMandatorySkillMention(draftMessage, composerSelectionStart),
    [composerSelectionStart, draftMessage],
  );
  const activeMandatorySkillMentionKey = activeMandatorySkillMention
    ? `${activeMandatorySkillMention.start}:${activeMandatorySkillMention.query}`
    : null;
  const filteredMandatorySkills = useMemo(() => {
    const selectedNames = new Set(
      selectedMandatorySkills.map((skill) => skill.name),
    );
    const normalizedQuery =
      activeMandatorySkillMention?.query.trim().toLowerCase() ?? "";
    return availableMandatorySkills.filter((skill) => {
      if (selectedNames.has(skill.name)) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }

      return (
        skill.name.toLowerCase().includes(normalizedQuery) ||
        (skill.description ?? "").toLowerCase().includes(normalizedQuery)
      );
    });
  }, [
    activeMandatorySkillMention?.query,
    availableMandatorySkills,
    selectedMandatorySkills,
  ]);
  const isMandatorySkillPickerOpen =
    !isStreaming &&
    activeMandatorySkillMention !== null &&
    activeMandatorySkillMentionKey !== dismissedMandatorySkillMentionKey;

  /**
   * Keeps local draft ownership inside the composer while still letting the
   * container observe draft changes for debounced side effects like context
   * estimation.
   */
  const updateDraftMessage = (value: string) => {
    setDraftMessage(value);
    onInputChange?.(value);
  };

  /**
   * Submits the current local draft through the container-owned send path.
   */
  const submitDraftMessage = () => {
    if (!computedCanSendMessage || !onSubmitMessage) {
      return;
    }

    void onSubmitMessage(draftMessage);
  };

  /**
   * Centralizes mention dismissal so pointer and keyboard exits share the same
   * rule: keep the raw slash text intact, but stop treating the current token
   * as an active picker session until the user edits it again.
   */
  const dismissActiveMandatorySkillMention = () => {
    if (activeMandatorySkillMentionKey !== null) {
      setDismissedMandatorySkillMentionKey(activeMandatorySkillMentionKey);
    }
  };

  /**
   * Track the current caret so slash-trigger detection stays aligned with what
   * the user is actually editing instead of assuming the cursor sits at the end.
   */
  const syncComposerSelection = (
    event?: SyntheticEvent<HTMLTextAreaElement>,
  ) => {
    const nextSelectionStart =
      event?.currentTarget.selectionStart ??
      textareaRef.current?.selectionStart ??
      0;
    setComposerSelectionStart(nextSelectionStart);
  };

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
      setComposerSelectionStart(cursorPosition);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [replyTarget]);

  /**
   * Supports externally seeded drafts in tests and future restore flows
   * without turning the textarea back into a fully controlled parent state.
   */
  useEffect(() => {
    if (inputMessage === undefined) {
      return;
    }

    setDraftMessage(inputMessage);
  }, [inputMessage]);

  /**
   * Clears the local draft after successful send/reset signals from the
   * container so typing no longer re-renders the full conversation tree.
   */
  useEffect(() => {
    if (!hasSeenResetSignalRef.current) {
      hasSeenResetSignalRef.current = true;
      return;
    }

    setDraftMessage("");
    setComposerSelectionStart(0);
    setDismissedMandatorySkillMentionKey(null);
  }, [resetDraftSignal]);

  /**
   * Keep the composer height aligned with the current draft so the reply and
   * action rows can stay visually attached instead of trapping the user in a
   * tiny scroll area.
   */
  useEffect(() => {
    const nextTextarea = textareaRef.current;
    if (!nextTextarea) {
      return;
    }

    const minHeight = 60;
    const maxHeight = 320;
    nextTextarea.style.height = "0px";
    nextTextarea.style.height = `${Math.min(
      Math.max(nextTextarea.scrollHeight, minHeight),
      maxHeight,
    )}px`;
  }, [draftMessage, replyTarget]);

  useEffect(() => {
    setHighlightedMandatorySkillIndex(0);
  }, [activeMandatorySkillMention?.query]);

  useEffect(() => {
    if (activeMandatorySkillMentionKey === null) {
      setDismissedMandatorySkillMentionKey(null);
    }
  }, [activeMandatorySkillMentionKey]);

  /**
   * Keeps keyboard navigation visible inside the bounded picker viewport so
   * ArrowDown/ArrowUp feel like moving a real selection instead of sending the
   * active item out of sight.
   */
  useEffect(() => {
    if (!isMandatorySkillPickerOpen) {
      return;
    }

    const highlightedSkill =
      filteredMandatorySkills[highlightedMandatorySkillIndex] ?? null;
    if (!highlightedSkill) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      mandatorySkillItemRefs.current[highlightedSkill.name]?.scrollIntoView({
        block: "nearest",
      });
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [
    filteredMandatorySkills,
    highlightedMandatorySkillIndex,
    isMandatorySkillPickerOpen,
  ]);

  /**
   * Converts the active slash token into one structured mandatory-skill chip
   * while keeping the remaining textarea content untouched.
   */
  const selectMandatorySkill = (skill: MandatorySkillSelection) => {
    if (!activeMandatorySkillMention) {
      return;
    }

    const beforeMention = draftMessage.slice(0, activeMandatorySkillMention.start);
    const afterMention = draftMessage.slice(activeMandatorySkillMention.end);
    const nextMessage =
      beforeMention.endsWith(" ") && afterMention.startsWith(" ")
        ? `${beforeMention}${afterMention.slice(1)}`
        : `${beforeMention}${afterMention}`;
    setDismissedMandatorySkillMentionKey(null);
    onAddMandatorySkill(skill);
    updateDraftMessage(nextMessage);

    window.requestAnimationFrame(() => {
      const nextTextarea = textareaRef.current;
      if (!nextTextarea) {
        return;
      }

      const nextCursorPosition = Math.min(
        activeMandatorySkillMention.start,
        nextMessage.length,
      );
      nextTextarea.focus();
      nextTextarea.setSelectionRange(nextCursorPosition, nextCursorPosition);
      setComposerSelectionStart(nextCursorPosition);
    });
  };

  /**
   * Reserves arrow and enter handling for the open skill picker so chat send
   * shortcuts do not steal those keystrokes while the user is choosing a skill.
   */
  const handleTextareaKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (isMandatorySkillPickerOpen) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (filteredMandatorySkills.length > 0) {
          setHighlightedMandatorySkillIndex((previous) =>
            previous >= filteredMandatorySkills.length - 1 ? 0 : previous + 1,
          );
        }
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (filteredMandatorySkills.length > 0) {
          setHighlightedMandatorySkillIndex((previous) =>
            previous <= 0 ? filteredMandatorySkills.length - 1 : previous - 1,
          );
        }
        return;
      }

      if (
        (event.key === "Enter" || event.key === "Tab") &&
        !event.shiftKey &&
        filteredMandatorySkills.length > 0
      ) {
        event.preventDefault();
        selectMandatorySkill(
          filteredMandatorySkills[highlightedMandatorySkillIndex] ??
            filteredMandatorySkills[0],
        );
        return;
      }

      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        dismissActiveMandatorySkillMention();
      }

      if (event.key === "Escape") {
        dismissActiveMandatorySkillMention();
        return;
      }
    }

    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitDraftMessage();
      return;
    }

    onKeyDown?.(event);
  };

  /**
   * Normalizes button and enter-key sends into the same local draft submit path.
   */
  const handleFormSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submitDraftMessage();
    onSubmit?.(event);
  };

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
          onSubmit={handleFormSubmit}
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

          <InputGroup className="rounded-none !border-0 bg-transparent !shadow-none has-[[data-slot=input-group-control]:focus-visible]:ring-0">
            {replyTarget && (
              <InputGroupAddon
                align="block-start"
                className="gap-1.5 bg-muted/20 px-3 pb-1.5 pt-2"
              >
                <MessageSquare className="h-3.5 w-3.5 shrink-0 text-primary/75" />
                <InputGroupText className="shrink-0 text-[11px] font-medium text-foreground/75">
                  Replying
                </InputGroupText>
                <p className="min-w-0 flex-1 truncate text-[12px] text-foreground/65">
                  {replyPreview}
                </p>
                <InputGroupButton
                  type="button"
                  size="icon-xs"
                  variant="ghost"
                  onClick={onCancelReply}
                  className="ml-auto rounded-full text-muted-foreground hover:bg-background hover:text-foreground"
                  title="Clear reply context"
                  aria-label="Clear reply context"
                >
                  <XCircle className="h-3.5 w-3.5" />
                </InputGroupButton>
              </InputGroupAddon>
            )}

            {selectedMandatorySkills.length > 0 && (
              <InputGroupAddon
                align="block-start"
                className="flex-wrap gap-1.5 bg-background px-3 pb-1.5 pt-1"
              >
                <InputGroupText className="text-[11px] font-medium text-foreground/70">
                  Skills
                </InputGroupText>
                {selectedMandatorySkills.map((skill) => (
                  <Badge
                    key={skill.name}
                    variant="secondary"
                    className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
                  >
                    <span>{skill.name}</span>
                    <button
                      type="button"
                      onClick={() => onRemoveMandatorySkill(skill.name)}
                      className="rounded-full p-0.5 text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                      aria-label={`Remove ${skill.name}`}
                      title={`Remove ${skill.name}`}
                    >
                      <XCircle className="h-3 w-3" />
                    </button>
                  </Badge>
                ))}
              </InputGroupAddon>
            )}

            <Popover
              open={isMandatorySkillPickerOpen}
              modal={false}
              onOpenChange={(open) => {
                if (!open) {
                  dismissActiveMandatorySkillMention();
                }
              }}
            >
              <PopoverAnchor asChild>
                <InputGroupTextarea
                  ref={textareaRef}
                  value={draftMessage}
                  onChange={(event) => {
                    updateDraftMessage(event.target.value);
                    setComposerSelectionStart(event.target.selectionStart ?? 0);
                    setDismissedMandatorySkillMentionKey(null);
                  }}
                  onKeyDown={handleTextareaKeyDown}
                  onFocus={syncComposerSelection}
                  onClick={syncComposerSelection}
                  onMouseUp={syncComposerSelection}
                  onKeyUp={syncComposerSelection}
                  onSelect={syncComposerSelection}
                  onPaste={onPaste}
                  placeholder={replyTarget ? "Write your answer..." : "Ask anything"}
                  className="min-h-[60px] max-h-80 overflow-y-auto !border-0 px-4 !shadow-none focus:!border-0 focus-visible:!border-0 [field-sizing:content]"
                  disabled={isStreaming}
                />
              </PopoverAnchor>
              <PopoverContent
                align="start"
                side="top"
                sideOffset={10}
                onOpenAutoFocus={(event) => event.preventDefault()}
                onCloseAutoFocus={(event) => event.preventDefault()}
                onInteractOutside={dismissActiveMandatorySkillMention}
                className="z-[2147483647] w-[min(16rem,calc((100vw-3rem)*0.67))] overflow-hidden rounded-2xl p-0"
              >
                <Command
                  shouldFilter={false}
                  value={
                    filteredMandatorySkills[highlightedMandatorySkillIndex]?.name ?? ""
                  }
                  className="rounded-[inherit]"
                >
                  <CommandList className="max-h-64">
                    <CommandEmpty>
                      {availableMandatorySkills.length === 0
                        ? "No skills available for this agent."
                        : "No matching skills found."}
                    </CommandEmpty>
                    <CommandGroup>
                      {filteredMandatorySkills.map((skill, index) => (
                        <HoverCard
                          key={skill.name}
                          openDelay={450}
                          closeDelay={120}
                        >
                          <HoverCardTrigger asChild>
                            <CommandItem
                              ref={(node) => {
                                mandatorySkillItemRefs.current[skill.name] =
                                  node;
                              }}
                              value={skill.name}
                              onSelect={() => selectMandatorySkill(skill)}
                              onMouseEnter={() =>
                                setHighlightedMandatorySkillIndex(index)
                              }
                              className={cn(
                                "cursor-pointer items-start",
                                "aria-selected:bg-accent aria-selected:text-accent-foreground",
                              )}
                            >
                              <div className="min-w-0">
                                <div className="truncate font-mono text-xs font-medium">
                                  {skill.name}
                                </div>
                                <div className="truncate text-xs text-muted-foreground">
                                  {skill.description || skill.path}
                                </div>
                              </div>
                            </CommandItem>
                          </HoverCardTrigger>
                          <HoverCardContent
                            side="right"
                            align="start"
                            className="w-80 space-y-2 p-3"
                          >
                            <div className="font-mono text-xs font-medium text-foreground">
                              {skill.name}
                            </div>
                            <p className="text-xs leading-relaxed text-muted-foreground">
                              {skill.description || "No description provided."}
                            </p>
                          </HoverCardContent>
                        </HoverCard>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>

            <InputGroupAddon
              align="block-end"
              className="flex-wrap gap-2 bg-background/90"
            >
              <div className="flex min-w-0 items-center gap-1.5">
                <DropdownMenu modal={false}>
                  <DropdownMenuTrigger asChild>
                    <InputGroupButton
                      variant="ghost"
                      size="icon-sm"
                      className="rounded-full"
                    >
                      <Plus className="h-4 w-4" />
                      <span className="sr-only">Attach</span>
                    </InputGroupButton>
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

              <div className="flex min-w-0 items-center gap-2 sm:ml-auto">
                {hasUploadingFiles && (
                  <InputGroupText className="text-xs text-muted-foreground">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Processing attachments...</span>
                  </InputGroupText>
                )}
                {compactStatusMessage && (
                  <InputGroupText className="hidden rounded-full border border-primary/20 bg-primary/10 px-2 py-1 text-[11px] font-medium text-foreground/80 sm:flex">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    <span>Compacting...</span>
                  </InputGroupText>
                )}
                <ContextUsageRing
                  usage={contextUsage}
                  isLoading={isContextUsageLoading}
                />
                {isStreaming ? (
                  <InputGroupButton
                    type="button"
                    onClick={onStop}
                    variant="destructive"
                    size="icon-sm"
                    className="rounded-full"
                    title="Stop execution"
                  >
                    <Square className="h-4 w-4" fill="currentColor" />
                    <span className="sr-only">Stop execution</span>
                  </InputGroupButton>
                ) : (
                  <InputGroupButton
                    type="submit"
                    variant="default"
                    disabled={!computedCanSendMessage}
                    size="icon-sm"
                    className="rounded-full"
                    title="Send message"
                  >
                    <ArrowUp className="h-4 w-4" />
                    <span className="sr-only">Send</span>
                  </InputGroupButton>
                )}
              </div>
            </InputGroupAddon>
          </InputGroup>
        </form>
      </div>
    </div>
  );
}
