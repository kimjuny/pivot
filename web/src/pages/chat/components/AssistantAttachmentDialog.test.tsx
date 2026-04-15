import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProviderContext } from "@/lib/use-theme";
import { fetchTaskAttachmentBlob } from "@/utils/api";

vi.mock("@/utils/api", () => ({
  fetchTaskAttachmentBlob: vi.fn(),
}));

vi.mock("@/desktop/desktop-adapter", () => ({
  isDesktop: false,
  saveBlobWithNativeDialog: vi.fn(),
}));

vi.mock("@/components/DraggableDialog", () => ({
  default: ({
    open,
    title,
    headerAction,
    children,
  }: {
    open: boolean;
    title: string;
    headerAction?: React.ReactNode;
    children: React.ReactNode;
  }) =>
    open ? (
      <div>
        <div>{title}</div>
        {headerAction}
        {children}
      </div>
    ) : null,
}));

vi.mock("@monaco-editor/react", () => ({
  default: ({
    language,
    value,
  }: {
    language: string;
    value: string;
  }) => (
    <div data-testid="monaco-editor" data-language={language}>
      {value}
    </div>
  ),
}));

import { AssistantAttachmentDialog } from "./AssistantAttachmentDialog";

function renderWithTheme(node: React.ReactNode) {
  return render(
    <ThemeProviderContext.Provider
      value={{ theme: "light", setTheme: vi.fn() }}
    >
      {node}
    </ThemeProviderContext.Provider>,
  );
}

describe("AssistantAttachmentDialog", () => {
  beforeEach(() => {
    vi.mocked(fetchTaskAttachmentBlob).mockReset();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:attachment-preview"),
      revokeObjectURL: vi.fn(),
    });
  });

  it("renders text attachments in a read-only Monaco viewer", async () => {
    vi.mocked(fetchTaskAttachmentBlob).mockResolvedValue(
      new Blob(['console.log("pivot");'], { type: "text/javascript" }),
    );

    renderWithTheme(
      <AssistantAttachmentDialog
        attachment={{
          attachmentId: "attachment-text",
          displayName: "script.js",
          originalName: "script.js",
          mimeType: "text/javascript",
          extension: "js",
          sizeBytes: 22,
          renderKind: "text",
          workspaceRelativePath: "outputs/script.js",
          createdAt: "2026-03-31T00:00:00Z",
        }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("monaco-editor")).toBeInTheDocument();
    });
    expect(screen.getByTestId("monaco-editor")).toHaveAttribute(
      "data-language",
      "javascript",
    );
    expect(screen.getByText('console.log("pivot");')).toBeInTheDocument();
  });

  it("keeps markdown attachments on the markdown renderer path", async () => {
    vi.mocked(fetchTaskAttachmentBlob).mockResolvedValue(
      new Blob(["# Heading\n\nBody copy"], { type: "text/markdown" }),
    );

    renderWithTheme(
      <AssistantAttachmentDialog
        attachment={{
          attachmentId: "attachment-markdown",
          displayName: "report.md",
          originalName: "report.md",
          mimeType: "text/markdown",
          extension: "md",
          sizeBytes: 22,
          renderKind: "markdown",
          workspaceRelativePath: "outputs/report.md",
          createdAt: "2026-03-31T00:00:00Z",
        }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Heading", level: 1 }),
      ).toBeInTheDocument();
    });
    expect(screen.queryByTestId("monaco-editor")).not.toBeInTheDocument();
    expect(screen.getByText("Body copy")).toBeInTheDocument();
  });

  it("shows an unsupported preview state for download-only attachments", async () => {
    vi.mocked(fetchTaskAttachmentBlob).mockResolvedValue(
      new Blob(["raw bytes"], { type: "application/octet-stream" }),
    );

    renderWithTheme(
      <AssistantAttachmentDialog
        attachment={{
          attachmentId: "attachment-raw",
          displayName: "archive.bin",
          originalName: "archive.bin",
          mimeType: "application/octet-stream",
          extension: "bin",
          sizeBytes: 9,
          renderKind: "download",
          workspaceRelativePath: "outputs/archive.bin",
          createdAt: "2026-03-31T00:00:00Z",
        }}
        open
        onOpenChange={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Unsupported file type")).toBeInTheDocument();
    });
    expect(
      screen.getByText(/cannot be previewed inline yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download archive.bin" }),
    ).toBeInTheDocument();
  });
});
