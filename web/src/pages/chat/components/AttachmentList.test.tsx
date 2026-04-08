import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/utils/api", () => ({
  fetchChatFileBlob: vi.fn(() =>
    Promise.resolve(new Blob(["# Uploaded report"], { type: "text/markdown" })),
  ),
  fetchWorkspaceTextFile: vi.fn(() =>
    Promise.resolve({
      session_id: "session-1",
      workspace_relative_path: ".uploads/file-2/report.md",
      content: "# Uploaded report",
    }),
  ),
  updateWorkspaceTextFile: vi.fn(() =>
    Promise.resolve({
      session_id: "session-1",
      workspace_relative_path: ".uploads/file-2/report.md",
      content: "# Uploaded report",
    }),
  ),
}));

import { AttachmentList } from "./AttachmentList";

const imageAttachment = {
  fileId: "file-1",
  kind: "image" as const,
  originalName: "diagram.png",
  mimeType: "image/png",
  format: "png",
  extension: "png",
  width: 320,
  height: 240,
  sizeBytes: 1234,
  previewUrl: "blob:diagram-preview",
};

describe("AttachmentList", () => {
  it("opens an image preview dialog from message history thumbnails", async () => {
    const user = userEvent.setup();

    render(<AttachmentList attachments={[imageAttachment]} />);

    expect(screen.getAllByAltText("diagram.png")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Open diagram.png" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByAltText("diagram.png")).toHaveLength(2);
  });

  it("opens an image preview dialog from composer thumbnails", async () => {
    const user = userEvent.setup();
    const composerAttachment = {
      ...imageAttachment,
      clientId: "pending-1",
      source: "local" as const,
      status: "ready" as const,
    };

    render(<AttachmentList attachments={[composerAttachment]} variant="composer" />);

    await user.click(screen.getByRole("button", { name: "Preview diagram.png" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByAltText("diagram.png")).toHaveLength(2);
  });

  it("opens attached documents against the current workspace file path", async () => {
    const user = userEvent.setup();
    const documentAttachment = {
      fileId: "file-2",
      kind: "document" as const,
      originalName: "report.md",
      mimeType: "text/markdown",
      format: "md",
      extension: "md",
      width: 0,
      height: 0,
      sizeBytes: 512,
      workspaceRelativePath: ".uploads/file-2/report.md",
    };

    render(
      <AttachmentList
        attachments={[documentAttachment]}
        currentSessionId="session-1"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Open report.md" }));

    expect(screen.getByText("/workspace/.uploads/file-2/report.md")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Uploaded report")).toBeInTheDocument();
    });
  });
});
