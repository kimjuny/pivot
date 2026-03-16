import { describe, expect, it } from "vitest";

import type { ChatMessage } from "../types";
import { deriveComposerTaskPlan } from "./chatPlan";

function createAssistantMessage(
  overrides: Partial<ChatMessage> = {},
): ChatMessage {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "",
    timestamp: "2026-03-15T00:00:00.000Z",
    status: "running",
    recursions: [],
    ...overrides,
  };
}

describe("deriveComposerTaskPlan", () => {
  it("promotes the first pending step to running for an active task", () => {
    const taskPlan = deriveComposerTaskPlan([
      createAssistantMessage({
        recursions: [
          {
            uid: "rec-1",
            iteration: 0,
            trace_id: "trace-1",
            events: [
              {
                type: "plan_update",
                task_id: "task-1",
                iteration: 0,
                timestamp: "2026-03-15T00:00:00.000Z",
                data: {
                  plan: [
                    {
                      step_id: "1",
                      general_goal: "Inspect the repository",
                      specific_description: "Review the current files",
                      completion_criteria: "Context is collected",
                      status: "pending",
                    },
                    {
                      step_id: "2",
                      general_goal: "Ship the fix",
                      specific_description: "Patch the bug",
                      completion_criteria: "Change is merged",
                      status: "pending",
                    },
                  ],
                },
              },
            ],
            status: "completed",
            startTime: "2026-03-15T00:00:00.000Z",
            endTime: "2026-03-15T00:00:01.000Z",
          },
        ],
      }),
    ]);

    expect(taskPlan?.steps.map((step) => step.status)).toEqual([
      "running",
      "pending",
    ]);
  });

  it("marks unfinished steps done for a completed task", () => {
    const taskPlan = deriveComposerTaskPlan([
      createAssistantMessage({
        status: "completed",
        recursions: [
          {
            uid: "rec-1",
            iteration: 0,
            trace_id: "trace-1",
            events: [
              {
                type: "plan_update",
                task_id: "task-1",
                iteration: 0,
                timestamp: "2026-03-15T00:00:00.000Z",
                data: {
                  plan: [
                    {
                      step_id: "1",
                      general_goal: "Inspect the repository",
                      specific_description: "Review the current files",
                      completion_criteria: "Context is collected",
                      status: "done",
                    },
                    {
                      step_id: "2",
                      general_goal: "Ship the fix",
                      specific_description: "Patch the bug",
                      completion_criteria: "Change is merged",
                      status: "pending",
                    },
                  ],
                },
              },
            ],
            status: "completed",
            startTime: "2026-03-15T00:00:00.000Z",
            endTime: "2026-03-15T00:00:01.000Z",
          },
        ],
      }),
    ]);

    expect(taskPlan?.steps.map((step) => step.status)).toEqual(["done", "done"]);
  });

  it("prefers the latest summary current_plan during live execution", () => {
    const taskPlan = deriveComposerTaskPlan([
      createAssistantMessage({
        recursions: [
          {
            uid: "rec-1",
            iteration: 0,
            trace_id: "trace-1",
            events: [
              {
                type: "plan_update",
                task_id: "task-1",
                iteration: 0,
                timestamp: "2026-03-15T00:00:00.000Z",
                data: {
                  plan: [
                    {
                      step_id: "1",
                      general_goal: "Inspect the repository",
                      specific_description: "Review the current files",
                      completion_criteria: "Context is collected",
                      status: "pending",
                    },
                  ],
                },
              },
            ],
            status: "completed",
            startTime: "2026-03-15T00:00:00.000Z",
            endTime: "2026-03-15T00:00:01.000Z",
          },
          {
            uid: "rec-2",
            iteration: 1,
            trace_id: "trace-2",
            events: [
              {
                type: "summary",
                task_id: "task-1",
                iteration: 1,
                timestamp: "2026-03-15T00:00:02.000Z",
                data: {
                  current_plan: [
                    {
                      step_id: "1",
                      general_goal: "Inspect the repository",
                      specific_description: "Review the current files",
                      completion_criteria: "Context is collected",
                      status: "done",
                    },
                    {
                      step_id: "2",
                      general_goal: "Ship the fix",
                      specific_description: "Patch the bug",
                      completion_criteria: "Change is merged",
                      status: "running",
                    },
                  ],
                },
              },
            ],
            status: "completed",
            startTime: "2026-03-15T00:00:02.000Z",
            endTime: "2026-03-15T00:00:03.000Z",
          },
        ],
      }),
    ]);

    expect(taskPlan?.steps.map((step) => step.status)).toEqual([
      "done",
      "running",
    ]);
  });

  it("uses the persisted current plan when history is reopened", () => {
    const taskPlan = deriveComposerTaskPlan([
      createAssistantMessage({
        status: "completed",
        currentPlan: [
          {
            step_id: "1",
            general_goal: "Inspect the repository",
            specific_description: "Review the current files",
            completion_criteria: "Context is collected",
            status: "done",
          },
          {
            step_id: "2",
            general_goal: "Ship the fix",
            specific_description: "Patch the bug",
            completion_criteria: "Change is merged",
            status: "running",
          },
        ],
        recursions: [],
      }),
    ]);

    expect(taskPlan?.steps.map((step) => step.status)).toEqual(["done", "done"]);
  });

  it("prefers a newer live plan event over persisted history after reconnect", () => {
    const taskPlan = deriveComposerTaskPlan([
      createAssistantMessage({
        currentPlan: [
          {
            step_id: "1",
            general_goal: "Inspect the repository",
            specific_description: "Review the current files",
            completion_criteria: "Context is collected",
            status: "pending",
          },
          {
            step_id: "2",
            general_goal: "Ship the fix",
            specific_description: "Patch the bug",
            completion_criteria: "Change is merged",
            status: "pending",
          },
        ],
        recursions: [
          {
            uid: "rec-2",
            iteration: 1,
            trace_id: "trace-2",
            events: [
              {
                type: "summary",
                task_id: "task-1",
                iteration: 1,
                timestamp: "2026-03-15T00:00:02.000Z",
                data: {
                  current_plan: [
                    {
                      step_id: "1",
                      general_goal: "Inspect the repository",
                      specific_description: "Review the current files",
                      completion_criteria: "Context is collected",
                      status: "done",
                    },
                    {
                      step_id: "2",
                      general_goal: "Ship the fix",
                      specific_description: "Patch the bug",
                      completion_criteria: "Change is merged",
                      status: "running",
                    },
                  ],
                },
              },
            ],
            status: "running",
            startTime: "2026-03-15T00:00:02.000Z",
          },
        ],
      }),
    ]);

    expect(taskPlan?.steps.map((step) => step.status)).toEqual([
      "done",
      "running",
    ]);
  });

  it("does not keep showing an older plan when the latest assistant message has none", () => {
    const taskPlan = deriveComposerTaskPlan([
      createAssistantMessage({
        id: "assistant-old",
        recursions: [
          {
            uid: "rec-old",
            iteration: 0,
            trace_id: "trace-old",
            events: [
              {
                type: "plan_update",
                task_id: "task-old",
                iteration: 0,
                timestamp: "2026-03-15T00:00:00.000Z",
                data: {
                  plan: [
                    {
                      step_id: "1",
                      general_goal: "Old plan",
                      specific_description: "",
                      completion_criteria: "",
                      status: "pending",
                    },
                  ],
                },
              },
            ],
            status: "completed",
            startTime: "2026-03-15T00:00:00.000Z",
            endTime: "2026-03-15T00:00:01.000Z",
          },
        ],
      }),
      createAssistantMessage({
        id: "assistant-latest",
        recursions: [],
      }),
    ]);

    expect(taskPlan).toBeNull();
  });
});
