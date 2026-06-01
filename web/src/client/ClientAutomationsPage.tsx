import { useEffect, useState } from "react";
import { Bot, Clock } from "lucide-react";
import { useNavigate } from "react-router-dom";

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
  getClientSessions,
  type ClientSessionListItem,
} from "@/client/api";
import ClientUserMenu from "@/client/ClientUserMenu";
import { useNewSessionShortcut } from "@/hooks/use-new-session-shortcut";
import { ClientAutomationsView } from "@/client/ClientAutomationsView";

function sortClientSessions(
  sessions: ClientSessionListItem[],
): ClientSessionListItem[] {
  return [...sessions].sort((left, right) => {
    if (left.is_pinned !== right.is_pinned) {
      return Number(right.is_pinned) - Number(left.is_pinned);
    }
    return Date.parse(right.updated_at) - Date.parse(left.updated_at);
  });
}

/** Browse and manage scheduled automations. */
function ClientAutomationsPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<ClientSessionListItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const sessionResponse = await getClientSessions(30);
        setSessions(sessionResponse.sessions);
      } catch {
        // Automations view handles its own error state
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const handleNewSession = () => {
    const latestSession = sessions[0];
    if (latestSession) {
      navigate(`/app/agents/${latestSession.agent_id}`);
      return;
    }
    navigate("/app/agents");
  };

  useNewSessionShortcut(handleNewSession);

  const handleSelectSession = (sessionId: string) => {
    const session = sessions.find((item) => item.session_id === sessionId);
    if (!session) return;
    navigate(`/app/agents/${session.agent_id}?session=${session.session_id}`);
  };

  const handleNavigateToSession = (agentId: number, sessionUuid: string) => {
    navigate(`/app/agents/${agentId}?session=${sessionUuid}`);
  };

  const replaceSidebarSession = (
    sessionId: string,
    updater: (session: ClientSessionListItem) => ClientSessionListItem,
  ) => {
    setSessions((previous) =>
      sortClientSessions(
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
            isActive: false,
            onSelect: () => navigate("/app/agents"),
          },
          {
            key: "automations",
            label: "Automations",
            icon: <Clock className="h-4 w-4" />,
            isActive: true,
            onSelect: () => {},
          },
        ]}
        footer={(isCollapsed) => (
          <ClientUserMenu isCollapsed={isCollapsed} />
        )}
      />

      <SidebarInset className="flex-1 overflow-y-auto bg-background text-foreground">
        <div className="pointer-events-none absolute left-3 top-3 z-20">
          <SidebarTrigger className="pointer-events-auto h-8 w-8 rounded-lg bg-transparent text-muted-foreground shadow-none hover:bg-accent/70 hover:text-foreground" />
        </div>
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col px-6 py-6">
          <ClientAutomationsView
            onNavigateToSession={handleNavigateToSession}
          />
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

export default ClientAutomationsPage;
