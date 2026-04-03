import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock("@/utils/api", () => ({
  getWebSearchProviders: vi.fn(),
}));

import { getWebSearchProviders } from "@/utils/api";

import WebSearchProvidersPage from "./WebSearchProvidersPage";

describe("WebSearchProvidersPage", () => {
  it("renders installed provider metadata for built-in and extension sources", async () => {
    vi.mocked(getWebSearchProviders).mockResolvedValue([
      {
        manifest: {
          key: "tavily",
          name: "Tavily",
          description: "Built-in search provider",
          docs_url: "https://example.com/tavily",
          logo_url: null,
          visibility: "builtin",
          status: "active",
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
          supported_parameters: ["query", "max_results"],
        },
      },
      {
        manifest: {
          key: "acme_search",
          name: "ACME Search",
          description: "Extension-backed search provider",
          docs_url: "https://example.com/acme-search",
          logo_url: null,
          visibility: "extension",
          status: "active",
          extension_name: "@acme/providers",
          extension_version: "1.0.0",
          extension_display_name: "ACME Providers",
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
          supported_parameters: ["query"],
        },
      },
    ]);

    render(<WebSearchProvidersPage />);

    await waitFor(() => {
      expect(screen.getByText("Tavily")).toBeInTheDocument();
      expect(screen.getByText("ACME Search")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Built-in").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Extension").length).toBeGreaterThan(0);
    expect(screen.getByText("Package: ACME Providers@1.0.0")).toBeInTheDocument();
  });
});
