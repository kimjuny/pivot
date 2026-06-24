import { memo, useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import {
  Check,
  CheckCircle2,
  ClipboardList,
  Copy,
  MessageCircleQuestion,
  MessagesSquare,
  Pencil,
  Square,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import DraggableDialog from "@/components/DraggableDialog";
import { Spinner } from "@/components/ui/spinner";
import { useTheme } from "@/lib/use-theme";
import { copyTextToClipboard } from "@/utils/clipboard";
import { formatTimestamp } from "@/utils/timestamp";

import type { ChatMessage, SkillChangeApprovalRequest } from "../types";
import {
  calculateDuration,
  extractSkillChangeApprovalRequest,
  formatTokenCount,
  isClarifyMessage,
} from "../utils/chatSelectors";
import { AssistantAttachmentList } from "./AssistantAttachmentList";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { RecursionCard } from "./RecursionCard";
import { TokenUsageLabel } from "./TokenUsageLabel";

interface AssistantMessageBlockProps {
  message: ChatMessage;
  isStreaming: boolean;
  onReplyTask: (taskId: string | null) => void;
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
 * Finds the index at which to split the recursions array so that the plan
 * review section can be inserted between the plan-tool recursion and the
 * execution recursions that follow.
 *
 * The plan tool call always lives in the recursion whose events contain a
 * `tool_call` with `name === "plan"`. All recursions after that index are
 * post-plan execution iterations.
 */
function findPlanRecursionSplitIndex(
  recursions: ChatMessage["recursions"],
): number {
  if (!recursions) return 0;
  for (let i = 0; i < recursions.length; i += 1) {
    const hasPlanToolCall = recursions[i].events.some((event) => {
      if (event.type !== "tool_call") return false;
      const data = event.data as
        | { tool_calls?: Array<{ name: string }> }
        | undefined;
      return data?.tool_calls?.some((tc) => tc.name === "plan") ?? false;
    });
    if (hasPlanToolCall) return i + 1;
  }
  return 0;
}

/**
 * Renders the assistant side of the timeline, including recursions and final answer state.
 */
export const AssistantMessageBlock = memo(function AssistantMessageBlock({
  message,
  isStreaming,
  onReplyTask,
  onApproveSkillChange,
  onRejectSkillChange,
  onPlanApprove,
  onPlanReject,
  onPlanEdit,
  planReviewSubmitting,
}: AssistantMessageBlockProps) {
  const clarifyMessage = isClarifyMessage(message);
  const approvalRequest = extractSkillChangeApprovalRequest(message);
  const [hasCopied, setHasCopied] = useState(false);
  const copyResetTimeoutRef = useRef<number | null>(null);
  const canReplyToClarify =
    clarifyMessage && message.status === "waiting_input" && Boolean(message.task_id);
  const canRenderApprovalActions =
    canReplyToClarify &&
    typeof message.task_id === "string" &&
    approvalRequest !== undefined;
  const hasFooterMetadata =
    message.status === "completed" ||
    message.status === "error" ||
    message.status === "stopped";

  // Final task duration for the footer: first recursion start → last
  // recursion end. Only meaningful once the task has settled; the live
  // counter lives in the Composer while running.
  const taskStartTime = message.recursions?.[0]?.startTime ?? message.timestamp;
  const taskEndTime = message.recursions?.at(-1)?.endTime;
  const taskDurationSeconds = calculateDuration(taskStartTime, taskEndTime);

  // Plan review state
  const planReview = message.planReview;
  const isPlanReviewActive = !planReview?.approved;
  const planRecursionSplit = planReview
    ? findPlanRecursionSplitIndex(message.recursions)
    : 0;
  const prePlanRecursions = planReview
    ? message.recursions?.slice(0, planRecursionSplit) ?? []
    : message.recursions ?? [];
  const postPlanRecursions = planReview
    ? message.recursions?.slice(planRecursionSplit) ?? []
    : [];

  // DraggableDialog + Monaco editor for plan editing
  const [planEditOpen, setPlanEditOpen] = useState(false);
  const [planEditText, setPlanEditText] = useState("");
  const { theme } = useTheme();
  const monacoTheme = theme === "dark" ? "vs-dark" : "light";

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  const handleCopyMessage = async () => {
    if (!message.content) {
      return;
    }

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
  };

  const handleOpenPlanEdit = () => {
    setPlanEditText(planReview?.plan_text ?? "");
    setPlanEditOpen(true);
  };

  const handleSavePlanEdit = () => {
    onPlanEdit(message.task_id!, planEditText);
    setPlanEditOpen(false);
  };

  /** Renders a list of recursions with their mid-task inputs. */
  const renderRecursions = (
    recursions: ChatMessage["recursions"],
    inputOffset: number,
  ) => {
    if (!recursions || recursions.length === 0) return null;
    return (
      <div className="space-y-2">
        {recursions.map((recursion, index) => {
          const inputIndex = inputOffset + index;
          return (
            <div key={`${message.id}-${recursion.uid}`}>
              <RecursionCard recursion={recursion} />
              {message.midTaskInputs?.[inputIndex] && (
                <div className="mt-2 flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-none bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground shadow-sm">
                    {message.midTaskInputs[inputIndex].message}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="space-y-2">
      {/* Pre-plan recursions (plan tool call) */}
      {renderRecursions(prePlanRecursions, 0)}

      {/* Plan Review section — persistent, visible even after approval */}
      {planReview && (
        <div className="rounded-lg bg-background/50 p-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <ClipboardList className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100" />
              <span className="text-xs font-semibold text-foreground">
                PLAN REVIEW
              </span>
            </div>
            {isPlanReviewActive && (
              <div className="flex items-center gap-2">
                {planReviewSubmitting ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Spinner size={12} />
                    <span>Processing...</span>
                  </div>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => onPlanReject(message.task_id!)}
                      className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-danger/30 hover:text-danger"
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      onClick={handleOpenPlanEdit}
                      className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-info/30 hover:text-info"
                    >
                      <Pencil className="mr-1 inline h-3 w-3" />
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => onPlanApprove(message.task_id!)}
                      className="rounded-full border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-medium text-success transition-colors hover:bg-success/15"
                    >
                      Approve
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
          <div className="pl-5 text-sm leading-relaxed text-foreground">
            {planReview.plan_text && (
              <MarkdownRenderer content={planReview.plan_text} />
            )}
          </div>
        </div>
      )}

      {/* Post-plan recursions (execution iterations) */}
      {renderRecursions(postPlanRecursions, planRecursionSplit)}

      {/* FINAL ANSWER / QUESTION / Skill Change Approval section */}
      <div className="group relative pb-8">
        {(message.content || (message.assistantAttachments?.length ?? 0) > 0) && (
          <div className="rounded-lg bg-background/50 p-3">
            <div className="mb-2 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                {clarifyMessage ? (
                  <>
                    <MessageCircleQuestion className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100" />
                    <span className="text-xs font-semibold text-foreground">
                      QUESTION
                    </span>
                  </>
                ) : (
                  <>
                    <MessagesSquare className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100" />
                    <span className="text-xs font-semibold text-foreground">
                      FINAL ANSWER
                    </span>
                  </>
                )}
              </div>
              {canRenderApprovalActions ? (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={isStreaming}
                    onClick={() =>
                      onRejectSkillChange(message.task_id!, approvalRequest)
                    }
                    className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-danger/30 hover:text-danger disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Reject
                  </button>
                  <button
                    type="button"
                    disabled={isStreaming}
                    onClick={() =>
                      onApproveSkillChange(message.task_id!, approvalRequest)
                    }
                    className="rounded-full border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-medium text-success transition-colors hover:bg-success/15 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Approve
                  </button>
                </div>
              ) : (
                canReplyToClarify && (
                  <button
                    type="button"
                    onClick={() => onReplyTask(message.task_id || null)}
                    className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-info/30 hover:text-info"
                  >
                    Reply
                  </button>
                )
              )}
            </div>
            <div className="pl-5 text-sm leading-relaxed text-foreground">
              {message.content && <MarkdownRenderer content={message.content} />}
              <AssistantAttachmentList attachments={message.assistantAttachments} />
            </div>
          </div>
        )}

        {message.status === "error" && message.errorMessage && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-3">
            <div className="mb-2 flex items-center gap-1.5">
              <XCircle className="h-3.5 w-3.5 text-danger" />
              <span className="text-xs font-semibold text-foreground">ERROR</span>
            </div>
            <div className="pl-5 text-sm leading-relaxed text-foreground whitespace-pre-wrap">
              {message.errorMessage}
            </div>
          </div>
        )}

        {hasFooterMetadata ? (
          <div className="pointer-events-none absolute bottom-0 left-0 right-0 flex items-center gap-2 px-3 opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
            {message.status === "completed" && (
              <>
                <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">Completed</span>
                {taskEndTime && taskDurationSeconds > 0 && (
                  <span className="ml-1 text-xs tabular-nums text-muted-foreground">
                    • {taskDurationSeconds}s
                  </span>
                )}
                {message.totalTokens && (
                  <TokenUsageLabel
                    tokens={message.totalTokens}
                    label={`• Total: ${formatTokenCount(message.totalTokens.total_tokens)} tokens`}
                    className="ml-2 cursor-help whitespace-nowrap text-xs tabular-nums text-muted-foreground underline decoration-dotted underline-offset-2"
                  />
                )}
              </>
            )}
            {message.status === "error" && (
              <>
                <XCircle className="h-3.5 w-3.5 text-danger" />
                <span className="text-xs text-danger">Error</span>
              </>
            )}
            {message.status === "stopped" && (
              <>
                <Square className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">Stopped</span>
              </>
            )}
            <div className="ml-auto flex items-center gap-1.5">
              {message.content ? (
                <button
                  type="button"
                  onClick={() => {
                    void handleCopyMessage();
                  }}
                  className="flex h-7 w-7 items-center justify-center rounded-lg bg-transparent text-muted-foreground/75 transition-colors hover:bg-sidebar-accent hover:text-foreground focus-visible:bg-sidebar-accent focus-visible:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
              <span className="text-xs text-muted-foreground">
                {formatTimestamp(message.timestamp)}
              </span>
            </div>
          </div>
        ) : null}
      </div>

      {/* Plan edit dialog — DraggableDialog + Monaco Editor */}
      <DraggableDialog
        open={planEditOpen}
        onOpenChange={setPlanEditOpen}
        title="Edit Plan"
        size="large"
        fullscreenable
        headerAction={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPlanEditOpen(false)}
              className="rounded-full border border-border/70 bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-border"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSavePlanEdit}
              className="rounded-full border border-success/30 bg-success/10 px-2.5 py-1 text-[11px] font-medium text-success transition-colors hover:bg-success/15"
            >
              Save &amp; Approve
            </button>
          </div>
        }
      >
        <Editor
          height="100%"
          language="markdown"
          value={planEditText}
          onChange={(value) => setPlanEditText(value ?? "")}
          theme={monacoTheme}
          options={{
            automaticLayout: true,
            readOnly: false,
            fontSize: 13,
            lineNumbers: "on",
            minimap: { enabled: false },
            renderLineHighlight: "none",
            renderWhitespace: "selection",
            scrollBeyondLastLine: false,
            wordWrap: "on",
          }}
        />
      </DraggableDialog>
    </div>
  );
});
