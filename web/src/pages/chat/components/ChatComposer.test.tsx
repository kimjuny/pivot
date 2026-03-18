import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatComposer } from "./ChatComposer";

describe("ChatComposer", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the Codex-style task plan above the composer when available", async () => {
    render(
      <ChatComposer
        inputMessage=""
        error={null}
        compactStatusMessage={null}
        replyTaskId={null}
        pendingFiles={[]}
        canSendMessage={false}
        isStreaming={false}
        isConversationEmpty={false}
        hasUploadingFiles={false}
        taskPlan={{
          messageId: "assistant-1",
          steps: [
            {
              stepId: "1",
              title: "Inspect the repository",
              description: "Review the current files",
              completionCriteria: "Context is collected",
              status: "running",
            },
            {
              stepId: "2",
              title: "Ship the fix",
              description: "Patch the bug",
              completionCriteria: "Change is merged",
              status: "pending",
            },
          ],
        }}
        contextUsage={null}
        isContextUsageLoading={false}
        supportsImageInput={false}
        imageInputRef={{ current: null }}
        documentInputRef={{ current: null }}
        onInputChange={vi.fn()}
        onKeyDown={vi.fn()}
        onPaste={vi.fn()}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        onCancelReply={vi.fn()}
        onImageInputChange={vi.fn()}
        onDocumentInputChange={vi.fn()}
        onRemovePendingFile={vi.fn()}
      />,
    );

    expect(
      screen.getByText("0 out of 2 tasks completed"),
    ).toBeInTheDocument();
    expect(screen.getByText("Inspect the repository")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Collapse task plan" }),
    ).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask anything")).toBeInTheDocument();
  });

  it("collapses and expands the task plan from the header control", async () => {
    const user = userEvent.setup();

    render(
      <ChatComposer
        inputMessage=""
        error={null}
        compactStatusMessage={null}
        replyTaskId={null}
        pendingFiles={[]}
        canSendMessage={false}
        isStreaming={false}
        isConversationEmpty={false}
        hasUploadingFiles={false}
        taskPlan={{
          messageId: "assistant-1",
          steps: [
            {
              stepId: "1",
              title: "Inspect the repository",
              description: "Review the current files",
              completionCriteria: "Context is collected",
              status: "done",
            },
          ],
        }}
        contextUsage={null}
        isContextUsageLoading={false}
        supportsImageInput={false}
        imageInputRef={{ current: null }}
        documentInputRef={{ current: null }}
        onInputChange={vi.fn()}
        onKeyDown={vi.fn()}
        onPaste={vi.fn()}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        onCancelReply={vi.fn()}
        onImageInputChange={vi.fn()}
        onDocumentInputChange={vi.fn()}
        onRemovePendingFile={vi.fn()}
      />,
    );

    await screen.findByRole("button", { name: "Collapse task plan" });
    await user.click(screen.getByRole("button", { name: "Collapse task plan" }));
    expect(
      screen.getByRole("button", { name: "Expand task plan" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("composer-task-plan-body")).toHaveAttribute(
      "aria-hidden",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "Expand task plan" }));
    expect(screen.getByTestId("composer-task-plan-body")).toHaveAttribute(
      "aria-hidden",
      "false",
    );
    expect(screen.getByText("Inspect the repository")).toBeInTheDocument();
  });

  it("auto-collapses the task plan after the task settles", async () => {
    vi.useFakeTimers();

    const { rerender } = render(
      <ChatComposer
        inputMessage=""
        error={null}
        compactStatusMessage={null}
        replyTaskId={null}
        pendingFiles={[]}
        canSendMessage={false}
        isStreaming={false}
        isConversationEmpty={false}
        hasUploadingFiles={false}
        taskPlan={{
          messageId: "assistant-1",
          taskId: "task-1",
          steps: [
            {
              stepId: "1",
              title: "Inspect the repository",
              description: "Review the current files",
              completionCriteria: "Context is collected",
              status: "running",
            },
            {
              stepId: "2",
              title: "Ship the fix",
              description: "Patch the bug",
              completionCriteria: "Change is merged",
              status: "pending",
            },
          ],
        }}
        contextUsage={null}
        isContextUsageLoading={false}
        supportsImageInput={false}
        imageInputRef={{ current: null }}
        documentInputRef={{ current: null }}
        onInputChange={vi.fn()}
        onKeyDown={vi.fn()}
        onPaste={vi.fn()}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        onCancelReply={vi.fn()}
        onImageInputChange={vi.fn()}
        onDocumentInputChange={vi.fn()}
        onRemovePendingFile={vi.fn()}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20);
    });
    expect(
      screen.getByRole("button", { name: "Collapse task plan" }),
    ).toBeInTheDocument();

    rerender(
      <ChatComposer
        inputMessage=""
        error={null}
        compactStatusMessage={null}
        replyTaskId={null}
        pendingFiles={[]}
        canSendMessage={false}
        isStreaming={false}
        isConversationEmpty={false}
        hasUploadingFiles={false}
        taskPlan={{
          messageId: "assistant-1",
          taskId: "task-1",
          steps: [
            {
              stepId: "1",
              title: "Inspect the repository",
              description: "Review the current files",
              completionCriteria: "Context is collected",
              status: "done",
            },
            {
              stepId: "2",
              title: "Ship the fix",
              description: "Patch the bug",
              completionCriteria: "Change is merged",
              status: "done",
            },
          ],
        }}
        contextUsage={null}
        isContextUsageLoading={false}
        supportsImageInput={false}
        imageInputRef={{ current: null }}
        documentInputRef={{ current: null }}
        onInputChange={vi.fn()}
        onKeyDown={vi.fn()}
        onPaste={vi.fn()}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        onCancelReply={vi.fn()}
        onImageInputChange={vi.fn()}
        onDocumentInputChange={vi.fn()}
        onRemovePendingFile={vi.fn()}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(750);
    });
    expect(screen.getByTestId("composer-task-plan-body")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("shows a clear compacting notice while the runtime window is rebuilding", () => {
    render(
      <ChatComposer
        inputMessage=""
        error={null}
        compactStatusMessage="Compacting context. Please wait before stopping."
        replyTaskId={null}
        pendingFiles={[]}
        canSendMessage={false}
        isStreaming
        isConversationEmpty={false}
        hasUploadingFiles={false}
        taskPlan={null}
        contextUsage={null}
        isContextUsageLoading={false}
        supportsImageInput={false}
        imageInputRef={{ current: null }}
        documentInputRef={{ current: null }}
        onInputChange={vi.fn()}
        onKeyDown={vi.fn()}
        onPaste={vi.fn()}
        onSubmit={vi.fn()}
        onStop={vi.fn()}
        onCancelReply={vi.fn()}
        onImageInputChange={vi.fn()}
        onDocumentInputChange={vi.fn()}
        onRemovePendingFile={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Compacting context. Please wait before stopping."),
    ).toBeInTheDocument();
    expect(screen.getByText("Compacting...")).toBeInTheDocument();
  });
});
