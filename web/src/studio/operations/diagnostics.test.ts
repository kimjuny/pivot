import { describe, expect, it } from "vitest";

import {
  buildOperationsDetailDiagnostics,
  summarizeOperationsTasks,
} from "@/studio/operations/diagnostics";
import type {
  OperationsSessionDiagnostics,
  OperationsTaskMessage,
} from "@/studio/operations/api";

function buildTask(overrides: Partial<OperationsTaskMessage>): OperationsTaskMessage {
  return {
    task_id: "task-1",
    user_message: "Investigate the failure",
    files: [],
    agent_answer: null,
    status: "running",
    total_tokens: 120,
    pending_user_action: null,
    current_plan: [],
    recursions: [],
    created_at: "2026-03-30T10:00:00Z",
    updated_at: "2026-03-30T10:00:00Z",
    ...overrides,
  };
}

describe("summarizeOperationsTasks", () => {
  it("surfaces latest errors and issue tasks from task history", () => {
    const summary = summarizeOperationsTasks([
      buildTask({
        task_id: "task-waiting",
        status: "waiting_input",
        updated_at: "2026-03-30T10:05:00Z",
      }),
      buildTask({
        task_id: "task-failed",
        status: "failed",
        total_tokens: 240,
        updated_at: "2026-03-30T10:10:00Z",
        recursions: [
          {
            iteration: 0,
            trace_id: "trace-older",
            observe: null,
            thinking: null,
            reason: null,
            summary: null,
            action_type: null,
            action_output: null,
            tool_call_results: null,
            status: "error",
            error_log: "Initial sandbox failure",
            prompt_tokens: 10,
            completion_tokens: 5,
            total_tokens: 15,
            cached_input_tokens: 0,
            created_at: "2026-03-30T10:01:00Z",
            updated_at: "2026-03-30T10:06:00Z",
          },
          {
            iteration: 1,
            trace_id: "trace-newer",
            observe: null,
            thinking: null,
            reason: null,
            summary: null,
            action_type: null,
            action_output: null,
            tool_call_results: null,
            status: "error",
            error_log: "Latest sandbox timeout",
            prompt_tokens: 12,
            completion_tokens: 6,
            total_tokens: 18,
            cached_input_tokens: 0,
            created_at: "2026-03-30T10:07:00Z",
            updated_at: "2026-03-30T10:11:00Z",
          },
        ],
      }),
    ]);

    expect(summary.taskCount).toBe(2);
    expect(summary.waitingInputTaskCount).toBe(1);
    expect(summary.failedTaskCount).toBe(1);
    expect(summary.failedRecursionCount).toBe(2);
    expect(summary.totalRecursionCount).toBe(2);
    expect(summary.totalTokens).toBe(360);
    expect(summary.attentionTaskCount).toBe(2);
    expect(summary.latestError?.message).toBe("Latest sandbox timeout");
    expect(summary.issueTasks[0]?.taskId).toBe("task-failed");
    expect(summary.issueTasks[0]?.latestErrorIteration).toBe(1);
    expect(summary.issueTasks[1]?.taskId).toBe("task-waiting");
  });
});

describe("buildOperationsDetailDiagnostics", () => {
  it("preserves backend counts while adding task-level issue drill-down", () => {
    const diagnostics: OperationsSessionDiagnostics = {
      task_count: 3,
      completed_task_count: 1,
      active_task_count: 0,
      waiting_input_task_count: 1,
      failed_task_count: 1,
      cancelled_task_count: 1,
      attention_task_count: 2,
      failed_recursion_count: 1,
      latest_error: {
        task_id: "task-failed",
        trace_id: "trace-api",
        message: "API-level latest error",
        timestamp: "2026-03-30T10:12:00Z",
      },
    };

    const summary = buildOperationsDetailDiagnostics(diagnostics, [
      buildTask({
        task_id: "task-failed",
        status: "failed",
        updated_at: "2026-03-30T10:11:00Z",
      }),
      buildTask({
        task_id: "task-waiting",
        status: "waiting_input",
        updated_at: "2026-03-30T10:09:00Z",
      }),
    ]);

    expect(summary.taskCount).toBe(3);
    expect(summary.completedTaskCount).toBe(1);
    expect(summary.cancelledTaskCount).toBe(1);
    expect(summary.attentionTaskCount).toBe(2);
    expect(summary.latestError?.message).toBe("API-level latest error");
    expect(summary.issueTasks).toHaveLength(2);
  });
});
