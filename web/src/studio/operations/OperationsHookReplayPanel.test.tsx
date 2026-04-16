import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("@/utils/api", () => ({
  getExtensionHookExecutions: vi.fn(),
  replayExtensionHookExecution: vi.fn(),
}));

import {
  getExtensionHookExecutions,
  replayExtensionHookExecution,
} from "@/utils/api";

import { OperationsHookReplayPanel } from "./OperationsHookReplayPanel";

describe("OperationsHookReplayPanel", () => {
  it("filters session hook logs by task, trace, and iteration then replays", async () => {
    vi.mocked(getExtensionHookExecutions).mockResolvedValue([
      {
        id: 11,
        session_id: "session-1",
        task_id: "task-a",
        trace_id: "trace-1",
        iteration: 2,
        agent_id: 7,
        release_id: null,
        extension_package_id: "@acme/hooks",
        extension_version: "1.0.0",
        hook_event: "iteration.after_tool_result",
        hook_callable: "handle_task_event",
        status: "succeeded",
        hook_context: {
          task_id: "task-a",
          event_payload: { tool_results: [{ name: "search_accounts" }] },
        },
        effects: [{ type: "observe" }],
        error: null,
        started_at: "2026-04-02T00:00:00Z",
        finished_at: "2026-04-02T00:00:01Z",
        duration_ms: 12,
      },
    ]);
    vi.mocked(replayExtensionHookExecution).mockResolvedValue({
      execution_id: 11,
      extension_package_id: "@acme/hooks",
      extension_version: "1.0.0",
      hook_event: "iteration.after_tool_result",
      hook_callable: "handle_task_event",
      status: "succeeded",
      effects: [{ type: "observe", data: { replayed: true } }],
      error: null,
      replayed_at: "2026-04-02T00:05:00Z",
    });

    render(
      <OperationsHookReplayPanel
        sessionId="session-1"
        tasks={[
          {
            task_id: "task-a",
            user_message: "Find account health",
            files: [],
            agent_answer: null,
            status: "failed",
            total_tokens: 12,
            pending_user_action: null,
            current_plan: [],
            recursions: [
              {
                iteration: 2,
                trace_id: "trace-1",
                input_message_json: null,
                observe: null,
                thinking: null,
                reason: null,
                summary: null,
                action_type: null,
                action_output: null,
                tool_call_results: null,
                status: "error",
                error_log: null,
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: 0,
                cached_input_tokens: 0,
                created_at: "2026-04-02T00:00:00Z",
                updated_at: "2026-04-02T00:00:00Z",
              },
            ],
            created_at: "2026-04-02T00:00:00Z",
            updated_at: "2026-04-02T00:00:00Z",
          },
        ]}
        focusRequest={null}
      />,
    );

    await waitFor(() => {
      expect(getExtensionHookExecutions).toHaveBeenCalledWith({
        sessionId: "session-1",
        taskId: undefined,
        traceId: undefined,
        iteration: undefined,
        limit: 25,
      });
      expect(screen.getByText("iteration.after_tool_result")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "task-a" }));
    fireEvent.click(screen.getByRole("button", { name: "trace-1" }));
    fireEvent.click(screen.getByRole("button", { name: "Iteration 2" }));

    await waitFor(() => {
      expect(getExtensionHookExecutions).toHaveBeenLastCalledWith({
        sessionId: "session-1",
        taskId: "task-a",
        traceId: "trace-1",
        iteration: 2,
        limit: 25,
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Inspect" }));

    await waitFor(() => {
      expect(screen.getByText("Hook Context")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Replay" }));

    await waitFor(() => {
      expect(replayExtensionHookExecution).toHaveBeenCalledWith(11);
      expect(screen.getByText("Replay Result")).toBeInTheDocument();
    });
  });
});
