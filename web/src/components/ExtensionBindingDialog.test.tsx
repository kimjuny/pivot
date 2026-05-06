import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const navigateMock = vi.hoisted(() => vi.fn());

vi.mock("@/utils/api", () => ({
  replaceAgentExtensionBindings: vi.fn(),
  upsertAgentExtensionBinding: vi.fn(),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

import ExtensionBindingDialog from "./ExtensionBindingDialog";

describe("ExtensionBindingDialog", () => {
  it("shows an empty state when no extension can be installed yet", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <ExtensionBindingDialog
        open={true}
        onOpenChange={onOpenChange}
        agentId={3}
        packages={[]}
        initialPackage={null}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getByText("No extensions installed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Go to Extensions" }));

    expect(navigateMock).toHaveBeenCalledWith("/studio/assets/extensions");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("renders package logos and keeps latest metadata inside version choices", async () => {
    const user = userEvent.setup();
    if (!("hasPointerCapture" in HTMLElement.prototype)) {
      Object.defineProperty(HTMLElement.prototype, "hasPointerCapture", {
        value: () => false,
        configurable: true,
      });
    }
    if (!("setPointerCapture" in HTMLElement.prototype)) {
      Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
        value: () => {},
        configurable: true,
      });
    }
    if (!("releasePointerCapture" in HTMLElement.prototype)) {
      Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
        value: () => {},
        configurable: true,
      });
    }

    render(
      <ExtensionBindingDialog
        open={true}
        onOpenChange={vi.fn()}
        agentId={3}
        packages={[
          {
            scope: "pivot",
            name: "notion-kit",
            package_id: "@pivot/notion-kit",
            display_name: "Notion Kit",
            description: "Notion provider bundle",
            logo_url: "https://example.com/notion.png",
            latest_version: "0.1.7",
            active_version_count: 1,
            disabled_version_count: 1,
            has_update_available: false,
            selected_binding: null,
            versions: [
              {
                id: 7,
                scope: "pivot",
                name: "notion-kit",
                package_id: "@pivot/notion-kit",
                version: "0.1.7",
                display_name: "Notion Kit",
                description: "Notion provider bundle",
                logo_url: "https://example.com/notion.png",
                manifest_hash: "hash-7",
                artifact_storage_backend: "local",
                artifact_key: "notion-7",
                artifact_digest: "digest-7",
                artifact_size_bytes: 1,
                install_root: "/tmp/notion-7",
                source: "manual",
                trust_status: "trusted_local",
                trust_source: "local_import",
                hub_scope: null,
                hub_package_id: null,
                hub_package_version_id: null,
                hub_artifact_digest: null,
                installed_by: null,
                creator_id: null,
                use_scope: "selected",
                read_only: false,
                has_installation_configuration: false,
                status: "active",
                created_at: "2026-04-20T00:00:00Z",
                updated_at: "2026-04-20T00:00:00Z",
                contribution_summary: {
                  tools: [],
                  skills: [],
                  hooks: [],
                  channel_providers: [],
                  media_providers: [],
                  web_search_providers: [],
                },
                contribution_items: [],
                reference_summary: null,
              },
              {
                id: 6,
                scope: "pivot",
                name: "notion-kit",
                package_id: "@pivot/notion-kit",
                version: "0.1.6",
                display_name: "Notion Kit",
                description: "Notion provider bundle",
                logo_url: "https://example.com/notion.png",
                manifest_hash: "hash-6",
                artifact_storage_backend: "local",
                artifact_key: "notion-6",
                artifact_digest: "digest-6",
                artifact_size_bytes: 1,
                install_root: "/tmp/notion-6",
                source: "manual",
                trust_status: "trusted_local",
                trust_source: "local_import",
                hub_scope: null,
                hub_package_id: null,
                hub_package_version_id: null,
                hub_artifact_digest: null,
                installed_by: null,
                creator_id: null,
                use_scope: "selected",
                read_only: false,
                has_installation_configuration: false,
                status: "disabled",
                created_at: "2026-04-19T00:00:00Z",
                updated_at: "2026-04-19T00:00:00Z",
                contribution_summary: {
                  tools: [],
                  skills: [],
                  hooks: [],
                  channel_providers: [],
                  media_providers: [],
                  web_search_providers: [],
                },
                contribution_items: [],
                reference_summary: null,
              },
            ],
          },
        ]}
        initialPackage={null}
        onSaved={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("img", { name: "Notion Kit logo" }).length).toBeGreaterThan(0);
    expect(
      screen.queryByText("This package is pinned at the currently selected installed version."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Latest 0.1.7")).not.toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Version" }));

    expect(screen.getAllByText("Latest")).toHaveLength(2);
    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });
});
