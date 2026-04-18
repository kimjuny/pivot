import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HTMLAttributes, PropsWithChildren } from "react";

vi.mock("react-resizable-panels", async () => {
  const React = await vi.importActual<typeof import("react")>("react");

  return {
    PanelGroup: ({
      children,
      className,
      direction,
    }: PropsWithChildren<{
      className?: string;
      direction: "horizontal" | "vertical";
    }>) => (
      <div data-panel-group-direction={direction} className={className}>
        {children}
      </div>
    ),
    Panel: ({
      children,
      className,
    }: PropsWithChildren<{ className?: string }>) => (
      <div className={className}>{children}</div>
    ),
    PanelResizeHandle: ({
      children,
      className,
      ...props
    }: PropsWithChildren<HTMLAttributes<HTMLDivElement>>) => (
      <div className={className} {...props}>
        {children}
      </div>
    ),
  };
});

vi.mock("@/utils/api", async () => {
  const actual = await vi.importActual<typeof import("@/utils/api")>(
    "@/utils/api",
  );

  return {
    ...actual,
    cancelReactTask: vi.fn(),
    createProject: vi.fn(),
    createDevSurfaceSession: vi.fn(),
    createInstalledSurfaceSession: vi.fn(),
    createSession: vi.fn(),
    deleteChatFile: vi.fn(),
    deleteProject: vi.fn(),
    deleteSession: vi.fn(),
    getAgentWebSearchBindings: vi.fn(),
    getAgentExtensionPackages: vi.fn(),
    getFullSessionHistory: vi.fn(),
    getLLMById: vi.fn(),
    getReactContextUsage: vi.fn(),
    getReactRuntimeSkills: vi.fn(),
    getReactSessionRuntimeDebug: vi.fn(),
    httpClient: vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      fetch(input, init),
    ),
    listProjects: vi.fn(),
    listSessions: vi.fn(),
    startReactTask: vi.fn(),
    submitReactUserAction: vi.fn(),
    uploadChatFile: vi.fn(),
    updateProject: vi.fn(),
    updateSession: vi.fn(),
  };
});

vi.mock("@/contexts/auth-core", () => ({
  AUTH_EXPIRED_EVENT: "auth-expired",
  getAuthToken: () => "token-123",
  getStoredUser: () => ({ username: "alice" }),
  isTokenValid: () => true,
}));

import {
  cancelReactTask,
  createProject,
  createDevSurfaceSession,
  createInstalledSurfaceSession,
  createSession,
  getAgentExtensionPackages,
  getAgentWebSearchBindings,
  getFullSessionHistory,
  getLLMById,
  getReactContextUsage,
  getReactRuntimeSkills,
  getReactSessionRuntimeDebug,
  httpClient,
  listProjects,
  listSessions,
  startReactTask,
  submitReactUserAction,
  uploadChatFile,
  updateProject,
} from "@/utils/api";

import ChatContainer from "./ChatContainer";
import ReactChatInterface from "@/components/ReactChatInterface";

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
  const expectedSessionListArgs = [7, 50, { type: "consumer" }] as const;

  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("fetch", vi.fn());
    applyPointerCapturePolyfill();
    vi.mocked(getAgentExtensionPackages).mockResolvedValue([]);
    vi.mocked(createInstalledSurfaceSession).mockResolvedValue({
      surface_session_id: "installed-surface-1",
      surface_token: "installed-token-1",
      surface_key: "workspace-editor",
      display_name: "Workspace Editor",
      package_id: "@acme/workspace-tools",
      extension_installation_id: 8,
      agent_id: 7,
      session_id: "session-1",
      workspace_id: "workspace-1",
      workspace_logical_root: "/workspace",
      runtime_url:
        "/api/chat-surfaces/installed-sessions/installed-surface-1/runtime/ui/workspace/",
      created_at: "2026-03-16T00:00:00.000Z",
      bootstrap: {
        surface_session_id: "installed-surface-1",
        surface_token: "installed-token-1",
        mode: "installed",
        surface_key: "workspace-editor",
        display_name: "Workspace Editor",
        package_id: "@acme/workspace-tools",
        extension_installation_id: 8,
        agent_id: 7,
        session_id: "session-1",
        workspace_id: "workspace-1",
        workspace_logical_root: "/workspace",
        runtime_url:
          "/api/chat-surfaces/installed-sessions/installed-surface-1/runtime/ui/workspace/",
        capabilities: ["workspace.read", "workspace.write"],
        files_api: {
          tree_url:
            "/api/chat-surfaces/installed-sessions/installed-surface-1/files/tree",
          content_url:
            "/api/chat-surfaces/installed-sessions/installed-surface-1/files/content",
        },
      },
    });
    vi.mocked(getLLMById).mockResolvedValue({
      image_input: false,
      thinking_policy: "auto",
      thinking_effort: null,
    } as Awaited<ReturnType<typeof getLLMById>>);
    vi.mocked(createProject).mockResolvedValue({
      id: 1,
      project_id: "project-1",
      agent_id: 7,
      name: "New Project",
      description: null,
      workspace_id: "workspace-1",
      created_at: "2026-03-19T00:00:00.000Z",
      updated_at: "2026-03-19T00:00:00.000Z",
    });
    vi.mocked(getAgentWebSearchBindings).mockResolvedValue([]);
    vi.mocked(getReactContextUsage).mockResolvedValue(buildContextUsage());
    vi.mocked(getReactRuntimeSkills).mockResolvedValue([]);
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
    vi.mocked(listProjects).mockResolvedValue({
      projects: [],
      total: 0,
    });
    vi.mocked(updateProject).mockResolvedValue({
      id: 1,
      project_id: "project-1",
      agent_id: 7,
      name: "Renamed project",
      description: null,
      workspace_id: "workspace-1",
      created_at: "2026-03-19T00:00:00.000Z",
      updated_at: "2026-03-19T01:00:00.000Z",
    });
    vi.mocked(httpClient).mockResolvedValue(
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
  });

  afterEach(() => {
    vi.useRealTimers();
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
        initialSessionId="session-1"
      />,
    );

    await waitFor(() => {
      expect(listSessions).toHaveBeenCalledWith(...expectedSessionListArgs);
    });

    expect(createSession).not.toHaveBeenCalled();
    expect(getFullSessionHistory).not.toHaveBeenCalled();
    expect(screen.getByText("Old chat")).toBeInTheDocument();
    expect(screen.getByText("Chat with Pivot Agent")).toBeInTheDocument();
  });

  it("attaches one dev surface from debug tools and opens it from the header", async () => {
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: "session-1",
          agent_id: 7,
          status: "active",
          title: "Surface thread",
          is_pinned: false,
          created_at: "2026-03-16T00:00:00.000Z",
          updated_at: "2026-03-16T00:00:00.000Z",
        },
      ],
      total: 1,
    });
    vi.mocked(createDevSurfaceSession).mockResolvedValue({
      surface_session_id: "surf-1",
      surface_token: "token-1",
      surface_key: "workspace-editor",
      display_name: "Workspace Editor",
      agent_id: 7,
      session_id: "session-1",
      workspace_id: "workspace-1",
      workspace_logical_root: "/workspace",
      dev_server_url: "http://127.0.0.1:4173",
      created_at: "2026-03-16T00:00:00.000Z",
      bootstrap: {
        surface_session_id: "surf-1",
        surface_token: "token-1",
        mode: "dev",
        surface_key: "workspace-editor",
        display_name: "Workspace Editor",
        agent_id: 7,
        session_id: "session-1",
        workspace_id: "workspace-1",
        workspace_logical_root: "/workspace",
        dev_server_url: "http://127.0.0.1:4173",
        capabilities: ["workspace.read", "workspace.write"],
        files_api: {
          tree_url: "/tree",
          content_url: "/content",
        },
      },
    });

    const user = userEvent.setup();

    render(
      <ReactChatInterface
        agentId={7}
        agentName="Pivot Agent"
        primaryLlmId={1}
        initialSessionId="session-1"
      />,
    );

    const debugButton = await screen.findByRole("button", {
      name: "Open compact debug inspector",
    });
    await user.hover(debugButton);

    expect(await screen.findByText("Surface Dev")).toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Attach Dev Surface" }),
      ).not.toBeDisabled();
    });
    await user.click(screen.getByRole("button", { name: "Open Official Sample" }));
    await waitFor(() => {
      expect(createDevSurfaceSession).toHaveBeenCalledWith({
        sessionId: "session-1",
        surfaceKey: "workspace-editor",
        devServerUrl: "http://127.0.0.1:4173",
      });
    });

    const surfaceButton = await screen.findByRole("button", {
      name: "Toggle surface workspace-editor",
    });
    expect(surfaceButton).toBeInTheDocument();

    await user.click(surfaceButton);
    expect(await screen.findByTitle("Surface runtime preview")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Toggle surface workspace-editor" }),
    ).not.toBeInTheDocument();
  });

  it("shows installed surface icons in the header and opens the shared dock", async () => {
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: "session-2",
          agent_id: 7,
          status: "active",
          title: "Installed surface thread",
          is_pinned: false,
          created_at: "2026-03-16T00:00:00.000Z",
          updated_at: "2026-03-16T00:00:00.000Z",
        },
      ],
      total: 1,
    });
    vi.mocked(getAgentExtensionPackages).mockResolvedValue([
      {
        scope: "acme",
        name: "workspace-tools",
        package_id: "@acme/workspace-tools",
        display_name: "Workspace Tools",
        description: "Workspace surfaces",
        logo_url: null,
        latest_version: "0.1.0",
        active_version_count: 1,
        disabled_version_count: 0,
        has_update_available: false,
        selected_binding: {
          id: 5,
          agent_id: 7,
          extension_installation_id: 8,
          enabled: true,
          priority: 100,
          config: {},
          created_at: "2026-03-16T00:00:00.000Z",
          updated_at: "2026-03-16T00:00:00.000Z",
          installation: {
            id: 8,
            scope: "acme",
            name: "workspace-tools",
            package_id: "@acme/workspace-tools",
            version: "0.1.0",
            display_name: "Workspace Tools",
            description: "Workspace surfaces",
            logo_url: null,
            manifest_hash: "hash-1",
            artifact_storage_backend: "local",
            artifact_key: "artifact",
            artifact_digest: "digest",
            artifact_size_bytes: 123,
            install_root: "/tmp/install",
            source: "manual",
            trust_status: "trusted_local",
            trust_source: "local_import",
            hub_scope: null,
            hub_package_id: null,
            hub_package_version_id: null,
            hub_artifact_digest: null,
            installed_by: "alice",
            status: "active",
            created_at: "2026-03-16T00:00:00.000Z",
            updated_at: "2026-03-16T00:00:00.000Z",
            contribution_summary: {
              tools: [],
              skills: [],
              hooks: [],
              chat_surfaces: ["workspace-editor"],
              channel_providers: [],
              image_providers: [],
              web_search_providers: [],
            },
            contribution_items: [
              {
                type: "chat_surface",
                name: "Workspace Editor",
                description: "Installed coding surface",
              },
            ],
            reference_summary: null,
          },
        },
        versions: [],
      },
    ]);

    const user = userEvent.setup();

    render(
      <ReactChatInterface
        agentId={7}
        agentName="Pivot Agent"
        primaryLlmId={1}
        initialSessionId="session-2"
      />,
    );

    const surfaceButton = await screen.findByRole("button", {
      name: "Open surface workspace-editor",
    });
    await user.click(surfaceButton);

    await waitFor(() => {
      expect(createInstalledSurfaceSession).toHaveBeenCalledWith({
        sessionId: "session-2",
        extensionInstallationId: 8,
        surfaceKey: "workspace-editor",
      });
    });
    expect(await screen.findByTitle("Installed surface runtime")).toBeInTheDocument();
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
    vi.mocked(httpClient).mockResolvedValue(
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
      expect(listSessions).toHaveBeenCalledWith(...expectedSessionListArgs);
    });

    await user.click(await screen.findByText("Focused thread"));

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
      mandatory_skill_names: [],
    });
  });

  it("sends ready document attachments together with a typed message", async () => {
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [],
      total: 0,
    });
    vi.mocked(createSession).mockResolvedValue({
      id: 3,
      session_id: "attachment-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: "2026-03-20T00:00:00.000Z",
      updated_at: "2026-03-20T00:00:00.000Z",
    });
    vi.mocked(uploadChatFile).mockResolvedValue({
      file_id: "file-markdown-1",
      kind: "document",
      source: "local",
      original_name: "proposal.md",
      mime_type: "text/markdown",
      format: "markdown",
      extension: "md",
      size_bytes: 24,
      width: 0,
      height: 0,
      page_count: null,
      can_extract_text: true,
      suspected_scanned: false,
      text_encoding: "utf-8",
      session_id: null,
      task_id: null,
      created_at: "2026-03-20T00:00:00.000Z",
    });
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-with-attachment",
      session_id: "attachment-session",
      status: "pending",
      cursor_before_start: 0,
    });

    const user = userEvent.setup();
    const { container } = render(
      <ChatContainer
        agentId={7}
        agentName="Pivot Agent"
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await waitFor(() => {
      expect(listSessions).toHaveBeenCalledWith(...expectedSessionListArgs);
    });

    const documentInput = container.querySelector(
      'input[type="file"][accept=".pdf,.docx,.pptx,.xlsx,.md,.markdown"]',
    );
    expect(documentInput).not.toBeNull();

    await user.upload(
      documentInput as HTMLInputElement,
      new File(["# Proposal"], "proposal.md", { type: "text/markdown" }),
    );

    await screen.findByText("proposal.md");

    await user.type(
      screen.getByPlaceholderText("Ask anything"),
      "Evaluate this markdown proposal",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalledWith({
        agent_id: 7,
        message: "Evaluate this markdown proposal",
        session_id: "attachment-session",
        task_id: null,
        file_ids: ["file-markdown-1"],
        web_search_provider: null,
        thinking_mode: null,
        mandatory_skill_names: [],
      });
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
    vi.mocked(httpClient).mockImplementation(
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
        mandatory_skill_names: [],
      });
    });
  });

  it("keeps skill-only drafts non-sendable without message text", async () => {
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [],
      total: 0,
    });
    vi.mocked(getReactRuntimeSkills).mockResolvedValue([
      {
        name: "sample_skill",
        description: "Example skill description",
        path: "/workspace/skills/sample_skill/SKILL.md",
      },
    ]);
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
      expect(getReactRuntimeSkills).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask anything");
    await user.click(textarea);
    await user.type(textarea, "/");
    await user.click(await screen.findByText("sample_skill"));

    const sendButton = screen.getByRole("button", { name: "Send" });
    expect(sendButton).toBeDisabled();
    await user.click(sendButton);
    expect(startReactTask).not.toHaveBeenCalled();
  });

  it("defaults to Auto mode when the primary LLM exposes a non-fast thinking tier", async () => {
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
    vi.mocked(httpClient).mockResolvedValue(
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
    expect(screen.getByRole("option", { name: "Auto" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Fast" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Thinking" })).toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "Auto" }));

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
        thinking_mode: "auto",
        mandatory_skill_names: [],
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
    vi.mocked(httpClient).mockResolvedValue(
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
        mandatory_skill_names: [],
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
    expect(screen.queryByRole("option", { name: "Auto" })).not.toBeInTheDocument();
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
      expect(listSessions).toHaveBeenCalledWith(...expectedSessionListArgs);
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
              input_message_json: null,
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
    vi.mocked(httpClient).mockResolvedValue(
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
      expect(httpClient).toHaveBeenCalled();
    });

    expect(screen.queryByText("Iteration 2")).not.toBeInTheDocument();
    expect(screen.getAllByText("Planning the sections").length).toBeGreaterThan(
      0,
    );
  });

  it("auto-enters reply mode when a clarify event arrives", async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], total: 0 });
    vi.mocked(createSession).mockResolvedValue({
      id: 5,
      session_id: "clarify-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: "2026-03-20T00:00:00.000Z",
      updated_at: "2026-03-20T00:00:00.000Z",
    });
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-clarify",
      session_id: "clarify-session",
      status: "pending",
      cursor_before_start: 0,
    });

    const encoder = new TextEncoder();
    vi.mocked(httpClient).mockImplementation(() =>
      Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              window.setTimeout(() => {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify({
                      event_id: 1,
                      type: "clarify",
                      task_id: "task-clarify",
                      iteration: 0,
                      timestamp: "2026-03-20T00:00:05.000Z",
                      data: {
                        question:
                          "Which export format do you prefer, PDF or PowerPoint?",
                      },
                    })}\n\n`,
                  ),
                );
                controller.close();
              }, 0);
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
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await user.type(screen.getByPlaceholderText("Ask anything"), "Help me export");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalledWith({
        agent_id: 7,
        message: "Help me export",
        session_id: "clarify-session",
        task_id: null,
        file_ids: [],
        web_search_provider: null,
        thinking_mode: null,
        mandatory_skill_names: [],
      });
    });

    const replyComposer = await screen.findByPlaceholderText("Write your answer...");
    expect(screen.getByText("Replying")).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Which export format do you prefer, PDF or PowerPoint?",
      ),
    ).toHaveLength(2);
    expect(replyComposer).toHaveFocus();
  });

  it("renders inline skill approval actions without switching the composer into reply mode", async () => {
    const sessionId = "skill-approval-session";
    const updatedAt = new Date().toISOString();
    const createdAt = new Date(Date.now() - 60_000).toISOString();
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: sessionId,
          agent_id: 7,
          status: "active",
          title: "Skill approval",
          is_pinned: false,
          created_at: createdAt,
          updated_at: updatedAt,
        },
      ],
      total: 1,
    });
    vi.mocked(startReactTask).mockResolvedValueOnce({
      task_id: "task-skill-approval",
      session_id: sessionId,
      status: "pending",
      cursor_before_start: 0,
    });
    vi.mocked(submitReactUserAction).mockResolvedValue({
      task_id: "task-skill-approval",
      session_id: sessionId,
      status: "pending",
      cursor_before_start: 0,
    });
    vi.mocked(getFullSessionHistory).mockResolvedValue({
      session_id: sessionId,
      last_event_id: 0,
      resume_from_event_id: 0,
      tasks: [
        {
          task_id: "task-skill-approval",
          user_message: "Build me a skill",
          agent_answer: null,
          status: "waiting_input",
          total_tokens: 0,
          pending_user_action: {
            kind: "skill_change_approval",
            approval_request: {
              submission_id: 42,
              skill_name: "planning-kit",
              change_type: "create",
              question:
                "Approve the request to create private skill `planning-kit`?",
              message: "Adds a reusable planning workflow.",
            },
          },
          current_plan: [],
          recursions: [
            {
              iteration: 0,
              trace_id: "trace-skill-approval",
              input_message_json: null,
              observe: null,
              thinking: null,
              reason: null,
              summary: null,
              action_type: "CLARIFY",
              action_output: JSON.stringify({
                question:
                    "Approve the request to create private skill `planning-kit`?",
                approval_request: {
                  submission_id: 42,
                  skill_name: "planning-kit",
                  change_type: "create",
                  question:
                    "Approve the request to create private skill `planning-kit`?",
                  message: "Adds a reusable planning workflow.",
                },
              }),
              tool_call_results: null,
              status: "done",
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
    vi.mocked(httpClient).mockResolvedValue(
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

    const approveButton = await screen.findByRole("button", { name: "Approve" });
    expect(
      screen.getAllByText(/Approve the request to create private skill/).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Replying")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask anything")).toBeInTheDocument();

    await user.click(approveButton);

    await waitFor(() => {
      expect(submitReactUserAction).toHaveBeenCalledWith(
        "task-skill-approval",
        "approve",
      );
    });
    expect(
      screen.queryByText(/Approve the request to create private skill/),
    ).not.toBeInTheDocument();
  });

  it("restores reply mode when session history is already waiting for clarify input", async () => {
    const sessionId = "clarify-history-session";
    const updatedAt = new Date().toISOString();
    const createdAt = new Date(Date.now() - 60_000).toISOString();
    vi.mocked(listSessions).mockResolvedValue({
      sessions: [
        {
          session_id: sessionId,
          agent_id: 7,
          status: "active",
          title: "Clarify thread",
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
          task_id: "task-clarify-history",
          user_message: "Help me export",
          agent_answer: null,
          status: "waiting_input",
          total_tokens: 0,
          current_plan: [],
          recursions: [
            {
              iteration: 0,
              trace_id: "trace-clarify-history",
              input_message_json: null,
              observe: null,
              thinking: null,
              reason: null,
              summary: null,
              action_type: "CLARIFY",
              action_output:
                '{"question":"Which export format do you prefer, PDF or PowerPoint?"}',
              tool_call_results: null,
              status: "done",
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
    vi.mocked(httpClient).mockResolvedValue(
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

    expect(await screen.findByPlaceholderText("Write your answer...")).toBeInTheDocument();
    expect(screen.getByText("Replying")).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Which export format do you prefer, PDF or PowerPoint?",
      ),
    ).toHaveLength(2);
  });

  it("keeps retryable recursion errors out of the final answer while the task continues", async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], total: 0 });
    vi.mocked(createSession).mockResolvedValue({
      id: 9,
      session_id: "retryable-error-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: "2026-03-20T00:00:00.000Z",
      updated_at: "2026-03-20T00:00:00.000Z",
    });
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-retryable-error",
      session_id: "retryable-error-session",
      status: "pending",
      cursor_before_start: 0,
    });

    const encoder = new TextEncoder();
    vi.mocked(httpClient).mockImplementation(() =>
      Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              window.setTimeout(() => {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify({
                      event_id: 1,
                      type: "recursion_start",
                      task_id: "task-retryable-error",
                      trace_id: "trace-retryable-error-1",
                      iteration: 0,
                      timestamp: "2026-03-20T00:00:01.000Z",
                    })}\n\n`,
                  ),
                );
              }, 0);

              window.setTimeout(() => {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify({
                      event_id: 2,
                      type: "error",
                      task_id: "task-retryable-error",
                      trace_id: "trace-retryable-error-1",
                      iteration: 0,
                      timestamp: "2026-03-20T00:00:02.000Z",
                      data: {
                        error: "Temporary sandbox hiccup",
                        terminal: false,
                      },
                    })}\n\n`,
                  ),
                );
              }, 10);

              window.setTimeout(() => {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify({
                      event_id: 3,
                      type: "recursion_start",
                      task_id: "task-retryable-error",
                      trace_id: "trace-retryable-error-2",
                      iteration: 1,
                      timestamp: "2026-03-20T00:00:03.000Z",
                    })}\n\n`,
                  ),
                );
              }, 20);

              window.setTimeout(() => {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify({
                      event_id: 4,
                      type: "answer",
                      task_id: "task-retryable-error",
                      trace_id: "trace-retryable-error-2",
                      iteration: 1,
                      timestamp: "2026-03-20T00:00:04.000Z",
                      data: {
                        answer: "Recovered and completed successfully.",
                      },
                    })}\n\n`,
                  ),
                );
              }, 30);

              window.setTimeout(() => {
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify({
                      event_id: 5,
                      type: "task_complete",
                      task_id: "task-retryable-error",
                      iteration: 1,
                      timestamp: "2026-03-20T00:00:05.000Z",
                      total_tokens: {
                        prompt_tokens: 10,
                        completion_tokens: 5,
                        total_tokens: 15,
                        cached_input_tokens: 0,
                      },
                    })}\n\n`,
                  ),
                );
                controller.close();
              }, 40);
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
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await user.type(screen.getByPlaceholderText("Ask anything"), "Run the checks");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalledWith({
        agent_id: 7,
        message: "Run the checks",
        session_id: "retryable-error-session",
        task_id: null,
        file_ids: [],
        web_search_provider: null,
        thinking_mode: null,
        mandatory_skill_names: [],
      });
    });

    await new Promise((resolve) => window.setTimeout(resolve, 20));

    await new Promise((resolve) => window.setTimeout(resolve, 40));

    expect(
      await screen.findByText("Recovered and completed successfully."),
    ).toBeInTheDocument();
  });

  it("keeps live tool results attached after a CALL_TOOL action event", async () => {
    vi.mocked(listSessions).mockResolvedValue({ sessions: [], total: 0 });
    vi.mocked(createSession).mockResolvedValue({
      id: 10,
      session_id: "tool-live-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: "2026-03-21T00:00:00.000Z",
      updated_at: "2026-03-21T00:00:00.000Z",
    });
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-live-tool",
      session_id: "tool-live-session",
      status: "pending",
      cursor_before_start: 0,
    });

    const encoder = new TextEncoder();
    vi.mocked(httpClient).mockImplementation(() =>
      Promise.resolve(
        new Response(
          new ReadableStream({
            start(controller) {
              const events = [
                {
                  event_id: 1,
                  type: "recursion_start",
                  task_id: "task-live-tool",
                  trace_id: "trace-live-tool",
                  iteration: 0,
                  timestamp: "2026-03-21T00:00:01.000Z",
                },
                {
                  event_id: 2,
                  type: "action",
                  task_id: "task-live-tool",
                  trace_id: "trace-live-tool",
                  iteration: 0,
                  delta: "CALL_TOOL",
                  timestamp: "2026-03-21T00:00:02.000Z",
                },
                {
                  event_id: 3,
                  type: "tool_call",
                  task_id: "task-live-tool",
                  trace_id: "trace-live-tool",
                  iteration: 0,
                  data: {
                    tool_calls: [
                      {
                        id: "call-1",
                        name: "read_file",
                        arguments: { path: "README.md" },
                      },
                    ],
                    tool_results: [
                      {
                        tool_call_id: "call-1",
                        name: "read_file",
                        result: "file contents",
                        success: true,
                      },
                    ],
                  },
                  timestamp: "2026-03-21T00:00:03.000Z",
                },
                {
                  event_id: 4,
                  type: "task_complete",
                  task_id: "task-live-tool",
                  iteration: 0,
                  timestamp: "2026-03-21T00:00:04.000Z",
                },
              ];

              events.forEach((event, index) => {
                window.setTimeout(() => {
                  controller.enqueue(
                    encoder.encode(`data: ${JSON.stringify(event)}\n\n`),
                  );
                  if (index === events.length - 1) {
                    controller.close();
                  }
                }, index * 10);
              });
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
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await user.type(screen.getByPlaceholderText("Ask anything"), "Read the file");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("1 tool");
    await user.click(screen.getByText("1 tool"));

    expect(await screen.findByText("TOOL EXECUTION")).toBeInTheDocument();
    expect(screen.getByText("📤 Result: read_file")).toBeInTheDocument();
  });

  it("reorders the sidebar from the backend after launching a new session task", async () => {
    const olderUpdatedAt = new Date(Date.now() - 30_000).toISOString();
    const olderCreatedAt = new Date(Date.now() - 60_000).toISOString();
    const createdSessionAt = new Date(Date.now() - 120_000).toISOString();
    const refreshedSessions = {
      sessions: [
        {
          session_id: "fresh-session",
          agent_id: 7,
          status: "active",
          title: null,
          is_pinned: false,
          created_at: createdSessionAt,
          updated_at: new Date().toISOString(),
        },
        {
          session_id: "older-session",
          agent_id: 7,
          status: "active",
          title: "Older thread",
          is_pinned: false,
          created_at: olderCreatedAt,
          updated_at: olderUpdatedAt,
        },
      ],
      total: 2,
    };

    vi.mocked(listSessions)
      .mockResolvedValueOnce({
        sessions: [
          {
            session_id: "older-session",
            agent_id: 7,
            status: "active",
            title: "Older thread",
            is_pinned: false,
            created_at: olderCreatedAt,
            updated_at: olderUpdatedAt,
          },
        ],
        total: 1,
      })
      .mockResolvedValueOnce(refreshedSessions)
      .mockResolvedValue(refreshedSessions);
    vi.mocked(createSession).mockResolvedValue({
      id: 6,
      session_id: "fresh-session",
      agent_id: 7,
      user: "alice",
      status: "active",
      title: null,
      is_pinned: false,
      created_at: createdSessionAt,
      updated_at: createdSessionAt,
    });
    vi.mocked(startReactTask).mockResolvedValue({
      task_id: "task-fresh-session",
      session_id: "fresh-session",
      status: "pending",
      cursor_before_start: 0,
    });
    vi.mocked(httpClient).mockImplementation(() =>
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
        primaryLlmId={1}
        sessionIdleTimeoutMinutes={15}
      />,
    );

    await waitFor(() => {
      expect(listSessions).toHaveBeenCalledWith(...expectedSessionListArgs);
    });

    await user.click(screen.getByRole("button", { name: "New Chat" }));
    await user.type(screen.getByPlaceholderText("Ask anything"), "Start fresh");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(startReactTask).toHaveBeenCalledWith({
        agent_id: 7,
        message: "Start fresh",
        session_id: "fresh-session",
        task_id: null,
        file_ids: [],
        web_search_provider: null,
        thinking_mode: null,
        mandatory_skill_names: [],
      });
    });
    await waitFor(() => {
      expect(vi.mocked(listSessions).mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    const newSessionLabel = screen.getByText("New conversation");
    const oldSessionLabel = screen.getByText("Older thread");
    expect(
      newSessionLabel.compareDocumentPosition(oldSessionLabel) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
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
              input_message_json: null,
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
    vi.mocked(httpClient).mockResolvedValue(
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
              input_message_json: null,
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
    vi.mocked(httpClient).mockResolvedValue(
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
