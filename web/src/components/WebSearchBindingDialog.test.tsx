import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/utils/api", () => ({
  createAgentWebSearchBinding: vi.fn(),
  testAgentWebSearchBinding: vi.fn(),
  testWebSearchProviderDraft: vi.fn(),
  updateAgentWebSearchBinding: vi.fn(),
}));

import { testWebSearchProviderDraft } from "@/utils/api";

import WebSearchBindingDialog from "./WebSearchBindingDialog";

describe("WebSearchBindingDialog", () => {
  it("tests an unsaved provider draft before saving", async () => {
    const user = userEvent.setup();
    vi.mocked(testWebSearchProviderDraft).mockResolvedValue({
      result: {
        ok: true,
        status: "healthy",
        message: "Tavily credentials verified successfully.",
      },
    });

    render(
      <WebSearchBindingDialog
        open={true}
        onOpenChange={vi.fn()}
        agentId={3}
        configuredProviderKeys={[]}
        catalog={[
          {
            manifest: {
              key: "tavily",
              name: "Tavily",
              description: "General-purpose search",
              docs_url: "https://docs.tavily.com",
              visibility: "builtin",
              status: "active",
              auth_schema: [
                {
                  key: "api_key",
                  label: "API Key",
                  type: "secret",
                  required: true,
                },
              ],
              config_schema: [],
              setup_steps: ["Paste the key", "Test it", "Save it"],
              supported_parameters: ["query", "max_results"],
            },
          },
        ]}
        initialBinding={null}
        onSaved={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("API Key *"), "tvly-demo");
    await user.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() => {
      expect(testWebSearchProviderDraft).toHaveBeenCalledWith("tavily", {
        auth_config: { api_key: "tvly-demo" },
        runtime_config: {},
      });
    });

    expect(screen.getByText("Tavily credentials verified successfully.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });
});
