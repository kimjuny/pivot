import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("@/utils/api", () => ({
  deleteAgentChannel: vi.fn(),
  deleteAgentExtensionBinding: vi.fn(),
  deleteAgentMediaProviderBinding: vi.fn(),
  deleteAgentWebSearchBinding: vi.fn(),
  getAgentChannels: vi.fn(),
  getAgentExtensionPackages: vi.fn(),
  getAgentMediaProviderBindings: vi.fn(),
  getAgentSidebarStats: vi.fn(),
  getAgentWebSearchBindings: vi.fn(),
  getChannels: vi.fn(),
  getMediaGenerationProviders: vi.fn(),
  getUsableSkills: vi.fn(),
  getUsableTools: vi.fn(),
  getWebSearchProviders: vi.fn(),
}));

vi.mock("./AgentModal", () => ({
  default: () => null,
}));

vi.mock("./ToolSelectorDialog", () => ({
  default: () => null,
}));

vi.mock("./SkillSelectorDialog", () => ({
  default: () => null,
}));

vi.mock("./ExtensionBindingDialog", () => ({
  default: () => null,
}));

vi.mock("./ChannelBindingDialog", () => ({
  default: () => null,
}));

vi.mock("./WebSearchBindingDialog", () => ({
  default: () => null,
}));

vi.mock("./MediaGenerationBindingDialog", () => ({
  default: () => null,
}));

import { SidebarProvider } from "@/components/ui/sidebar";
import {
  deleteAgentExtensionBinding,
  getAgentChannels,
  getAgentExtensionPackages,
  getAgentMediaProviderBindings,
  getAgentSidebarStats,
  getAgentWebSearchBindings,
  getChannels,
  getMediaGenerationProviders,
  getUsableSkills,
  getUsableTools,
  getWebSearchProviders,
  type UsableTool,
} from "@/utils/api";

import type { Agent } from "../types";

import AgentDetailSidebar from "./AgentDetailSidebar";

const LOGO_DATA_URL =
  "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=";

const baseSidebarStats = {
  tools: { selected_count: 0, total_count: 0 },
  skills: { selected_count: 0, total_count: 0 },
  extensions: { selected_count: 0, total_count: 0 },
  channels: { selected_count: 0, total_count: 0 },
  media: { selected_count: 0, total_count: 0 },
  web_search: { selected_count: 0, total_count: 0 },
};

const baseAgent: Agent = {
  id: 2,
  name: "Qwen Agent",
  description: "Test agent",
  llm_id: 1,
  session_idle_timeout_minutes: 30,
  sandbox_timeout_seconds: 60,
  compact_threshold_percent: 80,
  active_release_id: 3,
  active_release_version: 3,
  serving_enabled: true,
  model_name: "qwen",
  is_active: true,
  max_iteration: 8,
  tool_ids: null,
  skill_ids: null,
  created_at: "2026-04-03T00:00:00+00:00",
  updated_at: "2026-04-03T00:00:00+00:00",
};

/**
 * Build one controllable promise for async race-condition tests.
 * Why: agent switching bugs only show up when an older request resolves out of order.
 */
function createDeferredPromise<T>() {
  let resolvePromise!: (value: T) => void;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return {
    promise,
    resolve: resolvePromise,
  };
}

describe("AgentDetailSidebar", () => {
  it("shows sidebar stat placeholders, lazy-loads section data, and delays skeleton visibility", async () => {
    const user = userEvent.setup();
    const sidebarStats = createDeferredPromise<typeof baseSidebarStats>();
    const tools = createDeferredPromise<UsableTool[]>();
    const extensionPackages = createDeferredPromise<[]>();

    vi.mocked(getAgentSidebarStats).mockReturnValue(sidebarStats.promise);
    vi.mocked(getUsableTools).mockReturnValue(tools.promise);
    vi.mocked(getAgentExtensionPackages).mockReturnValue(extensionPackages.promise);

    render(
      <SidebarProvider defaultOpen={true}>
        <AgentDetailSidebar agent={baseAgent} />
      </SidebarProvider>,
    );

    expect(screen.getAllByText("_ / _")).toHaveLength(6);
    expect(getUsableTools).not.toHaveBeenCalled();
    expect(getAgentExtensionPackages).not.toHaveBeenCalled();

    sidebarStats.resolve({
      ...baseSidebarStats,
      tools: { selected_count: 1, total_count: 3 },
    });

    expect(await screen.findByText("1 / 3")).toBeInTheDocument();

    await user.click(screen.getAllByText("Tools")[1]);

    await waitFor(() => {
      expect(getUsableTools).toHaveBeenCalledTimes(1);
      expect(getAgentExtensionPackages).toHaveBeenCalledWith(2);
    });

    expect(
      screen.queryByTestId("agent-sidebar-tools-skeleton"),
    ).not.toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByTestId("agent-sidebar-tools-skeleton"),
      ).toBeInTheDocument();
    }, {
      timeout: 1200,
    });

    tools.resolve([
      {
        name: "search_docs",
        description: "Search docs",
        parameters: {},
        tool_type: "normal",
        source_type: "builtin",
        read_only: true,
        creator_id: null,
      },
    ]);
    extensionPackages.resolve([]);

    await waitFor(() => {
      expect(
        screen.queryByTestId("agent-sidebar-tools-skeleton"),
      ).not.toBeInTheDocument();
    });
  });

  it("persists extension removals into the parent draft workflow", async () => {
    const user = userEvent.setup();
    const onExtensionBindingsChanged = vi.fn().mockResolvedValue(undefined);

    vi.mocked(getAgentSidebarStats).mockResolvedValue({
      ...baseSidebarStats,
      extensions: { selected_count: 1, total_count: 1 },
    });
    vi.mocked(getUsableTools).mockResolvedValue([]);
    vi.mocked(getUsableSkills).mockResolvedValue([]);
    vi.mocked(getChannels).mockResolvedValue([]);
    vi.mocked(getAgentChannels).mockResolvedValue([]);
    vi.mocked(getMediaGenerationProviders).mockResolvedValue([]);
    vi.mocked(getAgentMediaProviderBindings).mockResolvedValue([]);
    vi.mocked(getWebSearchProviders).mockResolvedValue([]);
    vi.mocked(getAgentWebSearchBindings).mockResolvedValue([]);
    vi.mocked(deleteAgentExtensionBinding).mockResolvedValue(undefined);
    vi.mocked(getAgentExtensionPackages)
      .mockResolvedValueOnce([
        {
          scope: "pivot",
          name: "mem0",
          package_id: "@pivot/mem0",
          display_name: "Mem0",
          description: "External memory extension",
          logo_url: null,
          active_version_count: 1,
          disabled_version_count: 0,
          has_update_available: false,
          selected_binding: {
            id: 7,
            agent_id: 2,
            extension_installation_id: 11,
            enabled: true,
            priority: 0,
            config: {},
            created_at: "2026-04-03T00:00:00+00:00",
            updated_at: "2026-04-03T00:00:00+00:00",
            installation: {
              id: 11,
              scope: "pivot",
              name: "mem0",
              package_id: "@pivot/mem0",
              version: "0.1.0",
              display_name: "Mem0",
              description: "External memory extension",
              logo_url: null,
              manifest_hash: "hash",
              artifact_storage_backend: "local_fs",
              artifact_key: "extensions/pivot/mem0/0.1.0/hash.tar.gz",
              artifact_digest: "digest",
              artifact_size_bytes: 128,
              install_root: "/tmp/extensions/pivot/mem0/0.1.0",
              source: "bundle",
              trust_status: "trusted_local",
              trust_source: "local_import",
              hub_scope: null,
              hub_package_id: null,
              hub_package_version_id: null,
              hub_artifact_digest: null,
              installed_by: "alice",
              creator_id: 1,
              use_scope: "selected",
              read_only: false,
              has_installation_configuration: false,
              status: "active",
              created_at: "2026-04-03T00:00:00+00:00",
              updated_at: "2026-04-03T00:00:00+00:00",
              reference_summary: {
                extension_binding_count: 1,
                channel_binding_count: 0,
                web_search_binding_count: 0,
                binding_count: 1,
                release_count: 0,
                test_snapshot_count: 0,
                saved_draft_count: 0,
              },
              contribution_summary: {
                channel_providers: [],
                media_providers: [],
                web_search_providers: [],
                hooks: [],
                tools: [],
                skills: [],
                chat_surfaces: [],
              },
              contribution_items: [],
            },
          },
          latest_version: "0.1.0",
          versions: [],
        },
      ])
      .mockResolvedValueOnce([
        {
          scope: "pivot",
          name: "mem0",
          package_id: "@pivot/mem0",
          display_name: "Mem0",
          description: "External memory extension",
          logo_url: null,
          active_version_count: 1,
          disabled_version_count: 0,
          has_update_available: false,
          selected_binding: null,
          latest_version: "0.1.0",
          versions: [],
        },
      ]);

    render(
      <SidebarProvider defaultOpen={true}>
        <AgentDetailSidebar
          agent={baseAgent}
          onExtensionBindingsChanged={onExtensionBindingsChanged}
        />
      </SidebarProvider>,
    );

    await user.click(screen.getAllByText("Extensions")[1]);

    await waitFor(() => {
      expect(getAgentExtensionPackages).toHaveBeenCalledWith(2);
    });

    await user.click(screen.getByRole("button", { name: "Delete extension" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(deleteAgentExtensionBinding).toHaveBeenCalledWith(2, 11);
      expect(onExtensionBindingsChanged).toHaveBeenCalledTimes(1);
    });
  });

  it("renders the extension logo in the sidebar when one is available", async () => {
    vi.mocked(getAgentSidebarStats).mockResolvedValue({
      ...baseSidebarStats,
      extensions: { selected_count: 1, total_count: 1 },
      media: { selected_count: 1, total_count: 1 },
    });
    vi.mocked(getUsableTools).mockResolvedValue([]);
    vi.mocked(getUsableSkills).mockResolvedValue([]);
    vi.mocked(getChannels).mockResolvedValue([]);
    vi.mocked(getAgentChannels).mockResolvedValue([]);
    vi.mocked(getMediaGenerationProviders).mockResolvedValue([
      {
        manifest: {
          key: "wasp@image",
          name: "Wasp Image",
          media_type: "image",
          description: "Wasp media provider",
          docs_url: "https://example.com/wasp-image",
          visibility: "extension",
          status: "active",
          extension_name: "@wasp/plugin",
          extension_display_name: "Wasp Plugin",
          extension_version: "0.1.0",
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
          supported_operations: [],
          supported_parameters: [],
          capability_flags: {},
        },
      },
    ]);
    vi.mocked(getAgentMediaProviderBindings).mockResolvedValue([
      {
        id: 17,
        agent_id: 2,
        provider_key: "wasp@image",
        enabled: true,
        auth_config: {},
        runtime_config: {},
        last_health_status: "healthy",
        last_health_message: "ok",
        last_health_check_at: "2026-04-03T00:00:00+00:00",
        created_at: "2026-04-03T00:00:00+00:00",
        updated_at: "2026-04-03T00:00:00+00:00",
        manifest: {
          key: "wasp@image",
          name: "Wasp Image",
          media_type: "image",
          description: "Wasp media provider",
          docs_url: "https://example.com/wasp-image",
          visibility: "extension",
          status: "active",
          extension_name: "@wasp/plugin",
          extension_display_name: "Wasp Plugin",
          extension_version: "0.1.0",
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
          supported_operations: [],
          supported_parameters: [],
          capability_flags: {},
        },
      },
    ]);
    vi.mocked(getWebSearchProviders).mockResolvedValue([]);
    vi.mocked(getAgentWebSearchBindings).mockResolvedValue([]);
    vi.mocked(getAgentExtensionPackages).mockResolvedValue([
      {
        scope: "wasp",
        name: "plugin",
        package_id: "@wasp/plugin",
        display_name: "Wasp Plugin",
        description: "Wasp framework skills",
        logo_url: LOGO_DATA_URL,
        active_version_count: 1,
        disabled_version_count: 0,
        has_update_available: false,
        selected_binding: {
          id: 3,
          agent_id: 2,
          extension_installation_id: 7,
          enabled: true,
          priority: 0,
          config: {},
          created_at: "2026-04-03T00:00:00+00:00",
          updated_at: "2026-04-03T00:00:00+00:00",
          installation: {
            id: 7,
            scope: "wasp",
            name: "plugin",
            package_id: "@wasp/plugin",
            version: "0.1.0",
            display_name: "Wasp Plugin",
            description: "Wasp framework skills",
            logo_url: LOGO_DATA_URL,
            manifest_hash: "hash",
            artifact_storage_backend: "local_fs",
            artifact_key: "extensions/wasp/plugin/0.1.0/hash.tar.gz",
            artifact_digest: "digest",
            artifact_size_bytes: 128,
            install_root: "/tmp/extensions/wasp/plugin/0.1.0",
            source: "bundle",
            trust_status: "trusted_local",
            trust_source: "local_import",
            hub_scope: null,
            hub_package_id: null,
            hub_package_version_id: null,
            hub_artifact_digest: null,
            installed_by: "alice",
            creator_id: 1,
            use_scope: "selected",
            read_only: false,
            has_installation_configuration: false,
            status: "active",
            created_at: "2026-04-03T00:00:00+00:00",
            updated_at: "2026-04-03T00:00:00+00:00",
            reference_summary: {
              extension_binding_count: 1,
              channel_binding_count: 0,
              web_search_binding_count: 0,
              binding_count: 1,
              release_count: 0,
              test_snapshot_count: 0,
              saved_draft_count: 0,
            },
            contribution_summary: {
              channel_providers: [],
              media_providers: [],
              web_search_providers: [],
              hooks: [],
              tools: [],
              skills: [],
              chat_surfaces: [],
            },
            contribution_items: [],
          },
        },
        latest_version: "0.1.0",
        versions: [],
      },
    ]);

    render(
      <SidebarProvider defaultOpen={true}>
        <AgentDetailSidebar
          agent={baseAgent}
        />
      </SidebarProvider>,
    );

    await userEvent.setup().click(screen.getAllByText("Extensions")[1]);

    await waitFor(() => {
      expect(getAgentExtensionPackages).toHaveBeenCalledWith(2);
    });

    expect(screen.getByAltText("Wasp Plugin logo")).toHaveAttribute(
      "src",
      LOGO_DATA_URL,
    );

    await userEvent.setup().click(screen.getAllByText("Media")[1]);

    expect(screen.getAllByAltText("Wasp Image logo")[0]).toHaveAttribute(
      "src",
      LOGO_DATA_URL,
    );
  });

  it("clears stale web search bindings and keeps the next agent lazy-loaded", async () => {
    const user = userEvent.setup();
    const nextAgentBindings = createDeferredPromise<[]>();
    const nextAgent: Agent = {
      ...baseAgent,
      id: 9,
      name: "Claude Agent",
    };

    vi.mocked(getAgentSidebarStats).mockResolvedValue({
      ...baseSidebarStats,
      web_search: { selected_count: 1, total_count: 1 },
    });
    vi.mocked(getUsableTools).mockResolvedValue([]);
    vi.mocked(getUsableSkills).mockResolvedValue([]);
    vi.mocked(getChannels).mockResolvedValue([]);
    vi.mocked(getAgentChannels).mockResolvedValue([]);
    vi.mocked(getMediaGenerationProviders).mockResolvedValue([]);
    vi.mocked(getAgentMediaProviderBindings).mockResolvedValue([]);
    vi.mocked(getWebSearchProviders).mockResolvedValue([]);
    vi.mocked(getAgentExtensionPackages).mockResolvedValue([]);
    vi.mocked(getAgentWebSearchBindings)
      .mockResolvedValueOnce([
        {
          id: 41,
          agent_id: baseAgent.id,
          provider_key: "baidu",
          enabled: true,
          auth_config: {},
          runtime_config: {},
          last_health_status: "healthy",
          last_health_message: "ok",
          last_health_check_at: "2026-04-03T00:00:00+00:00",
          created_at: "2026-04-03T00:00:00+00:00",
          updated_at: "2026-04-03T00:00:00+00:00",
          manifest: {
            key: "baidu",
            name: "Baidu Search",
            description: "Baidu search provider",
            docs_url: "https://example.com/baidu",
            visibility: "builtin",
            status: "active",
            logo_url: null,
            extension_name: null,
            extension_display_name: null,
            extension_version: null,
            setup_steps: [],
            supported_parameters: [],
            auth_schema: [],
            config_schema: [],
          },
        },
      ])
      .mockImplementation((agentId: number) => {
        if (agentId === nextAgent.id) {
          return nextAgentBindings.promise;
        }
        return Promise.resolve([]);
      });

    const { rerender } = render(
      <SidebarProvider defaultOpen={true}>
        <AgentDetailSidebar
          agent={baseAgent}
        />
      </SidebarProvider>,
    );

    await user.click(screen.getAllByText("Web Search")[1]);

    expect((await screen.findAllByText("Baidu Search")).length).toBeGreaterThan(0);

    rerender(
      <SidebarProvider defaultOpen={true}>
        <AgentDetailSidebar
          agent={nextAgent}
        />
      </SidebarProvider>,
    );

    await waitFor(() => {
      expect(screen.queryAllByText("Baidu Search")).toHaveLength(0);
    });

    expect(getAgentWebSearchBindings).toHaveBeenCalledTimes(1);

    await user.click(screen.getAllByText("Web Search")[1]);

    nextAgentBindings.resolve([]);

    expect(
      await screen.findByRole("button", { name: "Add first web search" }),
    ).toBeInTheDocument();
  });
});
