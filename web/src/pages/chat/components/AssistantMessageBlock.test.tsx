import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssistantMessageBlock } from "./AssistantMessageBlock";

describe("AssistantMessageBlock", () => {
  it("renders the loading skill matcher only once while skills are resolving", () => {
    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-1",
          role: "assistant",
          content: "",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "skill_resolving",
          skillSelection: {
            status: "loading",
            count: 0,
            selectedSkills: [],
          },
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

    expect(screen.getAllByText("Matching Skills...")).toHaveLength(1);
  });

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
            "Approve the request to create private skill `planning-kit`?\n\nAdds a reusable planning workflow.",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "waiting_input",
          pendingUserAction: {
            kind: "skill_change_approval",
            approvalRequest: {
              submission_id: 42,
              skill_name: "planning-kit",
              change_type: "create",
              question:
                "Approve the request to create private skill `planning-kit`?",
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
                      "Approve the request to create private skill `planning-kit`?",
                    approval_request: {
                      submission_id: 42,
                      skill_name: "planning-kit",
                      change_type: "create",
                      question:
                        "Approve the request to create private skill `planning-kit`?",
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
      question: "Approve the request to create private skill `planning-kit`?",
      message: "Adds a reusable planning workflow.",
      file_count: undefined,
      total_bytes: undefined,
    });
    expect(onRejectSkillChange).not.toHaveBeenCalled();
  });
});
