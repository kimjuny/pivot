import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AssistantMessageBlock } from "./AssistantMessageBlock";

describe("AssistantMessageBlock", () => {
  it("renders the loading skill matcher only once while skills are resolving", () => {
    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-1",
          role: "assistant",
          content: "",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "skill_resolving",
          skillSelection: {
            status: "loading",
            count: 0,
            selectedSkills: [],
          },
          recursions: [],
        }}
        expandedRecursions={{}}
        onToggleRecursion={vi.fn()}
        onReplyTask={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Matching Skills...")).toHaveLength(1);
  });

  it("shows stopped instead of error for a stopped task", () => {
    render(
      <AssistantMessageBlock
        message={{
          id: "assistant-2",
          role: "assistant",
          content: "",
          timestamp: "2026-03-17T00:00:00.000Z",
          status: "stopped",
          recursions: [],
        }}
        expandedRecursions={{}}
        onToggleRecursion={vi.fn()}
        onReplyTask={vi.fn()}
      />,
    );

    expect(screen.getByText("Stopped")).toBeInTheDocument();
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
  });
});
