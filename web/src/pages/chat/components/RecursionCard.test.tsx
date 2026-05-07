import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  it("shows the rotating thinking ticker while reasoning tokens are still streaming", () => {
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

    expect(screen.getByTestId("thinking-word-ticker")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Toggle thinking details" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });

  it("replaces the fallback iteration title with the ticker until stable output exists", () => {
    render(
      <RecursionCard
        messageId="message-iteration"
        recursion={buildRecursion({
          iteration: 2,
          events: [
            {
              type: "tool_call",
              task_id: "task-iteration",
              trace_id: "trace-iteration",
              iteration: 2,
              timestamp: "2026-03-24T00:00:00.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-iteration-1",
                    name: "read_files",
                    arguments: { path: "server/app" },
                  },
                ],
                tool_results: [],
                pending_arguments: true,
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByTestId("thinking-word-ticker")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Preparing read_files/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Iteration 3")).not.toBeInTheDocument();
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

    expect(
      screen.getAllByText("Repository structure loaded.").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });

  it("collapses completed thinking by default while keeping it available", () => {
    render(
      <RecursionCard
        messageId="message-thinking-complete"
        recursion={buildRecursion({
          thinking: "I compared the available implementation paths.",
          summary: "Picked the smaller frontend-only change.",
          status: "completed",
          endTime: "2026-03-24T00:00:03.000Z",
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Toggle thinking details" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByText("Picked the smaller frontend-only change."),
    ).toBeInTheDocument();
  });

  it("calls the summary toggle and shows execution details when expanded", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();

    const { rerender } = render(
      <RecursionCard
        messageId="message-details"
        recursion={buildRecursion({
          summary: "Inspected the chat rendering flow.",
          observe: "RecursionCard owns the visible iteration row.",
          reason: "The shell component is not the right edit surface.",
          action: "CALL_TOOL",
          status: "completed",
          endTime: "2026-03-24T00:00:04.000Z",
        })}
        isExpanded={false}
        onToggle={onToggle}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: /Inspected the chat rendering flow/i,
      }),
    );
    expect(onToggle).toHaveBeenCalledWith("message-details", "recursion-1");

    rerender(
      <RecursionCard
        messageId="message-details"
        recursion={buildRecursion({
          summary: "Inspected the chat rendering flow.",
          observe: "RecursionCard owns the visible iteration row.",
          reason: "The shell component is not the right edit surface.",
          action: "CALL_TOOL",
          status: "completed",
          endTime: "2026-03-24T00:00:04.000Z",
        })}
        isExpanded={true}
        onToggle={onToggle}
      />,
    );

    expect(screen.getByText("Observe")).toBeInTheDocument();
    expect(screen.getByText("Reason")).toBeInTheDocument();
    expect(screen.getByText("Action")).toBeInTheDocument();
  });

  it("keeps the summary visible while tool execution is waiting on results", () => {
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
    expect(
      screen.getByRole("button", { name: /Running read_files/i }),
    ).toHaveTextContent("Running");
    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
  });

  it("renders live write and edit payload previews with filename counters", async () => {
    const user = userEvent.setup();

    render(
      <RecursionCard
        messageId="message-live-tools"
        recursion={buildRecursion({
          summary: "Updating files",
          events: [
            {
              type: "tool_call",
              task_id: "task-live-tools",
              trace_id: "trace-live-tools",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-write",
                    name: "write_file",
                    arguments: {
                      path: { $payload_ref: "write_path" },
                      content: { $payload_ref: "write_content" },
                    },
                  },
                  {
                    id: "call-edit",
                    name: "edit_file",
                    arguments: {
                      path: { $payload_ref: "edit_path" },
                      diff: { $payload_ref: "edit_diff" },
                    },
                  },
                ],
                tool_results: [],
              },
            },
            {
              type: "tool_payload_delta",
              task_id: "task-live-tools",
              trace_id: "trace-live-tools",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.100Z",
              data: {
                tool_call_id: "call-write",
                tool_name: "write_file",
                argument_name: "path",
                payload_name: "write_path",
                delta: "web/src/pages/chat/index.tsx",
                is_final: true,
              },
            },
            {
              type: "tool_payload_delta",
              task_id: "task-live-tools",
              trace_id: "trace-live-tools",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.200Z",
              data: {
                tool_call_id: "call-write",
                tool_name: "write_file",
                argument_name: "content",
                payload_name: "write_content",
                delta: "alpha\nbeta\ngamma",
                is_final: false,
              },
            },
            {
              type: "tool_payload_delta",
              task_id: "task-live-tools",
              trace_id: "trace-live-tools",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.300Z",
              data: {
                tool_call_id: "call-edit",
                tool_name: "edit_file",
                argument_name: "path",
                payload_name: "edit_path",
                delta: "server/app/demo.py",
                is_final: true,
              },
            },
            {
              type: "tool_payload_delta",
              task_id: "task-live-tools",
              trace_id: "trace-live-tools",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.400Z",
              data: {
                tool_call_id: "call-edit",
                tool_name: "edit_file",
                argument_name: "diff",
                payload_name: "edit_diff",
                delta: "@@ -1,2 +1,2 @@\n-old\n+new\n context",
                is_final: false,
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    const toolGroup = screen.getByRole("button", { name: /2 tools used/i });
    await user.click(toolGroup);

    const writeTool = screen.getByRole("button", { name: /Running write_file/i });
    expect(writeTool).toHaveTextContent("index.tsx");
    expect(writeTool).toHaveTextContent("+3");

    const editTool = screen.getByRole("button", { name: /Running edit_file/i });
    expect(editTool).toHaveTextContent("demo.py");
    expect(editTool).toHaveTextContent("+1");
    expect(editTool).toHaveTextContent("-1");

    await user.click(writeTool);
    expect(screen.queryByText("Arguments:")).not.toBeInTheDocument();
    expect(screen.getByText("Preview:")).toBeInTheDocument();
    expect(screen.getByText("gamma")).toBeInTheDocument();

    await user.click(editTool);
    expect(screen.getByText("Diff:")).toBeInTheDocument();
    expect(screen.getByText("+new")).toBeInTheDocument();
    expect(screen.getByText("-old")).toBeInTheDocument();
  });

  it("labels truncated write_file previews with real source line numbers", async () => {
    const user = userEvent.setup();
    const content = Array.from(
      { length: 430 },
      (_, index) => `line-${index + 1}`,
    ).join("\n");

    render(
      <RecursionCard
        messageId="message-long-write"
        recursion={buildRecursion({
          summary: "Writing a large file",
          events: [
            {
              type: "tool_call",
              task_id: "task-long-write",
              trace_id: "trace-long-write",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-write-long",
                    name: "write_file",
                    arguments: {
                      path: "web/src/index.css",
                      content,
                    },
                  },
                ],
                tool_results: [
                  {
                    tool_call_id: "call-write-long",
                    tool_name: "write_file",
                    status: "success",
                    result: "ok",
                  },
                ],
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Ran write_file/i }));

    expect(
      screen.getByText((_, element) =>
        element?.textContent === "Showing lines 11-430 of 430",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("11")).toBeInTheDocument();
    expect(screen.getByText("line-11")).toBeInTheDocument();
    expect(screen.queryByText("line-1")).not.toBeInTheDocument();
  });

  it("renders edit_file previews with original old-file line numbers", async () => {
    const user = userEvent.setup();

    render(
      <RecursionCard
        messageId="message-edit-lines"
        recursion={buildRecursion({
          summary: "Editing a file",
          events: [
            {
              type: "tool_call",
              task_id: "task-edit-lines",
              trace_id: "trace-edit-lines",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-edit-lines",
                    name: "edit_file",
                    arguments: {
                      path: "server/app/demo.py",
                      diff: "@@ -120,3 +120,4 @@\n old line\n-old value\n+new value\n+extra value\n context line",
                    },
                  },
                ],
                tool_results: [
                  {
                    tool_call_id: "call-edit-lines",
                    tool_name: "edit_file",
                    status: "success",
                    result: "ok",
                  },
                ],
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Ran edit_file/i }));

    expect(screen.getByText(/old line/)).toBeInTheDocument();
    expect(screen.getByText(/-old value/)).toBeInTheDocument();
    expect(screen.getByText(/context line/)).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("121")).toBeInTheDocument();
    expect(screen.getByText("122")).toBeInTheDocument();
    expect(screen.queryByText(/^1$/)).not.toBeInTheDocument();
  });

  it("renders tool executions as one-line records with terminal details", async () => {
    const user = userEvent.setup();

    render(
      <RecursionCard
        messageId="message-tools"
        recursion={buildRecursion({
          summary: "Ran file checks",
          status: "completed",
          endTime: "2026-03-24T00:00:05.000Z",
          events: [
            {
              type: "tool_call",
              task_id: "task-tools",
              trace_id: "trace-tools",
              iteration: 0,
              timestamp: "2026-03-24T00:00:05.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-success",
                    name: "read_file",
                    arguments: { path: "web/src/pages/chat" },
                  },
                  {
                    id: "call-failed",
                    name: "run_lint",
                    arguments: { target: "web" },
                  },
                  {
                    id: "call-bash",
                    name: "run_bash",
                    arguments: {
                      command:
                        "python3 /workspace/skills/ppt-master/scripts/total_md_split.py projects/shbank_pension_ppt169_20260426",
                    },
                  },
                  {
                    id: "call-search",
                    name: "search",
                    arguments: {
                      path: "server/app",
                      query: "React recursion tool rendering implementation",
                    },
                  },
                ],
                tool_results: [
                  {
                    tool_call_id: "call-success",
                    name: "read_file",
                    result: "ok",
                    success: true,
                  },
                  {
                    tool_call_id: "call-failed",
                    name: "run_lint",
                    error: "lint failed",
                    success: false,
                  },
                  {
                    tool_call_id: "call-bash",
                    name: "run_bash",
                    result: { ok: true, exit_code: 0 },
                    success: true,
                  },
                  {
                    tool_call_id: "call-search",
                    name: "search",
                    result: ["RecursionCard.tsx"],
                    success: true,
                  },
                ],
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.queryByText("TOOL EXECUTION")).not.toBeInTheDocument();

    const toolGroup = screen.getByRole("button", { name: /4 tools used/i });
    expect(toolGroup).toHaveTextContent("Failed");
    expect(toolGroup).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByRole("button", { name: /Ran read_file/i }),
    ).not.toBeInTheDocument();

    await user.click(toolGroup);
    expect(toolGroup).toHaveAttribute("aria-expanded", "true");

    const successfulTool = screen.getByRole("button", {
      name: /Ran read_file/i,
    });
    expect(successfulTool).toHaveTextContent("web/src/pages/chat");
    expect(successfulTool).not.toHaveTextContent("Done");
    expect(successfulTool).toHaveAttribute("aria-expanded", "false");

    const failedTool = screen.getByRole("button", { name: /Ran run_lint/i });
    expect(failedTool).not.toHaveTextContent('{"target":"web"}');
    expect(failedTool).toHaveTextContent("Failed");
    expect(failedTool).toHaveAttribute("aria-expanded", "false");

    await user.click(failedTool);
    expect(failedTool).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/lint failed/)).toBeInTheDocument();

    const bashTool = screen.getByRole("button", { name: /Ran run_bash/i });
    expect(bashTool).toHaveTextContent(
      "python3 /workspace/skills/ppt-master/scripts/total_md_split.py projects/shbank_pension_ppt169_20260426",
    );
    expect(bashTool).not.toHaveTextContent("Done");

    const searchTool = screen.getByRole("button", { name: /Ran search/i });
    expect(searchTool).toHaveTextContent("server/app");
    expect(searchTool).toHaveTextContent(
      "React recursion tool rendering implementation",
    );
    expect(searchTool).not.toHaveTextContent("Done");

    await user.click(successfulTool);
    expect(
      screen.getAllByText("Arguments:").length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("Result:").length).toBeGreaterThan(0);
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("keeps multi-tool groups expanded while any tool is still running", async () => {
    const baseEvents = [
      {
        type: "tool_call" as const,
        task_id: "task-tools-running",
        trace_id: "trace-tools-running",
        iteration: 0,
        timestamp: "2026-03-24T00:00:02.000Z",
        data: {
          tool_calls: [
            {
              id: "call-read",
              name: "read_file",
              arguments: { path: "README.md" },
            },
            {
              id: "call-test",
              name: "run_bash",
              arguments: { command: "npm test" },
            },
          ],
          tool_results: [
            {
              tool_call_id: "call-read",
              name: "read_file",
              result: "ok",
              success: true,
            },
          ],
        },
      },
    ];

    const { rerender } = render(
      <RecursionCard
        messageId="message-tools-running"
        recursion={buildRecursion({
          summary: "Running checks",
          status: "running",
          events: baseEvents,
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    const toolGroup = screen.getByRole("button", { name: /2 tools used/i });
    await waitFor(() => {
      expect(toolGroup).toHaveAttribute("aria-expanded", "true");
    });
    expect(
      screen.getByRole("button", { name: /Running run_bash/i }),
    ).toBeInTheDocument();

    rerender(
      <RecursionCard
        messageId="message-tools-running"
        recursion={buildRecursion({
          summary: "Running checks",
          status: "running",
          events: [
            {
              ...baseEvents[0],
              data: {
                ...baseEvents[0].data,
                tool_results: [
                  ...baseEvents[0].data.tool_results,
                  {
                    tool_call_id: "call-test",
                    name: "run_bash",
                    result: { ok: true },
                    success: true,
                  },
                ],
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(toolGroup).toHaveAttribute("aria-expanded", "false");
    });
    expect(
      screen.queryByRole("button", { name: /Ran run_bash/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps failed tool results from falling back to preparing", () => {
    render(
      <RecursionCard
        messageId="message-failed-reversed"
        recursion={buildRecursion({
          summary: "Lint failed",
          status: "completed",
          endTime: "2026-03-24T00:00:04.000Z",
          events: [
            {
              type: "tool_result",
              task_id: "task-failed-reversed",
              trace_id: "trace-failed-reversed",
              iteration: 0,
              timestamp: "2026-03-24T00:00:03.000Z",
              data: {
                tool_results: [
                  {
                    tool_call_id: "call-failed",
                    name: "run_lint",
                    error: "lint failed",
                    success: false,
                  },
                ],
              },
            },
            {
              type: "tool_call",
              task_id: "task-failed-reversed",
              trace_id: "trace-failed-reversed",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-failed",
                    name: "run_lint",
                    arguments: { target: "web" },
                  },
                ],
                tool_results: [],
                pending_arguments: true,
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    const failedTool = screen.getByRole("button", { name: /Ran run_lint/i });
    expect(failedTool).toHaveTextContent("Failed");
    expect(
      screen.queryByRole("button", { name: /Preparing run_lint/i }),
    ).not.toBeInTheDocument();
  });

  it("copies expanded tool arguments and results independently", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(
      <RecursionCard
        messageId="message-copy-tool"
        recursion={buildRecursion({
          summary: "Read file",
          status: "completed",
          endTime: "2026-03-24T00:00:05.000Z",
          events: [
            {
              type: "tool_call",
              task_id: "task-copy-tool",
              trace_id: "trace-copy-tool",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-copy",
                    name: "read_file",
                    arguments: { path: "README.md" },
                  },
                ],
                tool_results: [
                  {
                    tool_call_id: "call-copy",
                    name: "read_file",
                    result: "file contents",
                    success: true,
                  },
                ],
              },
            },
          ],
        })}
        isExpanded={false}
        onToggle={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Ran read_file/i }));
    await user.click(screen.getByRole("button", { name: "Copy Arguments" }));
    expect(writeText).toHaveBeenCalledWith('{\n  "path": "README.md"\n}');
    expect(
      screen.getByRole("button", { name: "Copied Arguments" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Copy Result" }));
    expect(writeText).toHaveBeenLastCalledWith("file contents");
    expect(screen.getByRole("button", { name: "Copied Result" })).toBeInTheDocument();
  });
});
