import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatComposer } from "./ChatComposer";

function buildComposerProps(
  overrides: Partial<ComponentProps<typeof ChatComposer>> = {},
): ComponentProps<typeof ChatComposer> {
  return {
    inputMessage: "",
    error: null,
    compactStatusMessage: null,
    replyTarget: null,
    pendingFiles: [],
    canSendMessage: false,
    isStreaming: false,
    isConversationEmpty: false,
    hasUploadingFiles: false,
    taskPlan: null,
    contextUsage: null,
    isContextUsageLoading: false,
    supportsImageInput: false,
    thinkingModes: [],
    selectedThinkingMode: null,
    webSearchProviders: [],
    selectedWebSearchProvider: null,
    imageInputRef: { current: null },
    documentInputRef: { current: null },
    onInputChange: vi.fn(),
    onThinkingModeChange: vi.fn(),
    onWebSearchProviderChange: vi.fn(),
    onKeyDown: vi.fn(),
    onPaste: vi.fn(),
    onSubmit: vi.fn(),
    onStop: vi.fn(),
    onCancelReply: vi.fn(),
    onImageInputChange: vi.fn(),
    onDocumentInputChange: vi.fn(),
    onRemovePendingFile: vi.fn(),
    ...overrides,
  };
}

/**
 * Radix Select expects pointer-capture helpers that happy-dom does not ship.
 */
function applyPointerCapturePolyfill() {
  if (!("hasPointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "hasPointerCapture", {
      value: () => false,
      configurable: true,
    });
  }
  if (!("setPointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "setPointerCapture", {
      value: () => {},
      configurable: true,
    });
  }
  if (!("releasePointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "releasePointerCapture", {
      value: () => {},
      configurable: true,
    });
  }
}

describe("ChatComposer", () => {
  beforeEach(() => {
    applyPointerCapturePolyfill();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the Codex-style task plan above the composer when available", async () => {
    render(
      <ChatComposer
        {...buildComposerProps({
          taskPlan: {
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
          },
        })}
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

  it("renders an inline reply context card and focuses the composer", async () => {
    render(
      <ChatComposer
        {...buildComposerProps({
          replyTarget: {
            taskId: "task-clarify-1",
            question:
              "Which export format do you prefer, PDF or PowerPoint?",
          },
        })}
      />,
    );

    const textarea = screen.getByPlaceholderText("Write your answer...");
    expect(screen.getByText("Replying")).toBeInTheDocument();
    expect(
      screen.getByText("Which export format do you prefer, PDF or PowerPoint?"),
    ).toBeInTheDocument();
    await act(async () => {
      await Promise.resolve();
    });
    expect(textarea).toHaveFocus();
  });

  it("collapses and expands the task plan from the header control", async () => {
    const user = userEvent.setup();

    render(
      <ChatComposer
        {...buildComposerProps({
          taskPlan: {
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
          },
        })}
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
        {...buildComposerProps({
          taskPlan: {
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
          },
        })}
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
        {...buildComposerProps({
          taskPlan: {
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
          },
        })}
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
        {...buildComposerProps({
          compactStatusMessage:
            "Compacting context. Please wait before stopping.",
          isStreaming: true,
        })}
      />,
    );

    expect(
      screen.getByText("Compacting context. Please wait before stopping."),
    ).toBeInTheDocument();
    expect(screen.getByText("Compacting...")).toBeInTheDocument();
  });

  it("renders and updates the web search provider selector when options exist", async () => {
    const user = userEvent.setup();
    const handleProviderChange = vi.fn();

    render(
      <ChatComposer
        {...buildComposerProps({
          webSearchProviders: [
            { key: "tavily", name: "Tavily" },
            { key: "baidu", name: "Baidu AI Search" },
          ],
          selectedWebSearchProvider: "tavily",
          onWebSearchProviderChange: handleProviderChange,
        })}
      />,
    );

    await user.click(
      screen.getByRole("combobox", { name: "Web search provider" }),
    );
    await user.click(screen.getByRole("option", { name: "Baidu AI Search" }));

    expect(handleProviderChange).toHaveBeenCalledWith("baidu");
  });
});
