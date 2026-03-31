import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/utils/api", () => ({
  fetchTaskAttachmentBlob: vi.fn(() =>
    new Blob(["# Report\n\nHello attachment"], { type: "text/markdown" }),
  ),
}));

vi.mock("@/desktop/desktop-adapter", () => ({
  isDesktop: false,
  saveBlobWithNativeDialog: vi.fn(),
}));

import { AssistantAttachmentList } from "./AssistantAttachmentList";

describe("AssistantAttachmentList", () => {
  beforeEach(() => {
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:attachment-preview"),
      revokeObjectURL: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens a draggable markdown preview for assistant artifacts", async () => {
    const user = userEvent.setup();

    render(
      <AssistantAttachmentList
        attachments={[
          {
            attachmentId: "attachment-1",
            displayName: "report.md",
            originalName: "report.md",
            mimeType: "text/markdown",
            extension: "md",
            sizeBytes: 2048,
            renderKind: "markdown",
            workspaceRelativePath: "outputs/report.md",
            createdAt: "2026-03-30T12:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByText("Markdown · 2.0KB")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open report.md" }));

    expect(screen.getAllByText("report.md").length).toBeGreaterThan(0);
    expect(screen.queryByText("outputs/report.md")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Hello attachment")).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Download report.md" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Download")).not.toBeInTheDocument();
  });

  it("renders download-only artifacts as static raw cards", () => {
    render(
      <AssistantAttachmentList
        attachments={[
          {
            attachmentId: "attachment-2",
            displayName: "archive.bin",
            originalName: "archive.bin",
            mimeType: "application/octet-stream",
            extension: "bin",
            sizeBytes: 920,
            renderKind: "download",
            workspaceRelativePath: "outputs/archive.bin",
            createdAt: "2026-03-30T12:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByText("archive.bin")).toBeInTheDocument();
    expect(screen.getByText("Raw · 920B")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Open archive.bin" }),
    ).not.toBeInTheDocument();
  });
});
