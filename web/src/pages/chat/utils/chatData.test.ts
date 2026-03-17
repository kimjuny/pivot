import { describe, expect, it } from "vitest";

import { buildMessagesFromHistory, getUniqueClipboardFiles } from "./chatData";

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

describe("buildMessagesFromHistory", () => {
  it("preserves running recursion state so reconnecting observers can continue applying live events", () => {
    const messages = buildMessagesFromHistory([
      {
        task_id: "task-1",
        user_message: "Keep going",
        agent_answer: null,
        status: "running",
        total_tokens: 0,
        current_plan: [],
        recursions: [
          {
            iteration: 0,
            trace_id: "trace-1",
            observe: null,
            thinking: "thinking",
            thought: null,
            abstract: null,
            summary: null,
            action_type: null,
            action_output: null,
            tool_call_results: null,
            status: "running",
            error_log: null,
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
            cached_input_tokens: 0,
            created_at: "2026-03-16T00:00:00.000Z",
            updated_at: "2026-03-16T00:00:01.000Z",
          },
        ],
        created_at: "2026-03-16T00:00:00.000Z",
        updated_at: "2026-03-16T00:00:01.000Z",
      },
    ]);

    const assistantMessage = messages.find((message) => message.role === "assistant");
    expect(assistantMessage?.status).toBe("running");
    expect(assistantMessage?.recursions?.[0]?.status).toBe("running");
    expect(assistantMessage?.recursions?.[0]?.endTime).toBeUndefined();
  });

  it("maps cancelled tasks to stopped UI state instead of error state", () => {
    const messages = buildMessagesFromHistory([
      {
        task_id: "task-2",
        user_message: "Stop here",
        agent_answer: null,
        status: "cancelled",
        total_tokens: 0,
        current_plan: [],
        recursions: [
          {
            iteration: 0,
            trace_id: "trace-2",
            observe: null,
            thinking: "thinking",
            thought: null,
            abstract: null,
            summary: null,
            action_type: null,
            action_output: null,
            tool_call_results: null,
            status: "running",
            error_log: null,
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: 0,
            cached_input_tokens: 0,
            created_at: "2026-03-16T00:00:00.000Z",
            updated_at: "2026-03-16T00:00:01.000Z",
          },
        ],
        created_at: "2026-03-16T00:00:00.000Z",
        updated_at: "2026-03-16T00:00:03.000Z",
      },
    ]);

    const assistantMessage = messages.find((message) => message.role === "assistant");
    expect(assistantMessage?.status).toBe("stopped");
    expect(assistantMessage?.recursions?.[0]?.status).toBe("stopped");
    expect(assistantMessage?.recursions?.[0]?.endTime).toBe(
      "2026-03-16T00:00:03.000Z",
    );
  });
});
