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
  deleteAgentWebSearchBinding: vi.fn(),
  getAgentChannels: vi.fn(),
  getAgentExtensionPackages: vi.fn(),
  getAgentWebSearchBindings: vi.fn(),
  getChannels: vi.fn(),
  getPrivateSkills: vi.fn(),
  getPrivateTools: vi.fn(),
  getSharedSkills: vi.fn(),
  getSharedTools: vi.fn(),
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

import { SidebarProvider } from "@/components/ui/sidebar";
import {
  deleteAgentExtensionBinding,
  getAgentChannels,
  getAgentExtensionPackages,
  getAgentWebSearchBindings,
  getChannels,
  getPrivateSkills,
  getPrivateTools,
  getSharedSkills,
  getSharedTools,
  getWebSearchProviders,
} from "@/utils/api";

import type { Agent, Scene } from "../types";

import AgentDetailSidebar from "./AgentDetailSidebar";

const baseAgent: Agent = {
  id: 2,
  name: "Qwen Agent",
  description: "Test agent",
  llm_id: 1,
  skill_resolution_llm_id: null,
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
  scenes: [],
};

describe("AgentDetailSidebar", () => {
  it("persists extension removals into the parent draft workflow", async () => {
    const user = userEvent.setup();
    const onExtensionBindingsChanged = vi.fn().mockResolvedValue(undefined);

    vi.mocked(getSharedTools).mockResolvedValue([]);
    vi.mocked(getPrivateTools).mockResolvedValue([]);
    vi.mocked(getSharedSkills).mockResolvedValue([]);
    vi.mocked(getPrivateSkills).mockResolvedValue([]);
    vi.mocked(getChannels).mockResolvedValue([]);
    vi.mocked(getAgentChannels).mockResolvedValue([]);
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
                web_search_providers: [],
                hooks: [],
                tools: [],
                skills: [],
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
          scenes={[] as Scene[]}
          selectedScene={null}
          onSceneSelect={vi.fn()}
          onCreateScene={vi.fn()}
          onDeleteScene={vi.fn()}
          onExtensionBindingsChanged={onExtensionBindingsChanged}
        />
      </SidebarProvider>,
    );

    await waitFor(() => {
      expect(getAgentExtensionPackages).toHaveBeenCalledWith(2);
    });

    await user.click(screen.getAllByText("Extensions")[1]);

    await user.click(screen.getByRole("button", { name: "Delete extension" }));

    await waitFor(() => {
      expect(deleteAgentExtensionBinding).toHaveBeenCalledWith(2, 11);
      expect(onExtensionBindingsChanged).toHaveBeenCalledTimes(1);
    });
  });
});
