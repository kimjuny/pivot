import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RecursionCard } from "./RecursionCard";

import type { RecursionRecord } from "../types";

/**
 * Builds a minimal recursion record so each test can override only the stage
 * that matters for the current interaction.
 */
function buildRecursion(
  overrides: Partial<RecursionRecord> = {},
): RecursionRecord {
  return {
    uid: "recursion-1",
    iteration: 0,
    trace_id: "trace-1",
    events: [],
    status: "running",
    startTime: "2026-03-24T00:00:00.000Z",
    ...overrides,
  };
}

describe("RecursionCard", () => {
  it("shows a blinking Thinking label while reasoning tokens are still streaming", () => {
    render(
      <RecursionCard
        messageId="message-1"
        recursion={buildRecursion({
          thinking: "Need to inspect the repo state.",
          events: [
            {
              type: "reasoning",
              task_id: "task-1",
              trace_id: "trace-1",
              iteration: 0,
              timestamp: "2026-03-24T00:00:00.000Z",
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });

  it("switches to the latest stable running label after visible output starts", () => {
    render(
      <RecursionCard
        messageId="message-2"
        recursion={buildRecursion({
          thinking: "Need to inspect the repo state.",
          observe: "Repository structure loaded.",
          events: [
            {
              type: "observe",
              task_id: "task-2",
              trace_id: "trace-2",
              iteration: 0,
              timestamp: "2026-03-24T00:00:01.000Z",
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("Repository structure loaded.")).toBeInTheDocument();
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });

  it("keeps the iteration title visible while tool execution is waiting on results", () => {
    render(
      <RecursionCard
        messageId="message-3"
        recursion={buildRecursion({
          summary: "Loaded project files",
          events: [
            {
              type: "tool_call",
              task_id: "task-3",
              trace_id: "trace-3",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-1",
                    name: "read_files",
                    arguments: { path: "web/src/pages/chat" },
                  },
                ],
                tool_results: [],
              },
            },
          ],
        })}
        isExpanded={true}
        onToggle={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /Loaded project files/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Waiting for tool result...")).toBeInTheDocument();
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });
});
