import { describe, expect, it } from "vitest";

import { extractSkillChangeApprovalRequest } from "./chatSelectors";

describe("chatSelectors", () => {
  it("reads skill approval requests only from task-owned pending actions", () => {
    expect(
      extractSkillChangeApprovalRequest({
        id: "assistant-approval",
        role: "assistant",
        content: "Approve this skill?",
        timestamp: "2026-03-24T00:00:00.000Z",
        status: "waiting_input",
        pendingUserAction: {
          kind: "skill_change_approval",
          approvalRequest: {
            submission_id: 42,
            skill_name: "planning-kit",
            change_type: "create",
            question: "Approve this skill?",
            message: "Adds a reusable planning workflow.",
          },
        },
        recursions: [],
      }),
    ).toEqual({
      submission_id: 42,
      skill_name: "planning-kit",
      change_type: "create",
      question: "Approve this skill?",
      message: "Adds a reusable planning workflow.",
      file_count: undefined,
      total_bytes: undefined,
    });
  });

  it("does not fall back to recursion clarify payloads for approvals", () => {
    expect(
      extractSkillChangeApprovalRequest({
        id: "assistant-legacy",
        role: "assistant",
        content: "Approve this skill?",
        timestamp: "2026-03-24T00:00:00.000Z",
        status: "waiting_input",
        recursions: [
          {
            uid: "recursion-1",
            iteration: 0,
            trace_id: "trace-1",
            status: "completed",
            startTime: "2026-03-24T00:00:00.000Z",
            endTime: "2026-03-24T00:00:01.000Z",
            events: [
              {
                type: "clarify",
                task_id: "task-1",
                trace_id: "trace-1",
                iteration: 0,
                timestamp: "2026-03-24T00:00:01.000Z",
                data: {
                  approval_request: {
                    submission_id: 7,
                    skill_name: "legacy-skill",
                    change_type: "create",
                    question: "Legacy fallback",
                  },
                },
              },
            ],
          },
        ],
      }),
    ).toBeUndefined();
  });
});
