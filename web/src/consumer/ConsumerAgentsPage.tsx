import { useEffect, useMemo, useState } from "react";
import { Bot } from "@/lib/lucide";
import { useNavigate } from "react-router-dom";

import { MotionReorderLoading } from "@/components/MotionReorderLoading";
import { Badge } from "@/components/ui/badge";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import {
  deleteSession,
  type SessionListItem,
  updateSession,
} from "@/utils/api";
import { SessionSidebar } from "@/pages/chat/components/SessionSidebar";
import { Input } from "@/components/ui/input";
import {
  getConsumerAgents,
  getConsumerSessions,
  type ConsumerSessionListItem,
} from "@/consumer/api";
import ConsumerUserMenu from "@/consumer/ConsumerUserMenu";
import { LLMBrandAvatar } from "@/components/LLMBrandAvatar";
import type { Agent } from "@/types";

/**
 * Keep the recent-session list aligned with backend ordering semantics.
 */
function sortConsumerSessions(
  sessions: ConsumerSessionListItem[],
): ConsumerSessionListItem[] {
  return [...sessions].sort((left, right) => {
    if (left.is_pinned !== right.is_pinned) {
      return Number(right.is_pinned) - Number(left.is_pinned);
    }

    return Date.parse(right.updated_at) - Date.parse(left.updated_at);
  });
}

/**
 * Browse all Consumer-visible agents and open one chat workspace.
 */
function ConsumerAgentsPage() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [sessions, setSessions] = useState<ConsumerSessionListItem[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setIsLoading(true);
        setError(null);
        const [nextAgents, sessionResponse] = await Promise.all([
          getConsumerAgents(),
          getConsumerSessions(30),
        ]);
        setAgents(nextAgents);
        setSessions(sessionResponse.sessions);
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load consumer agents.",
        );
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredAgents = useMemo(
    () =>
      agents.filter((agent) => {
        if (normalizedQuery.length === 0) {
          return true;
        }

        const description = agent.description?.toLowerCase() ?? "";
        return (
          agent.name.toLowerCase().includes(normalizedQuery) ||
          description.includes(normalizedQuery)
        );
      }),
    [agents, normalizedQuery],
  );

  /**
   * Opens a fresh draft with the most relevant visible agent instead of
   * leaving people stranded on a dead-end browser page.
   */
  const handleNewSession = () => {
    const latestSession = sessions[0];
    if (latestSession) {
      navigate(`/app/agents/${latestSession.agent_id}`);
      return;
    }

    const firstAgent = agents[0];
    if (firstAgent) {
      navigate(`/app/agents/${firstAgent.id}`);
    }
  };

  /**
   * Routes back into the exact session the user picked from the recent list.
   */
  const handleSelectSession = (sessionId: string) => {
    const session = sessions.find((item) => item.session_id === sessionId);
    if (!session) {
      return;
    }

    navigate(`/app/agents/${session.agent_id}?session=${session.session_id}`);
  };

  /**
   * Keeps the browser sidebar in sync with lightweight session metadata edits.
   */
  const replaceSidebarSession = (
    sessionId: string,
    updater: (session: ConsumerSessionListItem) => ConsumerSessionListItem,
  ) => {
    setSessions((previous) =>
      sortConsumerSessions(
        previous.map((session) =>
          session.session_id === sessionId ? updater(session) : session,
        ),
      ),
    );
  };

  const sidebarSessions: SessionListItem[] = sessions;

  return (
    <SidebarProvider defaultOpen>
      <SessionSidebar
        sessions={sidebarSessions}
        currentSessionId={null}
        isLoadingSession={isLoading}
        hasInitializedSessions={!isLoading}
        isStreaming={false}
        sidebarTitleIcon={
          <img
            src="/pivot.svg"
            alt=""
            className="size-5"
            aria-hidden="true"
          />
        }
        sidebarTitle="Pivot"
        onNewSession={handleNewSession}
        onSelectSession={handleSelectSession}
        onRenameSession={async (sessionId, title) => {
          const updatedSession = await updateSession(sessionId, { title });
          replaceSidebarSession(sessionId, (session) => ({
            ...session,
            title: updatedSession.title,
            updated_at: updatedSession.updated_at,
          }));
        }}
        onTogglePinSession={async (sessionId, isPinned) => {
          const updatedSession = await updateSession(sessionId, {
            is_pinned: isPinned,
          });
          replaceSidebarSession(sessionId, (session) => ({
            ...session,
            is_pinned: updatedSession.is_pinned,
            updated_at: updatedSession.updated_at,
          }));
        }}
        onDeleteSession={async (sessionId) => {
          await deleteSession(sessionId);
          setSessions((previous) =>
            previous.filter((session) => session.session_id !== sessionId),
          );
        }}
        navigationItems={[
          {
            key: "agents",
            label: "Agents",
            icon: <Bot className="h-4 w-4" />,
            isActive: true,
            onSelect: () => {},
          },
        ]}
        footer={(isCollapsed) => (
          <ConsumerUserMenu isCollapsed={isCollapsed} />
        )}
      />

      <SidebarInset className="flex-1 overflow-y-auto bg-background text-foreground">
        <div className="pointer-events-none absolute left-3 top-3 z-20">
          <SidebarTrigger className="pointer-events-auto h-8 w-8 rounded-lg bg-transparent text-muted-foreground shadow-none hover:bg-accent/70 hover:text-foreground" />
        </div>
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-6 py-6">
          <div className="flex flex-col gap-4 pb-5 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-xl font-semibold tracking-tight text-foreground">
                Agents
              </h1>
              <p className="text-sm text-muted-foreground">
                Choose an agent and start a conversation.
              </p>
            </div>

            <div className="w-full md:max-w-xs">
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search agents…"
                aria-label="Search consumer agents"
              />
            </div>
          </div>

          <div className="flex-1">
            {isLoading ? (
              <div className="flex items-center gap-2 py-12 text-sm text-muted-foreground">
                <MotionReorderLoading className="h-4 w-4" />
                <span>Loading agents…</span>
              </div>
            ) : error ? (
              <div className="py-12 text-sm text-destructive">{error}</div>
            ) : filteredAgents.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">
                {agents.length === 0
                  ? "No agents available yet."
                  : "No agents match your search."}
              </div>
            ) : (
              <div className="flex flex-col">
                {filteredAgents.map((agent) => (
                  <button
                    key={agent.id}
                    type="button"
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-accent/50"
                    onClick={() => navigate(`/app/agents/${agent.id}`)}
                  >
                    <LLMBrandAvatar
                      model={agent.model_name}
                      containerClassName="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10"
                      imageClassName="size-4"
                      fallback={
                        <Bot
                          className="size-4 text-primary"
                          aria-hidden="true"
                        />
                      }
                    />

                    <span className="min-w-0 shrink-0 text-sm font-medium">
                      {agent.name}
                    </span>

                    <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                      {agent.description?.trim() ?? ""}
                    </span>

                    {agent.model_name && (
                      <Badge
                        variant="outline"
                        className="shrink-0 text-[10px]"
                      >
                        {agent.model_name}
                      </Badge>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

export default ConsumerAgentsPage;
