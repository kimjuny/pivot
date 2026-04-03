import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

vi.mock("@/utils/api", () => ({
  getExtensionHookExecutions: vi.fn(),
  replayExtensionHookExecution: vi.fn(),
}));

import {
  getExtensionHookExecutions,
  replayExtensionHookExecution,
} from "@/utils/api";

import ExtensionHookReplayPanel from "./ExtensionHookReplayPanel";

describe("ExtensionHookReplayPanel", () => {
  it("loads package-scoped executions and replays one historical hook", async () => {
    vi.mocked(getExtensionHookExecutions).mockResolvedValue([
      {
        id: 101,
        session_id: "session-1",
        task_id: "task-1",
        trace_id: null,
        iteration: 0,
        agent_id: 7,
        release_id: null,
        extension_package_id: "@acme/memory",
        extension_version: "1.0.0",
        hook_event: "task.completed",
        hook_callable: "persist_memory",
        status: "succeeded",
        hook_context: {
          task_id: "task-1",
          execution_mode: "live",
        },
        effects: [{ type: "emit_event" }],
        error: null,
        started_at: "2026-04-02T00:00:00Z",
        finished_at: "2026-04-02T00:00:00Z",
        duration_ms: 14,
      },
    ]);
    vi.mocked(replayExtensionHookExecution).mockResolvedValue({
      execution_id: 101,
      extension_package_id: "@acme/memory",
      extension_version: "1.0.0",
      hook_event: "task.completed",
      hook_callable: "persist_memory",
      status: "succeeded",
      effects: [],
      error: null,
      replayed_at: "2026-04-02T00:01:00Z",
    });

    render(<ExtensionHookReplayPanel packageId="@acme/memory" />);

    await waitFor(() => {
      expect(getExtensionHookExecutions).toHaveBeenCalledWith({
        extensionPackageId: "@acme/memory",
        hookEvent: undefined,
        limit: 25,
        taskId: undefined,
      });
      expect(screen.getByText("task.completed")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Inspect" }));

    await waitFor(() => {
      expect(screen.getByText("Hook Execution Details")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Replay Hook" }));

    await waitFor(() => {
      expect(replayExtensionHookExecution).toHaveBeenCalledWith(101);
      expect(screen.getByText("Replay Result")).toBeInTheDocument();
    });
  });
});
