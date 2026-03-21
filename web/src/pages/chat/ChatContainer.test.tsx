import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/utils/api", () => ({
  API_BASE_URL: "http://localhost:8003/api",
  cancelReactTask: vi.fn(),
  createSession: vi.fn(),
  deleteSession: vi.fn(),
  getAgentWebSearchBindings: vi.fn(),
  getFullSessionHistory: vi.fn(),
  getLLMById: vi.fn(),
  getReactContextUsage: vi.fn(),
  getReactSessionRuntimeDebug: vi.fn(),
  listSessions: vi.fn(),
  startReactTask: vi.fn(),
  updateSession: vi.fn(),
}));

vi.mock("@/contexts/auth-core", () => ({
  AUTH_EXPIRED_EVENT: "auth-expired",
  getAuthToken: () => "token-123",
  getStoredUser: () => ({ username: "alice" }),
  isTokenValid: () => true,
}));

import {
  cancelReactTask,
  createSession,
  getAgentWebSearchBindings,
  getFullSessionHistory,
  getLLMById,
  getReactContextUsage,
  getReactSessionRuntimeDebug,
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

/**
 * Radix Select expects pointer-capture helpers that happy-dom does not ship.
 */
function applyPointerCapturePolyfill() {
  if (!("hasPointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "hasPointerCapture", {
      value: () => false,
      configurable: true,
    });
  }
  if (!("setPointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "setPointerCapture", {
      value: () => {},
      configurable: true,
    });
  }
  if (!("releasePointerCapture" in Element.prototype)) {
    Object.defineProperty(Element.prototype, "releasePointerCapture", {
      value: () => {},
      configurable: true,
    });
  }
}

describe("ChatContainer session rollover", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("fetch", vi.fn());
    applyPointerCapturePolyfill();
    vi.mocked(getLLMById).mockResolvedValue({
      image_input: false,
      thinking_policy: "auto",
      thinking_effort: null,
    } as Awaited<ReturnType<typeof getLLMById>>);
    vi.mocked(getAgentWebSearchBindings).mockResolvedValue([]);
    vi.mocked(getReactContextUsage).mockResolvedValue(buildContextUsage());
    vi.mocked(getReactSessionRuntimeDebug).mockResolvedValue({
      session_id: "session-1",
      runtime_message_count: 0,
      runtime_message_roles: [],
      has_compact_result: false,
      compact_result: null,
      compact_result_raw: null,
      updated_at: "2026-03-19T00:00:00.000Z",
    });
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
          title: "Old chat",
          is_pinned: false,
          created_at: "2026-03-16T00:00:00.000Z",
          updated_at: "2026-03-16T00:00:00.000Z",
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
      title: null,
      is_pinned: false,
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
          title: "Focused thread",
          is_pinned: false,
          created_at: "2026-03-16T00:00:00.000Z",
          updated_at: "2026-03-16T00:00:00.000Z",
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
      title: null,
      is_pinned: false,
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
      web_search_provider: null,
      thinking_mode: null,
    });
  });

  it("includes the selected web search provider in the launch payload", async () => {
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [],
      total: 0,
    });
    vi.mocked(createSession).mockResolvedValue({
      id: 2,
      session_id: "fresh-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: "2026-03-20T00:00:00.000Z",
      updated_at: "2026-03-20T00:00:00.000Z",
    });
    vi.mocked(getAgentWebSearchBindings).mockResolvedValue([
      {
        id: 11,
        agent_id: 7,
        provider_key: "tavily",
        enabled: true,
        auth_config: {},
        runtime_config: {},
        manifest: {
          key: "tavily",
          name: "Tavily",
          description: "Search the web",
          docs_url: "https://example.com/tavily",
          visibility: "builtin",
          status: "active",
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
          supported_parameters: [],
        },
        last_health_status: "ok",
        last_health_message: null,
        last_health_check_at: null,
        created_at: "2026-03-19T00:00:00.000Z",
        updated_at: "2026-03-19T00:00:00.000Z",
      },
      {
        id: 12,
        agent_id: 7,
        provider_key: "baidu",
        enabled: true,
        auth_config: {},
        runtime_config: {},
        manifest: {
          key: "baidu",
          name: "Baidu AI Search",
          description: "Search the web",
          docs_url: "https://example.com/baidu",
          visibility: "builtin",
          status: "active",
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
          supported_parameters: [],
        },
        last_health_status: "ok",
        last_health_message: null,
        last_health_check_at: null,
        created_at: "2026-03-19T00:01:00.000Z",
        updated_at: "2026-03-19T00:01:00.000Z",
      },
    ]);
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-2",
      session_id: "fresh-session",
      status: "pending",
      cursor_before_start: 0,
    });
    vi.mocked(fetch).mockImplementation(
      () =>
        Promise.resolve(
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
      ),
    );

    const user = userEvent.setup();
    render(
      <ChatContainer
        agentId={7}
        agentName="Pivot Agent"
        agentToolIds={null}
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await waitFor(() => {
      expect(getAgentWebSearchBindings).toHaveBeenCalledWith(7);
    });

    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Web search provider" }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("combobox", { name: "Web search provider" }));
    await user.click(screen.getByRole("option", { name: "Baidu AI Search" }));
    await user.type(screen.getByPlaceholderText("Ask anything"), "Search it");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalledWith({
        agent_id: 7,
        message: "Search it",
        session_id: "fresh-session",
        task_id: null,
        file_ids: [],
        web_search_provider: "baidu",
        thinking_mode: null,
      });
    });
  });

  it("defaults to Thinking mode when the primary LLM exposes a non-fast thinking tier", async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], total: 0 });
    vi.mocked(getLLMById).mockResolvedValue({
      image_input: false,
      thinking_policy: "openai-response-reasoning-effort",
      thinking_effort: "high",
    } as Awaited<ReturnType<typeof getLLMById>>);
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-thinking",
      session_id: "fresh-session",
      status: "pending",
      cursor_before_start: 0,
    });
    vi.mocked(createSession).mockResolvedValue({
      id: 3,
      session_id: "fresh-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: "2026-03-20T00:00:00.000Z",
      updated_at: "2026-03-20T00:00:00.000Z",
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
      expect(
        screen.getByRole("combobox", { name: "Thinking mode" }),
      ).toBeInTheDocument();
    });

    await user.type(screen.getByPlaceholderText("Ask anything"), "Think first");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalledWith({
        agent_id: 7,
        message: "Think first",
        session_id: "fresh-session",
        task_id: null,
        file_ids: [],
        web_search_provider: null,
        thinking_mode: "thinking",
      });
    });
  });

  it("lets the user switch the chat payload to Fast mode", async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], total: 0 });
    vi.mocked(getLLMById).mockResolvedValue({
      image_input: false,
      thinking_policy: "openai-response-reasoning-effort",
      thinking_effort: "high",
    } as Awaited<ReturnType<typeof getLLMById>>);
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-fast",
      session_id: "fresh-session",
      status: "pending",
      cursor_before_start: 0,
    });
    vi.mocked(createSession).mockResolvedValue({
      id: 4,
      session_id: "fresh-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: "2026-03-20T00:00:00.000Z",
      updated_at: "2026-03-20T00:00:00.000Z",
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
      expect(
        screen.getByRole("combobox", { name: "Thinking mode" }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("combobox", { name: "Thinking mode" }));
    await user.click(screen.getByRole("option", { name: "Fast" }));
    await user.type(screen.getByPlaceholderText("Ask anything"), "Be quick");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalledWith({
        agent_id: 7,
        message: "Be quick",
        session_id: "fresh-session",
        task_id: null,
        file_ids: [],
        web_search_provider: null,
        thinking_mode: "fast",
      });
    });
  });

  it("shows only Fast when the stored thinking tier is already disabled", async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], total: 0 });
    vi.mocked(getLLMById).mockResolvedValue({
      image_input: false,
      thinking_policy: "qwen-disable-thinking",
      thinking_effort: null,
    } as Awaited<ReturnType<typeof getLLMById>>);

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
      expect(
        screen.getByRole("combobox", { name: "Thinking mode" }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("combobox", { name: "Thinking mode" }));
    expect(screen.getByRole("option", { name: "Fast" })).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Thinking" }),
    ).not.toBeInTheDocument();
  });

  it("hides the provider selector when the agent cannot use web_search", async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], total: 0 });
    vi.mocked(getAgentWebSearchBindings).mockResolvedValue([
      {
        id: 11,
        agent_id: 7,
        provider_key: "tavily",
        enabled: true,
        auth_config: {},
        runtime_config: {},
        manifest: {
          key: "tavily",
          name: "Tavily",
          description: "Search the web",
          docs_url: "https://example.com/tavily",
          visibility: "builtin",
          status: "active",
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
          supported_parameters: [],
        },
        last_health_status: "ok",
        last_health_message: null,
        last_health_check_at: null,
        created_at: "2026-03-19T00:00:00.000Z",
        updated_at: "2026-03-19T00:00:00.000Z",
      },
    ]);

    render(
      <ChatContainer
        agentId={7}
        agentName="Pivot Agent"
        agentToolIds='["run_bash"]'
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await waitFor(() => {
      expect(listSessions).toHaveBeenCalledWith(7);
    });

    expect(
      screen.queryByRole("combobox", { name: "Web search provider" }),
    ).not.toBeInTheDocument();
    expect(getAgentWebSearchBindings).not.toHaveBeenCalled();
  });

  it("does not create a ghost iteration when replay reconnects into an already running recursion", async () => {
    const sessionId = "live-session";
    const updatedAt = new Date().toISOString();
    const createdAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: sessionId,
          agent_id: 7,
          status: "active",
          title: "Live thread",
          is_pinned: false,
          created_at: createdAt,
          updated_at: updatedAt,
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
              reason: null,
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
    expect(screen.getByText("Planning the sections")).toBeInTheDocument();
  });

  it("optimistically shows stopped when the user stops a running task", async () => {
    const sessionId = "stop-session";
    const updatedAt = new Date().toISOString();
    const createdAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();

    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: sessionId,
          agent_id: 7,
          status: "active",
          title: "Stop thread",
          is_pinned: false,
          created_at: createdAt,
          updated_at: updatedAt,
        },
      ],
      total: 1,
    });
    vi.mocked(getFullSessionHistory).mockResolvedValue({
      session_id: sessionId,
      last_event_id: 0,
      resume_from_event_id: 0,
      tasks: [
        {
          task_id: "task-stop",
          user_message: "Please stop",
          agent_answer: null,
          status: "running",
          total_tokens: 0,
          current_plan: [],
          recursions: [
            {
              iteration: 0,
              trace_id: "trace-stop",
              observe: null,
              thinking: "thinking",
              reason: null,
              summary: null,
              action_type: null,
              action_output: null,
              tool_call_results: null,
              status: "running",
              error_log: null,
              prompt_tokens: 0,
              completion_tokens: 0,
              total_tokens: 0,
              cached_input_tokens: 0,
              created_at: createdAt,
              updated_at: updatedAt,
            },
          ],
          created_at: createdAt,
          updated_at: updatedAt,
        },
      ],
    });
    vi.mocked(cancelReactTask).mockResolvedValue({
      task_id: "task-stop",
      status: "cancelled",
      cancel_requested: true,
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
      expect(getFullSessionHistory).toHaveBeenCalledWith(sessionId);
    });

    await user.click(screen.getByTitle("Stop execution"));

    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(cancelReactTask).toHaveBeenCalledWith("task-stop");
    });
  });

  it("updates the sidebar title when a streamed summary carries session_title", async () => {
    const sessionId = "session-title-live";
    const updatedAt = new Date().toISOString();
    const createdAt = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: sessionId,
          agent_id: 7,
          status: "active",
          title: null,
          is_pinned: false,
          created_at: createdAt,
          updated_at: updatedAt,
        },
      ],
      total: 1,
    });
    vi.mocked(getFullSessionHistory).mockResolvedValue({
      session_id: sessionId,
      last_event_id: 0,
      resume_from_event_id: 0,
      tasks: [
        {
          task_id: "task-title",
          user_message: "Help me plan a launch",
          agent_answer: null,
          status: "running",
          total_tokens: 0,
          current_plan: [],
          recursions: [
            {
              iteration: 0,
              trace_id: "trace-title",
              observe: null,
              thinking: null,
              reason: null,
              summary: null,
              action_type: null,
              action_output: null,
              tool_call_results: null,
              status: "running",
              error_log: null,
              prompt_tokens: 0,
              completion_tokens: 0,
              total_tokens: 0,
              cached_input_tokens: 0,
              created_at: createdAt,
              updated_at: updatedAt,
            },
          ],
          created_at: createdAt,
          updated_at: updatedAt,
        },
      ],
    });

    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                `data: ${JSON.stringify({
                  event_id: 1,
                  type: "summary",
                  task_id: "task-title",
                  trace_id: "trace-title",
                  iteration: 0,
                  delta: "I have organized the launch plan.",
                  data: {
                    current_plan: [],
                    session_title: "Launch planning thread",
                  },
                  timestamp: "2026-03-16T13:24:46.000Z",
                })}\n\n`,
              ),
            );
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
      expect(screen.getByText("Launch planning thread")).toBeInTheDocument();
    });
  });
});
