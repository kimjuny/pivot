import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/utils/api", () => ({
  API_BASE_URL: "http://localhost:8003/api",
  cancelReactTask: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  getFullSessionHistory: vi.fn(),
  getLLMById: vi.fn(),
  getReactContextUsage: vi.fn(),
  listSessions: vi.fn(),
  startReactTask: vi.fn(),
}));

vi.mock("@/contexts/auth-core", () => ({
  AUTH_EXPIRED_EVENT: "auth-expired",
  getAuthToken: () => "token-123",
  getStoredUser: () => ({ username: "alice" }),
  isTokenValid: () => true,
}));

import {
  createSession,
  getFullSessionHistory,
  getLLMById,
  getReactContextUsage,
  listSessions,
  startReactTask,
} from "@/utils/api";

import ChatContainer from "./ChatContainer";

/**
 * Build the smallest valid context-usage payload needed by the composer ring.
 */
function buildContextUsage(sessionId: string | null = null) {
  return {
    task_id: null,
    session_id: sessionId,
    estimation_mode: "next_turn_preview",
    message_count: 0,
    session_message_count: 0,
    used_tokens: 0,
    remaining_tokens: 1000,
    max_context_tokens: 1000,
    used_percent: 0,
    remaining_percent: 100,
    system_tokens: 0,
    conversation_tokens: 0,
    session_tokens: 0,
    preview_tokens: 0,
    bootstrap_tokens: 0,
    draft_tokens: 0,
    includes_task_bootstrap: false,
  };
}

describe("ChatContainer session rollover", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    vi.mocked(getLLMById).mockResolvedValue({
      image_input: false,
    } as Awaited<ReturnType<typeof getLLMById>>);
    vi.mocked(getReactContextUsage).mockResolvedValue(buildContextUsage());
    vi.mocked(getFullSessionHistory).mockResolvedValue({
      session_id: "session-1",
      last_event_id: 0,
      resume_from_event_id: 0,
      tasks: [],
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps the chat surface in draft mode when the latest session is expired", async () => {
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: "expired-session",
          agent_id: 7,
          status: "active",
          subject: "Old chat",
          created_at: "2026-03-16T00:00:00.000Z",
          updated_at: "2026-03-16T00:00:00.000Z",
          message_count: 2,
        },
      ],
      total: 1,
    });
    vi.mocked(createSession).mockResolvedValue({
      id: 1,
      session_id: "unexpected-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      subject: null,
      object: null,
      created_at: "2026-03-16T01:00:00.000Z",
      updated_at: "2026-03-16T01:00:00.000Z",
    });

    render(
      <ChatContainer
        agentId={7}
        agentName="Pivot Agent"
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await waitFor(() => {
      expect(listSessions).toHaveBeenCalledWith(7);
    });

    expect(createSession).not.toHaveBeenCalled();
    expect(getFullSessionHistory).not.toHaveBeenCalled();
    expect(screen.getByText("Old chat")).toBeInTheDocument();
    expect(screen.getByText("Chat with Pivot Agent")).toBeInTheDocument();
  });

  it("continues on an explicitly selected session instead of creating a fresh one", async () => {
    const selectedSessionId = "expired-session";
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: selectedSessionId,
          agent_id: 7,
          status: "active",
          subject: "Focused thread",
          created_at: "2026-03-16T00:00:00.000Z",
          updated_at: "2026-03-16T00:00:00.000Z",
          message_count: 4,
        },
      ],
      total: 1,
    });
    vi.mocked(createSession).mockResolvedValue({
      id: 1,
      session_id: "fresh-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      subject: null,
      object: null,
      created_at: "2026-03-16T01:00:00.000Z",
      updated_at: "2026-03-16T01:00:00.000Z",
    });
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-1",
      session_id: selectedSessionId,
      status: "pending",
      cursor_before_start: 0,
    });
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.close();
          },
        }),
        {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        },
      ),
    );

    const user = userEvent.setup();
    render(
      <ChatContainer
        agentId={7}
        agentName="Pivot Agent"
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await waitFor(() => {
      expect(listSessions).toHaveBeenCalledWith(7);
    });

    await user.click(screen.getByText("Focused thread"));

    await waitFor(() => {
      expect(getFullSessionHistory).toHaveBeenCalledWith(selectedSessionId);
    });

    await user.type(screen.getByPlaceholderText("Ask anything"), "Keep going");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalled();
    });

    expect(createSession).not.toHaveBeenCalled();
    expect(startReactTask).toHaveBeenCalledWith({
      agent_id: 7,
      message: "Keep going",
      session_id: selectedSessionId,
      task_id: null,
      file_ids: [],
    });
  });

  it("does not create a ghost iteration when replay reconnects into an already running recursion", async () => {
    const sessionId = "live-session";
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: sessionId,
          agent_id: 7,
          status: "active",
          subject: "Live thread",
          created_at: "2026-03-16T13:20:00.000Z",
          updated_at: "2026-03-16T13:24:50.000Z",
          message_count: 2,
        },
      ],
      total: 1,
    });
    vi.mocked(getFullSessionHistory).mockResolvedValue({
      session_id: sessionId,
      last_event_id: 25,
      resume_from_event_id: 20,
      tasks: [
        {
          task_id: "task-live",
          user_message: "Help me draft a React landing page",
          agent_answer: null,
          status: "running",
          total_tokens: 41205,
          current_plan: [],
          recursions: [
            {
              iteration: 1,
              trace_id: "trace-live-1",
              observe: "Reading the requirements",
              thinking: null,
              thought: null,
              abstract: "Draft the landing page plan",
              summary: "Planning the sections",
              action_type: null,
              action_output: null,
              tool_call_results: null,
              status: "running",
              error_log: null,
              prompt_tokens: 1000,
              completion_tokens: 200,
              total_tokens: 1200,
              cached_input_tokens: 0,
              created_at: "2026-03-16T13:24:45.000Z",
              updated_at: "2026-03-16T13:24:48.000Z",
            },
          ],
          created_at: "2026-03-16T13:24:40.000Z",
          updated_at: "2026-03-16T13:24:48.000Z",
        },
      ],
    });

    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            const events = [
              {
                event_id: 21,
                type: "recursion_start",
                task_id: "task-live",
                trace_id: "trace-live-1",
                iteration: 1,
                timestamp: "2026-03-16T13:24:45.000Z",
              },
              {
                event_id: 22,
                type: "recursion_start",
                task_id: "task-live",
                trace_id: "trace-live-2",
                iteration: 2,
                timestamp: "2026-03-16T13:24:50.000Z",
              },
            ];

            events.forEach((event) => {
              controller.enqueue(
                encoder.encode(`data: ${JSON.stringify(event)}\n\n`),
              );
            });
            controller.close();
          },
        }),
        {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        },
      ),
    );

    render(
      <ChatContainer
        agentId={7}
        agentName="Pivot Agent"
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await waitFor(() => {
      expect(getFullSessionHistory).toHaveBeenCalledWith(sessionId);
    });

    await waitFor(() => {
      expect(fetch).toHaveBeenCalled();
    });

    expect(screen.queryByText("Iteration 2")).not.toBeInTheDocument();
    expect(screen.getByText("Draft the landing page plan")).toBeInTheDocument();
  });
});
