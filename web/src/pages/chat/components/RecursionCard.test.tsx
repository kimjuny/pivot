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
  it("renders the thinking section while reasoning tokens are streaming", () => {
    render(
      <RecursionCard
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
      />,
    );

    expect(
      screen.getByRole("button", { name: "Toggle thinking details" }),
    ).toHaveAttribute("aria-expanded", "true");
    // No shell title, no leaked protocol label, no ticker.
    expect(screen.queryByText("CALL_TOOL")).not.toBeInTheDocument();
    expect(screen.queryByText("Working...")).not.toBeInTheDocument();
    expect(screen.queryByText("Completed step")).not.toBeInTheDocument();
  });

  it("renders nothing for a pure-tool iteration that has no content yet", () => {
    const { container } = render(
      <RecursionCard
        recursion={buildRecursion({
          iteration: 2,
          // No thinking, no message, no events.
        })}
      />,
    );

    // The brief window between recursion_start and the first content event
    // renders an empty stream — no placeholder label is leaked.
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText("CALL_TOOL")).not.toBeInTheDocument();
  });

  it("renders the agent progress note as an aside line, never a button", () => {
    render(
      <RecursionCard
        recursion={buildRecursion({
          thinking: "Need to inspect the repo state.",
          message: "Repository structure loaded.",
          status: "completed",
          endTime: "2026-03-24T00:00:03.000Z",
          events: [
            {
              type: "message",
              task_id: "task-2",
              trace_id: "trace-2",
              iteration: 0,
              timestamp: "2026-03-24T00:00:01.000Z",
            },
          ],
        })}
      />,
    );

    // The message is rendered as plain text, not a toggle button.
    expect(
      screen.getByText("Repository structure loaded."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Repository structure loaded/i }),
    ).not.toBeInTheDocument();
  });

  it("collapses completed thinking by default while keeping it available", () => {
    render(
      <RecursionCard
        recursion={buildRecursion({
          thinking: "I compared the available implementation paths.",
          message: "Picked the smaller frontend-only change.",
          status: "completed",
          endTime: "2026-03-24T00:00:03.000Z",
        })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Toggle thinking details" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByText("Picked the smaller frontend-only change."),
    ).toBeInTheDocument();
  });

  it("never renders the raw action enum even when set on the record", () => {
    // Regression: CALL_TOOL used to leak into the title via the
    // `message || action` fallback. The data field still drives status
    // transitions in the reducer, but the view must never surface it.
    render(
      <RecursionCard
        recursion={buildRecursion({
          action: "CALL_TOOL",
          status: "completed",
          endTime: "2026-03-24T00:00:04.000Z",
          events: [
            {
              type: "tool_call",
              task_id: "task-action",
              trace_id: "trace-action",
              iteration: 0,
              timestamp: "2026-03-24T00:00:04.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-action",
                    name: "read_file",
                    arguments: { path: "README.md" },
                  },
                ],
                tool_results: [
                  {
                    tool_call_id: "call-action",
                    name: "read_file",
                    result: "ok",
                    success: true,
                  },
                ],
              },
            },
          ],
        })}
      />,
    );

    expect(screen.queryByText("CALL_TOOL")).not.toBeInTheDocument();
    expect(screen.queryByText("Action")).not.toBeInTheDocument();
  });

  it("keeps the message visible while tool execution is waiting on results", () => {
    render(
      <RecursionCard
        recursion={buildRecursion({
          message: "Loaded project files",
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
      />,
    );

    expect(screen.getByText("Loaded project files")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Running read_files/i }),
    ).toHaveTextContent("Running");
  });

  it("renders live write and edit payload previews with filename counters", async () => {
    const user = userEvent.setup();

    render(
      <RecursionCard
        recursion={buildRecursion({
          message: "Updating files",
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
                    arguments: {},
                    pending_arguments: true,
                  },
                  {
                    id: "call-edit",
                    name: "edit_file",
                    arguments: {},
                    pending_arguments: true,
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
                delta: JSON.stringify({
                  path: "web/src/pages/chat/index.tsx",
                  content: "alpha\nbeta\ngamma",
                }),
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
                delta: JSON.stringify({
                  path: "server/app/demo.py",
                  diff: "@@ -1,2 +1,2 @@\n-old\n+new\n context",
                }),
              },
            },
          ],
        })}
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

    it("updates the write_file line counter as content deltas stream in", () => {
      // Regression: when tool_payload_delta arrives in many small chunks (the
      // real streaming path), the "+N" counter must grow incrementally rather
      // than staying frozen at the first value until the final delta lands.
      // The backend forwards raw arguments JSON fragments; a TS extractor
      // surfaces the in-progress `content` field for live +N rendering.
      const basePath = "web/src/pages/chat/index.tsx";
      // Mirrors how the LLM streams write_file: the content value grows
      // INSIDE one arguments JSON whose content string only closes at the
      // very end.  We assemble the final raw JSON, then stream growing
      // prefixes of it as separate tool_payload_delta fragments -- exactly
      // what the backend's coalesced fragments look like.
      const finalContent = [
        "alpha\n",
        "beta\n",
        "gamma\n",
        "delta\n",
        "epsilon\n",
        "zeta\n",
      ].join("");
      const fullRaw = JSON.stringify({ path: basePath, content: finalContent });

      // Compute prefix lengths that correspond to each cumulative line
      // count.  Each prefix cuts the content value mid-stream (string still
      // open) except the last, which closes it.
      const contentOpen = fullRaw.indexOf('"content":"') + '"content":"'.length;
      const contentValueEscaped = fullRaw.slice(
        contentOpen,
        fullRaw.lastIndexOf('"'),
      );
      const prefixForLines = (lines: number): number => {
        // Walk the escaped content until we've seen `lines` newlines.
        let seen = 0;
        let i = 0;
        while (i < contentValueEscaped.length && seen < lines) {
          if (contentValueEscaped.slice(i, i + 2) === "\\n") {
            seen += 1;
            i += 2;
          } else {
            i += 1;
          }
        }
        return contentOpen + i;
      };
      const checkpoints: Array<[number, number]> = [
        [prefixForLines(1), 1],
        [prefixForLines(3), 3],
        [fullRaw.length, 6],
      ];

      const events: RecursionRecord["events"] = [
        {
          type: "tool_call",
          task_id: "task-stream-counter",
          trace_id: "trace-stream-counter",
          iteration: 0,
          timestamp: "2026-03-24T00:00:02.000Z",
          data: {
            tool_calls: [
              {
                id: "call-write-stream",
                name: "write_file",
                arguments: {},
                pending_arguments: true,
              },
            ],
            tool_results: [],
          },
        },
      ];

      const { rerender } = render(
        <RecursionCard
          recursion={buildRecursion({ message: "Writing", events: [...events] })}
        />,
      );

      let previousLen = 0;
      for (const [rawLen, expectedLines] of checkpoints) {
        events.push({
          type: "tool_payload_delta",
          task_id: "task-stream-counter",
          trace_id: "trace-stream-counter",
          iteration: 0,
          timestamp: "2026-03-24T00:00:02.200Z",
          data: {
            tool_call_id: "call-write-stream",
            tool_name: "write_file",
            delta: fullRaw.slice(previousLen, rawLen),
          },
        });
        previousLen = rawLen;

        rerender(
          <RecursionCard
            recursion={buildRecursion({ message: "Writing", events: [...events] })}
          />,
        );

        const writeTool = screen.getByRole("button", {
          name: /Running write_file/i,
        });
        expect(writeTool).toHaveTextContent(`+${expectedLines}`);
      }
    });

    it("renders filename and +N counter when deltas arrive before tool_call", () => {
      // Regression: the live +N counter (and the filename shown next to it)
      // used to vanish intermittently while content streamed in. Root cause:
      // tool_payload_delta can reach the frontend before the first tool_call
      // event (the backend emits deltas as soon as args start streaming, and
      // the finalized tool_call only lands once the whole args JSON parses).
      const content = "line1\nline2\nline3\n";
      const fullRaw = JSON.stringify({ path: "src/app.ts", content });
      const events: RecursionRecord["events"] = [
        {
          type: "tool_payload_delta",
          task_id: "task-delta-first",
          trace_id: "trace-delta-first",
          iteration: 0,
          timestamp: "2026-03-24T00:00:02.000Z",
          data: {
            tool_call_id: "call-delta-first",
            tool_name: "write_file",
            delta: fullRaw.slice(0, Math.floor(fullRaw.length / 2)),
          },
        },
        {
          type: "tool_payload_delta",
          task_id: "task-delta-first",
          trace_id: "trace-delta-first",
          iteration: 0,
          timestamp: "2026-03-24T00:00:02.100Z",
          data: {
            tool_call_id: "call-delta-first",
            tool_name: "write_file",
            delta: fullRaw.slice(Math.floor(fullRaw.length / 2)),
          },
        },
      ];

      render(
        <RecursionCard
          recursion={buildRecursion({ message: "Writing", events: [...events] })}
        />,
      );

      const writeTool = screen.getByRole("button", {
        name: /Preparing write_file|Running write_file/i,
      });
      expect(writeTool).toHaveTextContent("app.ts");
      expect(writeTool).toHaveTextContent("+3");
    });


  it("labels truncated write_file previews with real source line numbers", async () => {
    const user = userEvent.setup();
    const content = Array.from(
      { length: 430 },
      (_, index) => `line-${index + 1}`,
    ).join("\n");

    render(
      <RecursionCard
        recursion={buildRecursion({
          message: "Writing a large file",
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
        recursion={buildRecursion({
          message: "Editing a file",
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

  it("keeps edit_file diff in the preview but hides it from the displayed result", async () => {
    const user = userEvent.setup();
    const diff =
      "@@ -1,2 +1,2 @@\n-old value\n+new value\n context line";

    render(
      <RecursionCard
        recursion={buildRecursion({
          message: "Editing a file",
          events: [
            {
              type: "tool_call",
              task_id: "task-edit-result-diff",
              trace_id: "trace-edit-result-diff",
              iteration: 0,
              timestamp: "2026-03-24T00:00:02.000Z",
              data: {
                tool_calls: [
                  {
                    id: "call-edit-result-diff",
                    name: "edit_file",
                    arguments: {
                      path: "server/app/demo.py",
                      old_string: "old value",
                      new_string: "new value",
                    },
                  },
                ],
                tool_results: [
                  {
                    tool_call_id: "call-edit-result-diff",
                    name: "edit_file",
                    success: true,
                    result: {
                      message: "Updated server/app/demo.py",
                      diff,
                      content_hash: "abc123",
                      added_lines: 1,
                      removed_lines: 1,
                    },
                  },
                ],
              },
            },
          ],
        })}
      />,
    );

    await user.click(screen.getByRole("button", { name: /Ran edit_file/i }));

    expect(screen.getByText(/-old value/)).toBeInTheDocument();
    expect(screen.getByText(/\+new value/)).toBeInTheDocument();
    expect(screen.queryByText(/"diff":/)).not.toBeInTheDocument();
    expect(screen.queryByText(/"content_hash":/)).not.toBeInTheDocument();
    expect(screen.getByText(/Updated server\/app\/demo.py/)).toBeInTheDocument();
  });

  it("renders tool executions as one-line records with terminal details", async () => {
    const user = userEvent.setup();

    render(
      <RecursionCard
        recursion={buildRecursion({
          message: "Ran file checks",
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
        recursion={buildRecursion({
          message: "Running checks",
          status: "running",
          events: baseEvents,
        })}
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
        recursion={buildRecursion({
          message: "Running checks",
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
        recursion={buildRecursion({
          message: "Lint failed",
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
        recursion={buildRecursion({
          message: "Read file",
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
      />,
    );

    await user.click(screen.getByRole("button", { name: /Ran read_file/i }));
    await user.click(screen.getByRole("button", { name: "Copy Arguments" }));
    expect(writeText).toHaveBeenCalledWith('{\n  "path": "README.md"\n}');
    expect(
      screen.getByRole("button", { name: "Copied Arguments" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Copy Result" }));
    expect(writeText).toHaveBeenCalledWith("file contents");
    expect(screen.getByRole("button", { name: "Copied Result" })).toBeInTheDocument();
  });
});
