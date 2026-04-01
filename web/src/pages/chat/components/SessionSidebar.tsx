import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import {
  Loader2,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  SquarePen,
  Trash2,
} from "@/lib/lucide";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { useSidebar } from "@/hooks/use-sidebar";
import type { SessionListItem } from "@/utils/api";
import type { ChatSidebarNavigationItem } from "@/pages/chat/types";

interface SessionSidebarProps {
  sessions: SessionListItem[];
  currentSessionId: string | null;
  isLoadingSession: boolean;
  hasInitializedSessions: boolean;
  isStreaming: boolean;
  sidebarTitleIcon?: ReactNode;
  sidebarTitle?: string;
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
  navigationItems?: ChatSidebarNavigationItem[];
  footer?: (isCollapsed: boolean) => ReactNode;
}

/**
 * Resolve the compact, user-facing session label shown in the sidebar.
 */
function getSessionTitle(session: SessionListItem): string {
  return session.title?.trim() || "New conversation";
}

/**
 * Whether the sidebar should show a live execution indicator for this session.
 *
 * Why: the sidebar only needs a lightweight "something is still running"
 * signal, and the persisted session status is the stable cross-refresh source
 * we already have for that state.
 */
function isSessionRunning(session: SessionListItem): boolean {
  return session.runtime_status === "running";
}

/**
 * Shows session navigation and keeps session-management controls visually
 * separated from the conversation timeline.
 */
export function SessionSidebar({
  sessions,
  currentSessionId,
  isLoadingSession,
  hasInitializedSessions,
  isStreaming,
  sidebarTitleIcon,
  sidebarTitle,
  onNewSession,
  onSelectSession,
  onRenameSession,
  onTogglePinSession,
  onDeleteSession,
  navigationItems = [],
  footer,
}: SessionSidebarProps) {
  const { state } = useSidebar();
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>("");
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const isCollapsed = state === "collapsed";
  const isSessionListPending = isLoadingSession || !hasInitializedSessions;

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
    <Sidebar
      layout="contained"
      collapsible="icon"
      className="border-r border-sidebar-border/70 bg-sidebar/95"
    >
      <SidebarHeader className="session-sidebar-header gap-2 px-3 pb-2 pt-3 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-2">
        {!isCollapsed && sidebarTitle ? (
          <div className="pb-1">
            <div className="flex items-center gap-2 rounded-xl px-2 py-1.5">
              {sidebarTitleIcon ? (
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sidebar-accent/70 text-sidebar-foreground">
                  {sidebarTitleIcon}
                </div>
              ) : (
                <span className="h-2.5 w-2.5 rounded-full bg-primary/80" />
              )}
              <div className="min-w-0">
                <div className="truncate text-[15px] font-semibold tracking-tight text-sidebar-foreground">
                  {sidebarTitle}
                </div>
              </div>
            </div>
          </div>
        ) : null}

        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              tooltip="New Session"
              onClick={() => {
                void onNewSession();
              }}
              disabled={isLoadingSession || isStreaming}
              className="text-sidebar-foreground/65 hover:bg-sidebar-accent hover:text-sidebar-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-foreground"
            >
              <SquarePen className="h-4 w-4" />
              <span>New Session</span>
            </SidebarMenuButton>
          </SidebarMenuItem>

          {navigationItems.map((item) => (
            <SidebarMenuItem key={item.key}>
              <SidebarMenuButton
                isActive={item.isActive}
                tooltip={item.label}
                onClick={() => {
                  void item.onSelect();
                }}
                className="text-sidebar-foreground/65 hover:bg-sidebar-accent hover:text-sidebar-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-foreground"
              >
                {item.icon}
                <span>{item.label}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarHeader>

      {!isCollapsed && (
        <SidebarContent className="session-sidebar-scroll-area gap-0">
          <SidebarGroup className="py-2">
            <SidebarGroupLabel className="h-6 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/42">
              Sessions
            </SidebarGroupLabel>
            <SidebarGroupContent
              className={`${footer ? "session-sidebar-group-content " : ""}px-1 pt-1`}
            >
              {sessions.length === 0 ? (
                <div className="px-3 py-4 text-sm text-muted-foreground">
                  {isSessionListPending ? (
                    <div className="space-y-2" role="status" aria-live="polite">
                      <span className="sr-only">Loading sessions...</span>
                      {Array.from({ length: 3 }, (_, index) => (
                        <Skeleton
                          key={`session-skeleton-${index}`}
                          className="h-9 rounded-xl bg-sidebar-accent/55"
                          aria-hidden="true"
                        />
                      ))}
                    </div>
                  ) : (
                    <span>No sessions yet</span>
                  )}
                </div>
              ) : (
                <SidebarMenu>
                  {sessions.map((session) => {
                    const isActive = session.session_id === currentSessionId;
                    const isEditing = session.session_id === editingSessionId;

                    return (
                      <SidebarMenuItem key={session.session_id}>
                        {isEditing ? (
                          <div className="px-2 py-1">
                            <Input
                              ref={renameInputRef}
                              value={editingTitle}
                              onChange={(event) =>
                                setEditingTitle(event.target.value)
                              }
                              onBlur={() => {
                                void submitRename();
                              }}
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => {
                                void handleRenameKeyDown(event);
                              }}
                              className="h-8 rounded-lg border-sidebar-border/60 bg-background px-2 text-xs shadow-none focus-visible:ring-2"
                              aria-label="Rename session"
                            />
                          </div>
                        ) : (
                          <>
                            <SidebarMenuButton
                              isActive={isActive}
                              tooltip={getSessionTitle(session)}
                              onClick={() => {
                                void onSelectSession(session.session_id);
                              }}
                              className="h-9 rounded-xl px-2.5 pr-8 text-[13px] text-sidebar-foreground/68 hover:bg-sidebar-accent/85 hover:text-sidebar-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-foreground"
                            >
                              <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                                {isSessionRunning(session) ? (
                                  <Loader2
                                    className="h-3.5 w-3.5 animate-spin text-sidebar-foreground/60"
                                    aria-hidden="true"
                                  />
                                ) : null}
                              </span>
                              <span>{getSessionTitle(session)}</span>
                            </SidebarMenuButton>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <SidebarMenuAction
                                  showOnHover={!session.is_pinned}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                  }}
                                  title="Session actions"
                                  className="right-2 h-7 w-7 rounded-lg text-sidebar-foreground/45 hover:bg-sidebar-accent hover:text-sidebar-foreground !top-1/2 -translate-y-1/2"
                                >
                                  {session.is_pinned ? (
                                    <Pin className="h-4 w-4" />
                                  ) : (
                                    <MoreHorizontal className="h-4 w-4" />
                                  )}
                                </SidebarMenuAction>
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
                          </>
                        )}
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              )}
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      )}

      {footer ? (
        <SidebarFooter
          className={`${
            !isCollapsed ? "session-sidebar-footer " : ""
          }relative z-20 mt-auto bg-sidebar px-2 pb-2 pt-1 group-data-[collapsible=icon]:bg-transparent group-data-[collapsible=icon]:px-1 group-data-[collapsible=icon]:pb-2`}
        >
          {footer(isCollapsed)}
        </SidebarFooter>
      ) : null}

      <SidebarRail />
    </Sidebar>
  );
}
