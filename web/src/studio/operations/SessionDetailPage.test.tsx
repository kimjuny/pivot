import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("@/studio/operations/api", () => ({
  getOperationsSessionDetail: vi.fn(),
}));

vi.mock("@/utils/api", () => ({
  getExtensionHookExecutions: vi.fn(),
  replayExtensionHookExecution: vi.fn(),
}));

vi.mock("@/pages/chat/utils/chatData", () => ({
  buildMessagesFromHistory: vi.fn(() => []),
}));

vi.mock("@/pages/chat/components/ConversationView", () => ({
  ConversationView: () => <div>Conversation View</div>,
}));

import { getOperationsSessionDetail } from "@/studio/operations/api";
import { getExtensionHookExecutions } from "@/utils/api";

import SessionDetailPage from "./SessionDetailPage";

describe("SessionDetailPage", () => {
  let scrollIntoViewMock: Element["scrollIntoView"];

  beforeEach(() => {
    scrollIntoViewMock = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoViewMock;
  });

  it("focuses hook executions from diagnostics shortcuts", async () => {
    vi.mocked(getOperationsSessionDetail).mockResolvedValue({
      session: {
        session_id: "session-1",
        agent_id: 7,
        agent_name: "Support Agent",
        release_version: 3,
        type: "studio_test",
        user: "alice",
        status: "failed",
        title: "Diagnose billing issue",
        diagnostics: {
          task_count: 1,
          completed_task_count: 0,
          active_task_count: 0,
          waiting_input_task_count: 0,
          failed_task_count: 1,
          cancelled_task_count: 0,
          attention_task_count: 1,
          failed_recursion_count: 1,
          latest_error: {
            task_id: "task-a",
            trace_id: "trace-1",
            message: "Provider failed",
            timestamp: "2026-04-02T00:00:00Z",
          },
        },
        created_at: "2026-04-02T00:00:00Z",
        updated_at: "2026-04-02T00:00:00Z",
      },
      tasks: [
        {
          task_id: "task-a",
          user_message: "Check billing account",
          files: [],
          agent_answer: null,
          status: "failed",
          total_tokens: 22,
          pending_user_action: null,
          current_plan: [],
          recursions: [
            {
              iteration: 3,
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
              error_log: "Provider failed",
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
      ],
    });
    vi.mocked(getExtensionHookExecutions).mockResolvedValue([
      {
        id: 11,
        session_id: "session-1",
        task_id: "task-a",
        trace_id: "trace-1",
        iteration: 3,
        agent_id: 7,
        release_id: null,
        extension_package_id: "@acme/hooks",
        extension_version: "1.0.0",
        hook_event: "iteration.error",
        hook_callable: "observe_error",
        status: "succeeded",
        hook_context: {
          task_id: "task-a",
        },
        effects: [{ type: "emit_event" }],
        error: null,
        started_at: "2026-04-02T00:00:00Z",
        finished_at: "2026-04-02T00:00:01Z",
        duration_ms: 8,
      },
    ]);

    render(
      <MemoryRouter initialEntries={["/studio/operations/sessions/session-1"]}>
        <Routes>
          <Route
            path="/studio/operations/sessions/:sessionId"
            element={<SessionDetailPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(getOperationsSessionDetail).toHaveBeenCalledWith("session-1");
      expect(getExtensionHookExecutions).toHaveBeenCalledWith({
        sessionId: "session-1",
        taskId: undefined,
        traceId: undefined,
        iteration: undefined,
        limit: 25,
      });
    });

    fireEvent.click(screen.getAllByRole("button", { name: "Inspect Hooks" })[0]);

    await waitFor(() => {
      expect(getExtensionHookExecutions).toHaveBeenLastCalledWith({
        sessionId: "session-1",
        taskId: "task-a",
        traceId: "trace-1",
        iteration: 3,
        limit: 25,
      });
      expect(scrollIntoViewMock).toHaveBeenCalled();
    });
  });
});
