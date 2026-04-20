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
  getExtensionInstallationReferences: vi.fn(),
  importExtensionBundle: vi.fn(),
  previewExtensionBundle: vi.fn(),
  uninstallExtensionInstallation: vi.fn(),
  updateExtensionInstallationStatus: vi.fn(),
}));

import { getExtensionPackages, importExtensionBundle, previewExtensionBundle } from "@/utils/api";

import ExtensionsPage from "./ExtensionsPage";

describe("ExtensionsPage", () => {
  it("links each package card to its package detail page", async () => {
    vi.mocked(getExtensionPackages).mockResolvedValue([
      {
        scope: "acme",
        name: "providers",
        package_id: "@acme/providers",
        display_name: "ACME Providers",
        description: "Provider package",
        logo_url: null,
        readme_markdown: "# Providers",
        latest_version: "1.0.0",
        active_version_count: 1,
        disabled_version_count: 0,
        versions: [
          {
            id: 1,
            scope: "acme",
            name: "providers",
            package_id: "@acme/providers",
            version: "1.0.0",
            display_name: "ACME Providers",
            description: "Provider package",
            logo_url: null,
            manifest_hash: "hash",
            artifact_storage_backend: "local_fs",
            artifact_key: "extensions/acme/providers/1.0.0/hash.tar.gz",
            artifact_digest: "artifact-hash",
            artifact_size_bytes: 128,
            install_root: "/tmp/@acme/providers/1.0.0",
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
              extension_binding_count: 0,
              channel_binding_count: 2,
              web_search_binding_count: 1,
              binding_count: 3,
              release_count: 1,
              test_snapshot_count: 0,
              saved_draft_count: 0,
            },
            contribution_summary: {
              channel_providers: ["acme@chat"],
              web_search_providers: ["acme@search"],
              hooks: [],
              tools: ["search_accounts"],
              skills: ["crm_research"],
            },
            contribution_items: [],
          },
        ],
      },
    ]);

    render(
      <MemoryRouter initialEntries={["/studio/assets/extensions"]}>
        <Routes>
          <Route path="/studio/assets/extensions" element={<ExtensionsPage />} />
          <Route
            path="/studio/assets/extensions/:scope/:name"
            element={<div>Extension detail route</div>}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("ACME Providers")).toBeInTheDocument();
    });

    expect(screen.getByText("by acme")).toBeInTheDocument();
    expect(screen.getByText("Provider package")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Extension options for ACME Providers" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open extension ACME Providers" }));

    await waitFor(() => {
      expect(screen.getByText("Extension detail route")).toBeInTheDocument();
    });
  });

  it("filters packages by enabled and disabled status", async () => {
    vi.mocked(getExtensionPackages).mockResolvedValue([
      {
        scope: "acme",
        name: "providers",
        package_id: "@acme/providers",
        display_name: "ACME Providers",
        description: "Enabled package",
        logo_url: null,
        readme_markdown: "",
        latest_version: "1.0.0",
        active_version_count: 1,
        disabled_version_count: 0,
        versions: [
          {
            id: 1,
            scope: "acme",
            name: "providers",
            package_id: "@acme/providers",
            version: "1.0.0",
            display_name: "ACME Providers",
            description: "Enabled package",
            logo_url: null,
            manifest_hash: "hash-1",
            artifact_storage_backend: "local_fs",
            artifact_key: "extensions/acme/providers/1.0.0/hash.tar.gz",
            artifact_digest: "artifact-hash-1",
            artifact_size_bytes: 128,
            install_root: "/tmp/@acme/providers/1.0.0",
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
      {
        scope: "pivot",
        name: "mem0",
        package_id: "@pivot/mem0",
        display_name: "Mem0 Memory",
        description: "Disabled package",
        logo_url: null,
        readme_markdown: "",
        latest_version: "0.1.0",
        active_version_count: 0,
        disabled_version_count: 1,
        versions: [
          {
            id: 2,
            scope: "pivot",
            name: "mem0",
            package_id: "@pivot/mem0",
            version: "0.1.0",
            display_name: "Mem0 Memory",
            description: "Disabled package",
            logo_url: null,
            manifest_hash: "hash-2",
            artifact_storage_backend: "local_fs",
            artifact_key: "extensions/pivot/mem0/0.1.0/hash.tar.gz",
            artifact_digest: "artifact-hash-2",
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
        ],
      },
    ]);

    render(
      <MemoryRouter>
        <ExtensionsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("ACME Providers")).toBeInTheDocument();
      expect(screen.getByText("Mem0 Memory")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /enabled/i }));

    expect(screen.getByText("ACME Providers")).toBeInTheDocument();
    expect(screen.queryByText("Mem0 Memory")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /disabled/i }));

    expect(screen.getByText("Mem0 Memory")).toBeInTheDocument();
    expect(screen.queryByText("ACME Providers")).not.toBeInTheDocument();
  });

  it("requires an explicit trust step before importing a local bundle", async () => {
    vi.mocked(getExtensionPackages).mockResolvedValue([]);
    vi.mocked(previewExtensionBundle).mockResolvedValue({
      scope: "acme",
      name: "providers",
      package_id: "@acme/providers",
      version: "1.0.0",
      display_name: "ACME Providers",
      description: "Provider package",
      source: "bundle",
      trust_status: "unverified",
      trust_source: "local_import",
      manifest_hash: "hash-preview",
      contribution_summary: {
        channel_providers: ["acme@chat"],
        chat_surfaces: ["workspace-editor"],
        web_search_providers: ["acme@search"],
        hooks: [],
        tools: [],
        skills: [],
      },
      contribution_items: [],
      permissions: {
        network: {
          allow_hosts: ["api.acme.com"],
        },
      },
      existing_installation_id: null,
      existing_installation_status: null,
      identical_to_installed: false,
      requires_overwrite_confirmation: false,
      overwrite_blocked_reason: "",
      existing_reference_summary: null,
    });
    vi.mocked(importExtensionBundle).mockResolvedValue({
      id: 2,
      scope: "acme",
      name: "providers",
      package_id: "@acme/providers",
      version: "1.0.0",
      display_name: "ACME Providers",
      description: "Provider package",
      logo_url: null,
      manifest_hash: "hash",
      artifact_storage_backend: "local_fs",
      artifact_key: "extensions/acme/providers/1.0.0/hash.tar.gz",
      artifact_digest: "artifact-hash",
      artifact_size_bytes: 128,
      install_root: "/tmp/@acme/providers/1.0.0",
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
        channel_providers: ["acme@chat"],
        web_search_providers: ["acme@search"],
        hooks: [],
        tools: [],
        skills: [],
      },
      contribution_items: [],
    });

    const { container } = render(
      <MemoryRouter>
        <ExtensionsPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("No extensions installed yet.")).toBeInTheDocument();
    });

    const input = container.querySelector('input[type="file"]');
    if (!(input instanceof HTMLInputElement)) {
      throw new Error("Expected hidden file input");
    }
    const manifest = new File(["{}"], "manifest.json", { type: "application/json" });
    Object.defineProperty(manifest, "webkitRelativePath", {
      value: "acme-bundle/manifest.json",
    });

    fireEvent.change(input, { target: { files: [manifest] } });

    await waitFor(() => {
      expect(screen.getByText("Trust Extension")).toBeInTheDocument();
    });
    expect(screen.getByText("@acme/providers")).toBeInTheDocument();
    expect(screen.getByText("Chat Surfaces")).toBeInTheDocument();
    expect(screen.getByText("workspace-editor")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Trust and Install" }));

    await waitFor(() => {
      expect(importExtensionBundle).toHaveBeenCalledWith([manifest], {
        trustConfirmed: true,
        overwriteConfirmed: false,
      });
    });
  });

  it("prompts for overwrite when a different same-version package is already installed", async () => {
    vi.mocked(getExtensionPackages).mockResolvedValue([]);
    vi.mocked(previewExtensionBundle).mockResolvedValue({
      scope: "acme",
      name: "providers",
      package_id: "@acme/providers",
      version: "1.0.0",
      display_name: "ACME Providers",
      description: "Provider package",
      source: "bundle",
      trust_status: "unverified",
      trust_source: "local_import",
      manifest_hash: "hash-preview-2",
      contribution_summary: {
        channel_providers: ["acme@chat"],
        web_search_providers: ["acme@search"],
        hooks: [],
        tools: [],
        skills: [],
      },
      contribution_items: [],
      permissions: {},
      existing_installation_id: 9,
      existing_installation_status: "active",
      identical_to_installed: false,
      requires_overwrite_confirmation: true,
      overwrite_blocked_reason: "",
      existing_reference_summary: {
        extension_binding_count: 0,
        channel_binding_count: 0,
        web_search_binding_count: 0,
        binding_count: 0,
        release_count: 0,
        test_snapshot_count: 0,
        saved_draft_count: 0,
      },
    });
    vi.mocked(importExtensionBundle).mockResolvedValue({
      id: 2,
      scope: "acme",
      name: "providers",
      package_id: "@acme/providers",
      version: "1.0.0",
      display_name: "ACME Providers",
      description: "Provider package",
      logo_url: null,
      manifest_hash: "hash-new",
      artifact_storage_backend: "local_fs",
      artifact_key: "extensions/acme/providers/1.0.0/artifact/hash-new.tar.gz",
      artifact_digest: "artifact-hash",
      artifact_size_bytes: 128,
      install_root: "/tmp/@acme/providers/1.0.0/runtime",
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
        channel_providers: ["acme@chat"],
        web_search_providers: ["acme@search"],
        hooks: [],
        tools: [],
        skills: [],
      },
      contribution_items: [],
    });

    const { container } = render(
      <MemoryRouter>
        <ExtensionsPage />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("No extensions installed yet.")).toBeInTheDocument();
    });

    const input = container.querySelector('input[type="file"]');
    if (!(input instanceof HTMLInputElement)) {
      throw new Error("Expected hidden file input");
    }
    const manifest = new File(["{}"], "manifest.json", { type: "application/json" });
    Object.defineProperty(manifest, "webkitRelativePath", {
      value: "acme-bundle/manifest.json",
    });

    fireEvent.change(input, { target: { files: [manifest] } });

    await waitFor(() => {
      expect(screen.getByText("Trust Extension")).toBeInTheDocument();
    });
    expect(screen.getByText(/replace that installed version/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Trust and Overwrite" }));

    await waitFor(() => {
      expect(importExtensionBundle).toHaveBeenCalledWith([manifest], {
        trustConfirmed: true,
        overwriteConfirmed: true,
      });
    });
  });
});
