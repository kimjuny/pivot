import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/utils/api", () => ({
  createAgentChannel: vi.fn(),
  pollAgentChannel: vi.fn(),
  testAgentChannel: vi.fn(),
  testChannelDraft: vi.fn(),
  updateAgentChannel: vi.fn(),
}));

import { testChannelDraft } from "@/utils/api";

import ChannelBindingDialog from "./ChannelBindingDialog";

describe("ChannelBindingDialog", () => {
  it("tests an unsaved binding draft before saving", async () => {
    const user = userEvent.setup();
    vi.mocked(testChannelDraft).mockResolvedValue({
      result: {
        ok: true,
        status: "healthy",
        message: "Draft credentials look good.",
        endpoint_infos: [],
      },
    });

    render(
      <MemoryRouter>
        <ChannelBindingDialog
          open={true}
          onOpenChange={vi.fn()}
          agentId={3}
          catalog={[
            {
              manifest: {
                key: "telegram",
                name: "Telegram",
                description: "Telegram bot binding",
                icon: "send",
                docs_url: "https://example.com/docs",
                transport_mode: "polling",
                visibility: "public",
                status: "active",
                capabilities: ["receive_text"],
                auth_schema: [
                  {
                    key: "bot_token",
                    label: "Bot Token",
                    type: "secret",
                    required: true,
                  },
                ],
                config_schema: [],
                setup_steps: ["Paste the token", "Test the connection", "Save it"],
              },
            },
          ]}
          initialBinding={null}
          onSaved={vi.fn()}
        />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText("Bot Token *"), "123:abc");
    await user.click(screen.getByRole("button", { name: "Test Connection" }));

    await waitFor(() => {
      expect(testChannelDraft).toHaveBeenCalledWith("telegram", {
        auth_config: { bot_token: "123:abc" },
        runtime_config: {},
      });
    });

    expect(screen.getByText("Draft credentials look good.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });
});
