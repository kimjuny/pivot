import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProviderContext } from "@/lib/use-theme";
import {
  fetchWorkspaceTextFile,
  updateWorkspaceTextFile,
} from "@/utils/api";

vi.mock("@/utils/api", () => ({
  fetchChatFileBlob: vi.fn(),
  fetchWorkspaceTextFile: vi.fn(),
  updateWorkspaceTextFile: vi.fn(),
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

import { AttachmentPreviewDialog } from "./AttachmentPreviewDialog";

function renderWithTheme(node: React.ReactNode) {
  return render(
    <ThemeProviderContext.Provider
      value={{ theme: "light", setTheme: vi.fn() }}
    >
      {node}
    </ThemeProviderContext.Provider>,
  );
}

describe("AttachmentPreviewDialog", () => {
  beforeEach(() => {
    vi.mocked(fetchWorkspaceTextFile).mockReset();
    vi.mocked(updateWorkspaceTextFile).mockReset();
  });

  it("edits and saves attached workspace markdown files", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchWorkspaceTextFile).mockResolvedValue({
      session_id: "session-1",
      workspace_relative_path: ".uploads/file-2/report.md",
      content: "# Uploaded report",
    });
    vi.mocked(updateWorkspaceTextFile).mockResolvedValue({
      session_id: "session-1",
      workspace_relative_path: ".uploads/file-2/report.md",
      content: "# Uploaded report",
    });

    renderWithTheme(
      <AttachmentPreviewDialog
        attachment={{
          fileId: "file-2",
          kind: "document",
          originalName: "report.md",
          mimeType: "text/markdown",
          format: "md",
          extension: "md",
          width: 0,
          height: 0,
          sizeBytes: 512,
          workspaceRelativePath: ".uploads/file-2/report.md",
        }}
        currentSessionId="session-1"
        open
        onOpenChange={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByTestId("monaco-editor")).toHaveAttribute(
      "data-language",
      "markdown",
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(updateWorkspaceTextFile).toHaveBeenCalledWith(
        "session-1",
        ".uploads/file-2/report.md",
        "# Uploaded report",
      );
    });
  });
});
