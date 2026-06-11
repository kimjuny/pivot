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

const STEP_INSPECT = { step_id: "1", subject: "Inspect the repository", status: "pending" as const };
const STEP_FIX = { step_id: "2", subject: "Ship the fix", status: "pending" as const };

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
                  plan: [STEP_INSPECT, STEP_FIX],
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
                    { ...STEP_INSPECT, status: "done" },
                    STEP_FIX,
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

  it("prefers the latest message current_plan during live execution", () => {
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
                  plan: [STEP_INSPECT],
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
                type: "plan_update",
                task_id: "task-1",
                iteration: 1,
                timestamp: "2026-03-15T00:00:02.000Z",
                data: {
                  plan: [
                    { ...STEP_INSPECT, status: "done" },
                    { ...STEP_FIX, status: "running" },
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
        currentSteps: [
          { ...STEP_INSPECT, status: "done" },
          { ...STEP_FIX, status: "running" },
        ],
        recursions: [],
      }),
    ]);

    expect(taskPlan?.steps.map((step) => step.status)).toEqual(["done", "done"]);
  });

  it("prefers a newer live plan event over persisted history after reconnect", () => {
    const taskPlan = deriveComposerTaskPlan([
      createAssistantMessage({
        currentSteps: [STEP_INSPECT, STEP_FIX],
        recursions: [
          {
            uid: "rec-2",
            iteration: 1,
            trace_id: "trace-2",
            events: [
              {
                type: "plan_update",
                task_id: "task-1",
                iteration: 1,
                timestamp: "2026-03-15T00:00:02.000Z",
                data: {
                  plan: [
                    { ...STEP_INSPECT, status: "done" },
                    { ...STEP_FIX, status: "running" },
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
                  plan: [{ step_id: "1", title: "Old plan", status: "pending" }],
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
