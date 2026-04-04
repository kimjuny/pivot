import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("@/utils/api", () => ({
  getExtensionPackages: vi.fn(),
  getExtensionInstallationConfiguration: vi.fn(),
  uninstallExtensionInstallation: vi.fn(),
  updateExtensionInstallationConfiguration: vi.fn(),
  updateExtensionInstallationStatus: vi.fn(),
  getExtensionHookExecutions: vi.fn(),
  replayExtensionHookExecution: vi.fn(),
}));

import {
  getExtensionInstallationConfiguration,
  getExtensionPackages,
  uninstallExtensionInstallation,
  updateExtensionInstallationStatus,
} from "@/utils/api";

import ExtensionDetailPage from "./ExtensionDetailPage";

describe("ExtensionDetailPage", () => {
  it("renders package overview and package-scoped hook replay", async () => {
    vi.mocked(getExtensionPackages).mockResolvedValue([
      {
        scope: "acme",
        name: "memory",
        package_id: "@acme/memory",
        display_name: "ACME Memory",
        description: "External memory sample",
        logo_url: null,
        readme_markdown: "# ACME Memory\n\nThis package recalls memory.",
        latest_version: "1.0.0",
        active_version_count: 1,
        disabled_version_count: 0,
        versions: [
          {
            id: 11,
            scope: "acme",
            name: "memory",
            package_id: "@acme/memory",
            version: "1.0.0",
            display_name: "ACME Memory",
            description: "External memory sample",
            logo_url: null,
            manifest_hash: "hash",
            artifact_storage_backend: "local_fs",
            artifact_key: "extensions/acme/memory/1.0.0/hash.tar.gz",
            artifact_digest: "artifact-hash",
            artifact_size_bytes: 128,
            install_root: "/tmp/@acme/memory/1.0.0",
            source: "bundle",
            trust_status: "trusted_local",
            trust_source: "local_import",
            hub_scope: null,
            hub_package_id: null,
            hub_package_version_id: null,
            hub_artifact_digest: null,
            installed_by: "alice",
            status: "active",
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
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
              hooks: ["Recall Stored Memory"],
              tools: [],
              skills: [],
            },
            contribution_items: [
              {
                type: "hook",
                name: "Recall Stored Memory",
                description: "Loads relevant memory before the task starts.",
              },
            ],
          },
        ],
      },
    ]);
    vi.mocked(getExtensionInstallationConfiguration).mockResolvedValue({
      installation_id: 11,
      package_id: "@acme/memory",
      version: "1.0.0",
      configuration_schema: {
        installation: {
          fields: [
            {
              key: "base_url",
              label: "Base URL",
              type: "string",
              description: "Memory service base URL",
              required: true,
              default: "http://localhost:8765",
              placeholder: "http://localhost:8765",
            },
          ],
        },
        binding: { fields: [] },
      },
      config: {
        base_url: "http://localhost:8765",
      },
    });
    render(
      <MemoryRouter initialEntries={["/studio/assets/extensions/acme/memory"]}>
        <Routes>
          <Route path="/studio/assets/extensions/:scope/:name" element={<ExtensionDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("ACME Memory").length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText("@acme/memory")).toHaveLength(2);
    expect(screen.getAllByText("Trusted Local")).toHaveLength(1);
    expect(
      screen.getByRole("heading", { level: 2, name: "README.md" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Includes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Information" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Current Package Status")).not.toBeInTheDocument();
    expect(screen.queryByText("Quick Actions")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Disable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Uninstall" }),
    ).toBeInTheDocument();
    expect(screen.getByText("This package recalls memory.")).toBeInTheDocument();
    expect(screen.getByText("Recall Stored Memory")).toBeInTheDocument();
    expect(screen.getByText("Loads relevant memory before the task starts.")).toBeInTheDocument();
    expect(screen.getByText("Hook")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Setup" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Versions" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Hook Replay" })).toBeInTheDocument();
  });

  it("surfaces quick actions for the latest installation", async () => {
    vi.mocked(getExtensionPackages).mockResolvedValue([
      {
        scope: "pivot",
        name: "mem0",
        package_id: "@pivot/mem0",
        display_name: "Mem0 Memory",
        description: "External memory store",
        logo_url: "http://localhost:8000/api/extensions/installations/7/logo",
        readme_markdown: "",
        latest_version: "0.1.0",
        active_version_count: 1,
        disabled_version_count: 0,
        versions: [
          {
            id: 7,
            scope: "pivot",
            name: "mem0",
            package_id: "@pivot/mem0",
            version: "0.1.0",
            display_name: "Mem0 Memory",
            description: "External memory store",
            logo_url: "http://localhost:8000/api/extensions/installations/7/logo",
            manifest_hash: "hash",
            artifact_storage_backend: "local_fs",
            artifact_key: "extensions/pivot/mem0/0.1.0/hash.tar.gz",
            artifact_digest: "artifact-hash",
            artifact_size_bytes: 128,
            install_root: "/tmp/@pivot/mem0/0.1.0",
            source: "bundle",
            trust_status: "trusted_local",
            trust_source: "local_import",
            hub_scope: null,
            hub_package_id: null,
            hub_package_version_id: null,
            hub_artifact_digest: null,
            installed_by: "alice",
            status: "active",
            created_at: "2026-04-01T00:00:00Z",
            updated_at: "2026-04-01T00:00:00Z",
            reference_summary: null,
            contribution_summary: {
              channel_providers: [],
              web_search_providers: [],
              hooks: [],
              tools: [],
              skills: [],
            },
            contribution_items: [],
          },
        ],
      },
    ]);
    vi.mocked(getExtensionInstallationConfiguration).mockResolvedValue({
      installation_id: 7,
      package_id: "@pivot/mem0",
      version: "0.1.0",
      configuration_schema: {
        installation: { fields: [] },
        binding: { fields: [] },
      },
      config: {},
    });
    vi.mocked(updateExtensionInstallationStatus).mockResolvedValue({
      id: 7,
      scope: "pivot",
      name: "mem0",
      package_id: "@pivot/mem0",
      version: "0.1.0",
      display_name: "Mem0 Memory",
      description: "External memory store",
      logo_url: "http://localhost:8000/api/extensions/installations/7/logo",
      manifest_hash: "hash",
      artifact_storage_backend: "local_fs",
      artifact_key: "extensions/pivot/mem0/0.1.0/hash.tar.gz",
      artifact_digest: "artifact-hash",
      artifact_size_bytes: 128,
      install_root: "/tmp/@pivot/mem0/0.1.0",
      source: "bundle",
      trust_status: "trusted_local",
      trust_source: "local_import",
      hub_scope: null,
      hub_package_id: null,
      hub_package_version_id: null,
      hub_artifact_digest: null,
      installed_by: "alice",
      status: "disabled",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:00:00Z",
      reference_summary: null,
      contribution_summary: {
        channel_providers: [],
        web_search_providers: [],
        hooks: [],
        tools: [],
        skills: [],
      },
      contribution_items: [],
    });
    vi.mocked(uninstallExtensionInstallation).mockResolvedValue({
      mode: "logical",
      references: {
        extension_binding_count: 1,
        channel_binding_count: 0,
        web_search_binding_count: 0,
        binding_count: 1,
        release_count: 0,
        test_snapshot_count: 0,
        saved_draft_count: 0,
      },
      installation: {
        id: 7,
        scope: "pivot",
        name: "mem0",
        package_id: "@pivot/mem0",
        version: "0.1.0",
        display_name: "Mem0 Memory",
        description: "External memory store",
        logo_url: "http://localhost:8000/api/extensions/installations/7/logo",
        manifest_hash: "hash",
        artifact_storage_backend: "local_fs",
        artifact_key: "extensions/pivot/mem0/0.1.0/hash.tar.gz",
        artifact_digest: "artifact-hash",
        artifact_size_bytes: 128,
        install_root: "/tmp/@pivot/mem0/0.1.0",
        source: "bundle",
        trust_status: "trusted_local",
        trust_source: "local_import",
        hub_scope: null,
        hub_package_id: null,
        hub_package_version_id: null,
        hub_artifact_digest: null,
        installed_by: "alice",
        status: "disabled",
        created_at: "2026-04-01T00:00:00Z",
        updated_at: "2026-04-01T00:00:00Z",
        reference_summary: null,
        contribution_summary: {
          channel_providers: [],
          web_search_providers: [],
          hooks: [],
          tools: [],
          skills: [],
        },
        contribution_items: [],
      },
    });

    render(
      <MemoryRouter initialEntries={["/studio/assets/extensions/pivot/mem0"]}>
        <Routes>
          <Route path="/studio/assets/extensions/:scope/:name" element={<ExtensionDetailPage />} />
          <Route path="/studio/assets/extensions" element={<div>Extension list route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Mem0 Memory").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole("button", { name: "Disable" }));

    await waitFor(() => {
      expect(updateExtensionInstallationStatus).toHaveBeenCalledWith(7, "disabled");
    });

    fireEvent.click(screen.getByRole("button", { name: "Uninstall" }));

    await waitFor(() => {
      expect(screen.getByText("Uninstall Extension Version")).toBeInTheDocument();
    });

    const uninstallButtons = screen.getAllByRole("button", { name: "Uninstall" });
    fireEvent.click(uninstallButtons[uninstallButtons.length - 1]);

    await waitFor(() => {
      expect(uninstallExtensionInstallation).toHaveBeenCalledWith(7);
    });
  });
});
