import { act, fireEvent, render, screen, within } from "@testing-library/react";
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
    availableMandatorySkills: [],
    selectedMandatorySkills: [],
    imageInputRef: { current: null },
    documentInputRef: { current: null },
    onInputChange: vi.fn(),
    onAddMandatorySkill: vi.fn(),
    onRemoveMandatorySkill: vi.fn(),
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

function placeComposerCaret(textarea: HTMLTextAreaElement, position: number) {
  act(() => {
    textarea.focus();
    textarea.setSelectionRange(position, position);
    fireEvent.select(textarea);
  });
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

  it("renders reply and action rows inside the input-group addons", () => {
    render(
      <ChatComposer
        {...buildComposerProps({
          replyTarget: {
            taskId: "task-clarify-2",
            question: "Please confirm whether we should prioritize mobile.",
          },
          canSendMessage: true,
          thinkingModes: ["auto", "fast"],
          selectedThinkingMode: "auto",
          webSearchProviders: [{ key: "tavily", name: "Tavily" }],
          selectedWebSearchProvider: "tavily",
        })}
      />,
    );

    const textarea = screen.getByPlaceholderText("Write your answer...");
    const group = textarea.closest('[data-slot="input-group"]');
    expect(group).not.toBeNull();
    expect(group?.querySelector('[data-align="block-start"]')).not.toBeNull();
    expect(group?.querySelector('[data-align="block-end"]')).not.toBeNull();

    const scopedGroup = within(group as HTMLElement);
    expect(scopedGroup.getByText("Replying")).toBeInTheDocument();
    expect(
      scopedGroup.getByRole("button", { name: "Clear reply context" }),
    ).toBeInTheDocument();
    expect(scopedGroup.getByRole("button", { name: "Attach" })).toBeInTheDocument();
    expect(scopedGroup.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("opens the slash picker and inserts one mandatory skill chip", async () => {
    const user = userEvent.setup();
    const handleInputChange = vi.fn();
    const handleAddMandatorySkill = vi.fn();

    render(
      <ChatComposer
        {...buildComposerProps({
          inputMessage: "/sam",
          availableMandatorySkills: [
            {
              name: "sample_skill",
              description: "Example skill description",
              path: "/workspace/skills/sample_skill/SKILL.md",
            },
          ],
          onInputChange: handleInputChange,
          onAddMandatorySkill: handleAddMandatorySkill,
        })}
      />,
    );

    const textarea = screen.getByPlaceholderText("Ask anything");
    await user.click(textarea);
    expect(textarea).toBeInstanceOf(HTMLTextAreaElement);
    if (!(textarea instanceof HTMLTextAreaElement)) {
      throw new Error("Expected the composer to render a textarea element.");
    }
    placeComposerCaret(textarea, 4);

    expect(
      await screen.findByText("Example skill description"),
    ).toBeInTheDocument();
    await user.click(screen.getByText("sample_skill"));

    expect(handleAddMandatorySkill).toHaveBeenCalledWith({
      name: "sample_skill",
      description: "Example skill description",
      path: "/workspace/skills/sample_skill/SKILL.md",
    });
    expect(handleInputChange).toHaveBeenCalledWith("");
  });

  it("closes the slash picker after clicking outside the composer", async () => {
    const user = userEvent.setup();

    render(
      <div>
        <button type="button">Outside area</button>
        <ChatComposer
          {...buildComposerProps({
            inputMessage: "/sam",
            availableMandatorySkills: [
              {
                name: "sample_skill",
                description: "Example skill description",
                path: "/workspace/skills/sample_skill/SKILL.md",
              },
            ],
          })}
        />
      </div>,
    );

    const textarea = screen.getByPlaceholderText("Ask anything");
    expect(textarea).toBeInstanceOf(HTMLTextAreaElement);
    if (!(textarea instanceof HTMLTextAreaElement)) {
      throw new Error("Expected the composer to render a textarea element.");
    }

    await user.click(textarea);
    placeComposerCaret(textarea, 4);

    expect(
      await screen.findByText("Example skill description"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Outside area" }));

    expect(
      screen.queryByText("Example skill description"),
    ).not.toBeInTheDocument();
  });

  it("moves the keyboard highlight and closes the picker on horizontal arrows", async () => {
    const user = userEvent.setup();
    const handleAddMandatorySkill = vi.fn();

    render(
      <ChatComposer
        {...buildComposerProps({
          inputMessage: "/",
          availableMandatorySkills: [
            {
              name: "alpha_skill",
              description: "Alpha",
              path: "/workspace/skills/alpha_skill/SKILL.md",
            },
            {
              name: "beta_skill",
              description: "Beta",
              path: "/workspace/skills/beta_skill/SKILL.md",
            },
          ],
          onAddMandatorySkill: handleAddMandatorySkill,
        })}
      />,
    );

    const textarea = screen.getByPlaceholderText("Ask anything");
    expect(textarea).toBeInstanceOf(HTMLTextAreaElement);
    if (!(textarea instanceof HTMLTextAreaElement)) {
      throw new Error("Expected the composer to render a textarea element.");
    }

    await user.click(textarea);
    placeComposerCaret(textarea, 1);

    const alphaSkill = await screen.findByText("alpha_skill");
    const betaSkill = await screen.findByText("beta_skill");
    expect(alphaSkill.closest("[cmdk-item]")).toHaveAttribute(
      "data-selected",
      "true",
    );

    fireEvent.keyDown(textarea, { key: "ArrowDown" });

    expect(betaSkill.closest("[cmdk-item]")).toHaveAttribute(
      "data-selected",
      "true",
    );
    expect(alphaSkill.closest("[cmdk-item]")).not.toHaveAttribute(
      "data-selected",
      "true",
    );

    fireEvent.keyDown(textarea, { key: "ArrowRight" });

    expect(screen.queryByText("alpha_skill")).not.toBeInTheDocument();
    expect(screen.queryByText("beta_skill")).not.toBeInTheDocument();
    expect(handleAddMandatorySkill).not.toHaveBeenCalled();
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

  it("keeps a non-running task plan collapsed when reopening a session", async () => {
    vi.useFakeTimers();

    render(
      <ChatComposer
        {...buildComposerProps({
          taskPlan: {
            messageId: "assistant-paused",
            taskId: "task-paused",
            taskStatus: "waiting_input",
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
                status: "running",
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
      screen.getByRole("button", { name: "Expand task plan" }),
    ).toBeInTheDocument();
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
