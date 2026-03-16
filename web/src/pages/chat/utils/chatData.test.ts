import { describe, expect, it } from "vitest";

import { getUniqueClipboardFiles } from "./chatData";

interface ClipboardDataStubOptions {
  itemFiles?: File[];
  listFiles?: File[];
}

function createClipboardDataStub({
  itemFiles = [],
  listFiles = [],
}: ClipboardDataStubOptions): DataTransfer {
  return {
    items: itemFiles.map(
      (file) =>
        ({
          kind: "file",
          getAsFile: () => file,
        }) as DataTransferItem,
    ),
    files: listFiles as unknown as FileList,
  } as unknown as DataTransfer;
}

describe("getUniqueClipboardFiles", () => {
  it("deduplicates blank-name screenshot blobs surfaced by both clipboard collections", () => {
    const screenshot = new File(["pixels"], "", {
      type: "image/png",
      lastModified: 123,
    });

    const result = getUniqueClipboardFiles(
      createClipboardDataStub({
        itemFiles: [screenshot],
        listFiles: [screenshot],
      }),
    );

    expect(result).toHaveLength(1);
    expect(result[0].name).toMatch(/^clipboard-\d+-0\.png$/);
  });

  it("falls back to the file list when clipboard items are unavailable", () => {
    const copiedFile = new File(["doc"], "notes.md", {
      type: "text/markdown",
      lastModified: 456,
    });

    const result = getUniqueClipboardFiles(
      createClipboardDataStub({
        listFiles: [copiedFile],
      }),
    );

    expect(result).toEqual([copiedFile]);
  });
});
