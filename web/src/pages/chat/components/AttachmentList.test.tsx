import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

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

    await user.click(
      screen.getByRole("button", { name: "Preview diagram.png" }),
    );

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

    await user.click(
      screen.getByRole("button", { name: "Preview diagram.png" }),
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getAllByAltText("diagram.png")).toHaveLength(2);
  });
});
