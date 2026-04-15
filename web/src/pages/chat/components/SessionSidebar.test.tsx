import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SidebarProvider } from "@/components/ui/sidebar";
import type { SessionListItem } from "@/utils/api";
import type { ChatSidebarProjectItem } from "@/pages/chat/types";

import { SessionSidebar } from "./SessionSidebar";

const baseSession: SessionListItem = {
  session_id: "session-1",
  agent_id: 1,
  status: "active",
  runtime_status: "idle",
  title: "Idle Session",
  is_pinned: false,
  created_at: "2026-04-10T00:00:00+00:00",
  updated_at: "2026-04-10T00:00:00+00:00",
};

function renderSessionSidebar(
  sessions: SessionListItem[],
  options: {
    projects?: ChatSidebarProjectItem[];
    currentSessionId?: string | null;
  } = {},
) {
  return render(
    <SidebarProvider defaultOpen={true}>
      <SessionSidebar
        sessions={sessions}
        projects={options.projects}
        currentSessionId={options.currentSessionId ?? null}
        isLoadingSession={false}
        hasInitializedSessions={true}
        isStreaming={false}
        onNewSession={vi.fn()}
        onSelectSession={vi.fn()}
        onRenameSession={vi.fn()}
        onTogglePinSession={vi.fn()}
        onDeleteSession={vi.fn()}
      />
    </SidebarProvider>,
  );
}

describe("SessionSidebar", () => {
  it("does not reserve indicator space for idle sessions", () => {
    renderSessionSidebar([baseSession]);

    const indicator = screen.getByTestId("session-running-indicator-session-1");
    expect(indicator).toHaveClass("w-0", "mr-0", "opacity-0");
    expect(indicator.querySelector("svg")).toBeNull();
  });

  it("expands the indicator slot only while a session is running", () => {
    renderSessionSidebar([
      {
        ...baseSession,
        session_id: "session-running",
        title: "Running Session",
        runtime_status: "running",
      },
    ]);

    const indicator = screen.getByTestId(
      "session-running-indicator-session-running",
    );
    expect(indicator).toHaveClass("w-4", "mr-2", "opacity-100");
    expect(indicator.querySelector("svg")).not.toBeNull();
  });

  it("auto-expands the project containing the active session", () => {
    const projectSession: SessionListItem = {
      ...baseSession,
      session_id: "project-session",
      project_id: "project-1",
      title: "Project Session",
    };

    renderSessionSidebar([], {
      currentSessionId: "project-session",
      projects: [
        {
          id: 1,
          project_id: "project-1",
          agent_id: 1,
          name: "Launch Project",
          description: null,
          workspace_id: "workspace-1",
          created_at: "2026-04-10T00:00:00+00:00",
          updated_at: "2026-04-10T00:00:00+00:00",
          sessions: [projectSession],
        },
      ],
    });

    expect(screen.getByText("Project Session")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Collapse project Launch Project" }),
    ).toHaveAttribute("aria-expanded", "true");
  });
});
