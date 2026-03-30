import { afterEach, describe, expect, it, vi } from "vitest";

const invoke = vi.fn();
const isTauri = vi.fn();

vi.mock("@tauri-apps/api/core", () => ({
  invoke,
  isTauri,
}));

describe("desktop attachment saving", () => {
  afterEach(() => {
    invoke.mockReset();
    isTauri.mockReset();
    vi.restoreAllMocks();
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it("writes the chosen file when running in the desktop shell", async () => {
    isTauri.mockReturnValue(true);
    invoke
      .mockResolvedValueOnce("/tmp/report.md")
      .mockResolvedValueOnce(undefined);

    const { saveBlobWithNativeDialog } = await import("./desktop-adapter");
    const result = await saveBlobWithNativeDialog({
      blob: new Blob(["hello"], { type: "text/markdown" }),
      suggestedName: "report.md",
      extension: "md",
      formatLabel: "Markdown",
    });

    expect(result).toBe("/tmp/report.md");
    expect(invoke).toHaveBeenNthCalledWith(
      1,
      "plugin:dialog|save",
      expect.objectContaining({
        options: {
          defaultPath: "report.md",
          canCreateDirectories: true,
          filters: [{ name: "Markdown", extensions: ["md"] }],
        },
      }),
    );
    expect(invoke).toHaveBeenNthCalledWith(
      2,
      "plugin:fs|write_file",
      expect.any(Uint8Array),
      {
        headers: {
          path: encodeURIComponent("/tmp/report.md"),
          options: undefined,
        },
      },
    );
  });

  it("returns null when the desktop save dialog is cancelled", async () => {
    isTauri.mockReturnValue(true);
    invoke.mockResolvedValueOnce(null);

    const { saveBlobWithNativeDialog } = await import("./desktop-adapter");
    const result = await saveBlobWithNativeDialog({
      blob: new Blob(["hello"]),
      suggestedName: "report.md",
    });

    expect(result).toBeNull();
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("does not attempt a native save outside the desktop shell", async () => {
    isTauri.mockReturnValue(false);

    const { saveBlobWithNativeDialog } = await import("./desktop-adapter");
    const result = await saveBlobWithNativeDialog({
      blob: new Blob(["hello"]),
      suggestedName: "report.md",
    });

    expect(result).toBeNull();
    expect(invoke).not.toHaveBeenCalled();
  });
});
