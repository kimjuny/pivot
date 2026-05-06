import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssistantMessageBlock } from "./AssistantMessageBlock";

describe("AssistantMessageBlock", () => {
  it("shows stopped instead of error for a stopped task", () => {
    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-2",
          role: "assistant",
          content: "",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "stopped",
          recursions: [],
        }}
        expandedRecursions={{}}
        isStreaming={false}
        onToggleRecursion={vi.fn()}
        onReplyTask={vi.fn()}
        onApproveSkillChange={vi.fn()}
        onRejectSkillChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Stopped")).toBeInTheDocument();
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
  });

  it("renders terminal errors outside the final answer block", () => {
    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-error",
          role: "assistant",
          content: "",
          errorMessage: "Sandbox timed out while running tests.",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "error",
          recursions: [],
        }}
        expandedRecursions={{}}
        isStreaming={false}
        onToggleRecursion={vi.fn()}
        onReplyTask={vi.fn()}
        onApproveSkillChange={vi.fn()}
        onRejectSkillChange={vi.fn()}
      />,
    );

    expect(screen.queryByText("FINAL ANSWER")).not.toBeInTheDocument();
    expect(screen.getByText("ERROR")).toBeInTheDocument();
    expect(
      screen.getByText("Sandbox timed out while running tests."),
    ).toBeInTheDocument();
  });

  it("renders final answers with markdown headings and emphasis", () => {
    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-markdown",
          role: "assistant",
          content: "## Summary\n\n**Important** details live here.",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "completed",
          recursions: [],
        }}
        expandedRecursions={{}}
        isStreaming={false}
        onToggleRecursion={vi.fn()}
        onReplyTask={vi.fn()}
        onApproveSkillChange={vi.fn()}
        onRejectSkillChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Summary", level: 2 }),
    ).toBeInTheDocument();
    expect(screen.getByText("Important")).toBeInTheDocument();
    expect(screen.getByText("details live here.")).toBeInTheDocument();
  });

  it("renders inline approval actions for skill change clarify messages", async () => {
    const user = userEvent.setup();
    const onApproveSkillChange = vi.fn();
    const onRejectSkillChange = vi.fn();

    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-approval",
          role: "assistant",
          task_id: "task-approval",
          content:
            "Approve the request to create Skill `planning-kit`?\n\nAdds a reusable planning workflow.",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "waiting_input",
          pendingUserAction: {
            kind: "skill_change_approval",
            approvalRequest: {
              submission_id: 42,
              skill_name: "planning-kit",
              change_type: "create",
              question:
                "Approve the request to create Skill `planning-kit`?",
              message: "Adds a reusable planning workflow.",
            },
          },
          recursions: [
            {
              uid: "assistant-approval-recursion-0",
              iteration: 0,
              trace_id: "trace-approval",
              events: [
                {
                  type: "clarify",
                  task_id: "task-approval",
                  trace_id: "trace-approval",
                  iteration: 0,
                  timestamp: "2026-03-17T00:00:00.000Z",
                  data: {
                    question:
                      "Approve the request to create Skill `planning-kit`?",
                    approval_request: {
                      submission_id: 42,
                      skill_name: "planning-kit",
                      change_type: "create",
                      question:
                        "Approve the request to create Skill `planning-kit`?",
                    },
                  },
                },
              ],
              status: "completed",
              startTime: "2026-03-17T00:00:00.000Z",
              endTime: "2026-03-17T00:00:00.000Z",
            },
          ],
        }}
        expandedRecursions={{}}
        isStreaming={false}
        onToggleRecursion={vi.fn()}
        onReplyTask={vi.fn()}
        onApproveSkillChange={onApproveSkillChange}
        onRejectSkillChange={onRejectSkillChange}
      />,
    );

    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reply" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(onApproveSkillChange).toHaveBeenCalledWith("task-approval", {
      submission_id: 42,
      skill_name: "planning-kit",
      change_type: "create",
      question: "Approve the request to create Skill `planning-kit`?",
      message: "Adds a reusable planning workflow.",
      file_count: undefined,
      total_bytes: undefined,
    });
    expect(onRejectSkillChange).not.toHaveBeenCalled();
  });

  it("labels completed clarify history as a question without offering another reply", () => {
    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-clarify-history",
          role: "assistant",
          task_id: "task-clarify-history",
          content: "Which export format do you prefer?",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "completed",
          recursions: [
            {
              uid: "assistant-clarify-history-recursion-0",
              iteration: 0,
              trace_id: "trace-clarify-history",
              action: "CLARIFY",
              events: [
                {
                  type: "clarify",
                  task_id: "task-clarify-history",
                  trace_id: "trace-clarify-history",
                  iteration: 0,
                  timestamp: "2026-03-17T00:00:00.000Z",
                  data: {
                    question: "Which export format do you prefer?",
                  },
                },
              ],
              status: "completed",
              startTime: "2026-03-17T00:00:00.000Z",
              endTime: "2026-03-17T00:00:00.000Z",
            },
          ],
        }}
        expandedRecursions={{}}
        isStreaming={false}
        onToggleRecursion={vi.fn()}
        onReplyTask={vi.fn()}
        onApproveSkillChange={vi.fn()}
        onRejectSkillChange={vi.fn()}
      />,
    );

    expect(screen.getByText("QUESTION")).toBeInTheDocument();
    expect(screen.queryByText("FINAL ANSWER")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reply" })).not.toBeInTheDocument();
  });
});
