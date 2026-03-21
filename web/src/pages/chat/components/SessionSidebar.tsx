import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import {
  Loader2,
  MoreHorizontal,
  PanelLeft,
  Pencil,
  Pin,
  PinOff,
  SquarePen,
  Trash2,
} from "@/lib/lucide";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type { SessionListItem } from "@/utils/api";

interface SessionSidebarProps {
  sessions: SessionListItem[];
  currentSessionId: string | null;
  isLoadingSession: boolean;
  isStreaming: boolean;
  isCollapsed: boolean;
  onToggleCollapsed: () => void;
  onNewSession: () => void | Promise<void>;
  onSelectSession: (sessionId: string) => void | Promise<void>;
  onRenameSession: (
    sessionId: string,
    title: string | null,
  ) => void | Promise<void>;
  onTogglePinSession: (
    sessionId: string,
    isPinned: boolean,
  ) => void | Promise<void>;
  onDeleteSession: (sessionId: string) => void | Promise<void>;
}

/**
 * Resolve the compact, user-facing session label shown in the sidebar.
 */
function getSessionTitle(session: SessionListItem): string {
  return session.title?.trim() || "New conversation";
}

/**
 * Shows session navigation and keeps session-management controls visually
 * separated from the conversation timeline.
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
  onRenameSession,
  onTogglePinSession,
  onDeleteSession,
}: SessionSidebarProps) {
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>("");
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!editingSessionId) {
      return;
    }

    renameInputRef.current?.focus();
    renameInputRef.current?.select();
  }, [editingSessionId]);

  /**
   * Enter inline-title editing so renames stay lightweight and fast.
   */
  const startRenaming = (session: SessionListItem) => {
    setEditingSessionId(session.session_id);
    setEditingTitle(session.title ?? "");
  };

  /**
   * Exit rename mode without touching persisted state.
   */
  const cancelRenaming = () => {
    setEditingSessionId(null);
    setEditingTitle("");
  };

  /**
   * Persist the current inline rename draft and fall back to the generated
   * title when the user clears the field entirely.
   */
  const submitRename = async () => {
    if (!editingSessionId) {
      return;
    }

    const nextTitle = editingTitle.trim();
    const sessionId = editingSessionId;
    cancelRenaming();
    await onRenameSession(sessionId, nextTitle.length > 0 ? nextTitle : null);
  };

  /**
   * Keep keyboard-driven renaming aligned with common list-editing behavior.
   */
  const handleRenameKeyDown = async (
    event: KeyboardEvent<HTMLInputElement>,
  ) => {
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      await submitRename();
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      cancelRenaming();
    }
  };

  return (
    <>
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
              <SquarePen className="h-4 w-4" />
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
            <PanelLeft className="h-4 w-4" />
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
                sessions.map((session) => {
                  const isActive = session.session_id === currentSessionId;
                  const isEditing = session.session_id === editingSessionId;

                  return (
                    <div
                      key={session.session_id}
                      onClick={() => {
                        if (isEditing) {
                          return;
                        }
                        void onSelectSession(session.session_id);
                      }}
                      className={`group w-full cursor-pointer rounded-lg border border-transparent px-2 py-1 text-left transition-colors ${
                        isActive ? "bg-muted" : "hover:bg-muted"
                      }`}
                    >
                      <div className="flex min-h-6 items-center justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          {isEditing ? (
                            <Input
                              ref={renameInputRef}
                              value={editingTitle}
                              onChange={(event) => setEditingTitle(event.target.value)}
                              onBlur={() => {
                                void submitRename();
                              }}
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => {
                                void handleRenameKeyDown(event);
                              }}
                              className="h-6 border-transparent bg-transparent px-0 text-xs shadow-none focus:border-transparent focus-visible:border-transparent focus-visible:ring-0"
                              aria-label="Rename session"
                            />
                          ) : (
                            <div className="flex min-w-0 min-h-6 items-center">
                              <span className="truncate text-xs font-medium">
                                {getSessionTitle(session)}
                              </span>
                            </div>
                          )}
                        </div>

                        {!isEditing && (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                type="button"
                                className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md transition-opacity hover:bg-accent ${
                                  session.is_pinned
                                    ? "opacity-100"
                                    : "opacity-0 group-hover:opacity-100 data-[state=open]:opacity-100"
                                }`}
                                onClick={(event) => {
                                  event.stopPropagation();
                                }}
                                title="Session actions"
                              >
                                <span className="relative flex h-4 w-4 items-center justify-center">
                                  {session.is_pinned && (
                                    <Pin className="absolute h-3.5 w-3.5 text-foreground transition-opacity group-hover:opacity-0" />
                                  )}
                                  <MoreHorizontal
                                    className={`absolute h-4 w-4 text-muted-foreground transition-opacity ${
                                      session.is_pinned
                                        ? "opacity-0 group-hover:opacity-100"
                                        : "opacity-100"
                                    }`}
                                  />
                                </span>
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="end"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <DropdownMenuItem
                                onSelect={() => {
                                  startRenaming(session);
                                }}
                              >
                                <Pencil className="h-4 w-4" />
                                Rename
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => {
                                  void onTogglePinSession(
                                    session.session_id,
                                    !session.is_pinned,
                                  );
                                }}
                              >
                                {session.is_pinned ? (
                                  <PinOff className="h-4 w-4" />
                                ) : (
                                  <Pin className="h-4 w-4" />
                                )}
                                {session.is_pinned ? "Unpin" : "Pin to top"}
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                onSelect={() => {
                                  void onDeleteSession(session.session_id);
                                }}
                                className="text-destructive focus:text-destructive"
                              >
                                <Trash2 className="h-4 w-4" />
                                Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </div>
                    </div>
                  );
                })
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
              <SquarePen className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>
    </>
  );
}
