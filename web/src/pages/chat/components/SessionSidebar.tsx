import {
  Loader2,
  MessageCircle,
  PanelLeft,
  PanelLeftClose,
  PlusCircle,
  Trash2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type { SessionListItem } from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

interface SessionSidebarProps {
  sessions: SessionListItem[];
  currentSessionId: string | null;
  isLoadingSession: boolean;
  isStreaming: boolean;
  isCollapsed: boolean;
  onToggleCollapsed: () => void;
  onNewSession: () => void | Promise<void>;
  onSelectSession: (sessionId: string) => void | Promise<void>;
  onDeleteSession: (sessionId: string) => void | Promise<void>;
}

/**
 * Shows session navigation and keeps session management controls visually separated from the timeline.
 */
export function SessionSidebar({
  sessions,
  currentSessionId,
  isLoadingSession,
  isStreaming,
  isCollapsed,
  onToggleCollapsed,
  onNewSession,
  onSelectSession,
  onDeleteSession,
}: SessionSidebarProps) {
  return (
    <div
      className={`flex flex-shrink-0 flex-col border-r border-border bg-muted/30 transition-all duration-300 ease-in-out ${
        isCollapsed ? "w-12" : "w-64"
      }`}
    >
      <div
        className={`flex items-center border-b border-border p-3 ${
          isCollapsed ? "justify-center" : "justify-between"
        }`}
      >
        {!isCollapsed && (
          <Button
            onClick={() => {
              void onNewSession();
            }}
            variant="outline"
            className="flex-1 justify-start gap-2"
            disabled={isLoadingSession || isStreaming}
          >
            <PlusCircle className="h-4 w-4" />
            New Session
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className={`h-8 w-8 ${isCollapsed ? "" : "ml-2"}`}
          onClick={onToggleCollapsed}
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? (
            <PanelLeft className="h-4 w-4" />
          ) : (
            <PanelLeftClose className="h-4 w-4" />
          )}
        </Button>
      </div>

      {!isCollapsed && (
        <div className="flex-1 overflow-y-auto">
          <div className="space-y-1 p-2">
            {sessions.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">
                {isLoadingSession ? (
                  <div className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    <span>Loading sessions...</span>
                  </div>
                ) : (
                  <span>No sessions yet</span>
                )}
              </div>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.session_id}
                  onClick={() => {
                    void onSelectSession(session.session_id);
                  }}
                  className={`group w-full cursor-pointer rounded-lg border p-2 text-left transition-colors ${
                    session.session_id === currentSessionId
                      ? "border-primary/30 bg-primary/10"
                      : "border-transparent hover:bg-muted"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <MessageCircle className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
                        <span className="truncate text-sm font-medium">
                          {session.subject || "New conversation"}
                        </span>
                      </div>
                      <div className="mt-1 pl-5 text-xs text-muted-foreground">
                        {formatTimestamp(session.updated_at)}
                      </div>
                      <div className="mt-0.5 pl-5 text-xs text-muted-foreground">
                        {session.message_count} messages
                      </div>
                    </div>
                    <button
                      type="button"
                      className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded opacity-0 transition-opacity hover:bg-accent group-hover:opacity-100"
                      onClick={(event) => {
                        event.stopPropagation();
                        void onDeleteSession(session.session_id);
                      }}
                      title="Delete session"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {isCollapsed && (
        <div className="flex flex-1 flex-col items-center space-y-2 py-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => {
              void onNewSession();
            }}
            disabled={isLoadingSession || isStreaming}
            title="New Session"
          >
            <PlusCircle className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
