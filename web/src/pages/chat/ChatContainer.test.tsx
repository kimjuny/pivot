import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/utils/api", () => ({
  API_BASE_URL: "http://localhost:8003/api",
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  getFullSessionHistory: vi.fn(),
  getLLMById: vi.fn(),
  getReactContextUsage: vi.fn(),
  listSessions: vi.fn(),
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
      expect(fetch).toHaveBeenCalled();
    });

    expect(createSession).not.toHaveBeenCalled();
    const requestInit = vi.mocked(fetch).mock.calls[0]?.[1];
    expect(requestInit).toBeDefined();
    if (!requestInit || typeof requestInit.body !== "string") {
      throw new Error("Missing chat stream request body");
    }

    expect(JSON.parse(requestInit.body)).toMatchObject({
      agent_id: 7,
      message: "Keep going",
      session_id: selectedSessionId,
    });
  });
});
