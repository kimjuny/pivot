import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock("@/utils/api", () => ({
  getChannels: vi.fn(),
}));

import { getChannels } from "@/utils/api";

import ChannelsPage from "./ChannelsPage";

describe("ChannelsPage", () => {
  it("renders built-in and extension provider metadata", async () => {
    vi.mocked(getChannels).mockResolvedValue([
      {
        manifest: {
          key: "telegram",
          name: "Telegram",
          description: "Built-in polling provider",
          icon: "send",
          docs_url: "https://example.com/telegram",
          transport_mode: "polling",
          visibility: "builtin",
          status: "active",
          capabilities: ["receive_text"],
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
        },
      },
      {
        manifest: {
          key: "acme_chat",
          name: "ACME Chat",
          description: "Extension-backed channel provider",
          icon: "message-square",
          docs_url: "https://example.com/acme-chat",
          transport_mode: "webhook",
          visibility: "extension",
          status: "active",
          extension_name: "@acme/providers",
          extension_version: "1.0.0",
          extension_display_name: "ACME Providers",
          capabilities: ["send_text"],
          auth_schema: [],
          config_schema: [],
          setup_steps: [],
        },
      },
    ]);

    render(<ChannelsPage />);

    await waitFor(() => {
      expect(screen.getByText("Telegram")).toBeInTheDocument();
      expect(screen.getByText("ACME Chat")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Built-in").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Extension").length).toBeGreaterThan(0);
    expect(screen.getByText("Package: ACME Providers@1.0.0")).toBeInTheDocument();
  });
});
