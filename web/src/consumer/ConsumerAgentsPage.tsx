import { useEffect, useMemo, useState } from "react";
import { Bot, Loader2 } from "@/lib/lucide";
import { useNavigate } from "react-router-dom";

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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  getConsumerAgents,
  getConsumerSessions,
  type ConsumerSessionListItem,
} from "@/consumer/api";
import ConsumerUserMenu from "@/consumer/ConsumerUserMenu";
import type { Agent } from "@/types";
import { formatTimestamp } from "@/utils/timestamp";

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
        isStreaming={false}
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
        <div className="mx-auto flex min-h-full w-full max-w-7xl flex-col px-6 py-6">
          <div className="flex flex-col gap-4 border-b border-border pb-5 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight text-foreground">
                Agents
              </h1>
              <p className="text-sm text-muted-foreground">
                Choose an agent and jump straight into work.
              </p>
            </div>

            <div className="w-full md:max-w-sm">
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search agents"
                aria-label="Search consumer agents"
              />
            </div>
          </div>

          <div className="py-6">
            {isLoading ? (
              <Card>
                <CardContent className="flex items-center gap-2 pt-6 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>Loading visible agents…</span>
                </CardContent>
              </Card>
            ) : error ? (
              <Card>
                <CardContent className="pt-6 text-sm text-destructive">
                  {error}
                </CardContent>
              </Card>
            ) : filteredAgents.length === 0 ? (
              <Card>
                <CardContent className="pt-6 text-sm text-muted-foreground">
                  No published agents matched your search.
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {filteredAgents.map((agent) => (
                  <Card
                    key={agent.id}
                    className="cursor-pointer transition-colors hover:border-primary/40"
                    onClick={() => navigate(`/app/agents/${agent.id}`)}
                  >
                    <CardHeader>
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-2">
                          <CardTitle className="flex items-center gap-2">
                            <Bot className="h-4 w-4 text-primary" />
                            <span>{agent.name}</span>
                          </CardTitle>
                          <CardDescription className="line-clamp-3 min-h-[3.75rem]">
                            {agent.description?.trim() || "No description yet."}
                          </CardDescription>
                        </div>
                        <Badge variant="secondary">Live</Badge>
                      </div>
                    </CardHeader>

                    <CardContent className="space-y-4">
                      <div className="space-y-1 text-sm text-muted-foreground">
                        <div>{agent.model_name || "No model label"}</div>
                        <div>Updated {formatTimestamp(agent.updated_at)}</div>
                      </div>

                      <Button
                        type="button"
                        className="w-full"
                        onClick={(event) => {
                          event.stopPropagation();
                          navigate(`/app/agents/${agent.id}`);
                        }}
                      >
                        Open chat
                      </Button>
                    </CardContent>
                  </Card>
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
