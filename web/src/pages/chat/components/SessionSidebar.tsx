import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderUp,
  Loader2,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
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
import type { ChatSidebarNavigationItem, ChatSidebarProjectItem } from "@/pages/chat/types";
import type { SessionListItem } from "@/utils/api";

const EMPTY_PROJECTS: ChatSidebarProjectItem[] = [];
const EMPTY_NAVIGATION_ITEMS: ChatSidebarNavigationItem[] = [];
const SIDEBAR_ITEM_HOVER_CLASS =
  "text-sidebar-foreground/65 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-foreground";

interface SessionSidebarProps {
  sessions: SessionListItem[];
  projects?: ChatSidebarProjectItem[];
  currentSessionId: string | null;
  currentProjectId?: string | null;
  isNewSessionDraftActive?: boolean;
  isLoadingSession: boolean;
  hasInitializedSessions: boolean;
  isStreaming: boolean;
  sidebarTitleIcon?: ReactNode;
  sidebarTitle?: string;
  onNewSession: () => void | Promise<void>;
  onCreateProject?: () => void | Promise<void>;
  onSelectProject?: (projectId: string) => void | Promise<void>;
  onRenameProject?: (
    projectId: string,
    name: string | null,
  ) => void | Promise<void>;
  onDeleteProject?: (projectId: string) => void | Promise<void>;
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

interface SidebarEmptyActionProps {
  kind: "project" | "session";
  title: string;
  icon: ReactNode;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
}

/**
 * Presents an obvious next step when a sidebar section has no content yet.
 */
function SidebarEmptyAction({
  kind,
  title,
  icon,
  onClick,
  disabled = false,
}: SidebarEmptyActionProps) {
  if (kind === "project") {
    return (
      <SidebarMenuItem>
        <div className="relative">
          <span className="absolute left-2 top-1/2 z-10 flex h-5 w-5 -translate-y-1/2 items-center justify-center text-sidebar-foreground/55">
            {icon}
          </span>
          <SidebarMenuButton
            tooltip={title}
            onClick={() => {
              void onClick();
            }}
            disabled={disabled}
            className={`h-9 rounded-xl border border-dashed border-sidebar-border/70 pl-8 pr-8 text-[13px] hover:border-sidebar-border ${SIDEBAR_ITEM_HOVER_CLASS}`}
          >
            <span className="truncate">{title}</span>
          </SidebarMenuButton>
        </div>
      </SidebarMenuItem>
    );
  }

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        tooltip={title}
        onClick={() => {
          void onClick();
        }}
        disabled={disabled}
        className={`h-9 rounded-xl border border-dashed border-sidebar-border/70 px-2.5 pr-8 text-[13px] hover:border-sidebar-border ${SIDEBAR_ITEM_HOVER_CLASS}`}
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-sidebar-foreground/60">
          {icon}
        </span>
        <span>{title}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

interface SidebarLoadingPlaceholderProps {
  kind: "project" | "session";
}

/**
 * Keep loading layout aligned with the empty-action rows so section labels do
 * not jump when sidebar data resolves.
 */
function SidebarLoadingPlaceholder({
  kind,
}: SidebarLoadingPlaceholderProps) {
  return (
    <SidebarMenuItem
      data-testid={`sidebar-loading-placeholder-${kind}`}
    >
      <div
        className="flex h-9 w-full items-center gap-2.5 rounded-xl border border-dashed border-sidebar-border/70 px-2.5"
        role="status"
        aria-live="polite"
      >
        <span className="sr-only">
          {kind === "project" ? "Loading projects..." : "Loading sessions..."}
        </span>
        <Skeleton
          className="h-5 w-5 shrink-0 rounded-full bg-sidebar-accent"
          aria-hidden="true"
        />
        <Skeleton
          className="h-4 min-w-0 flex-1 rounded-full bg-sidebar-accent"
          aria-hidden="true"
        />
      </div>
    </SidebarMenuItem>
  );
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
 * Shows project and session navigation while keeping workspace-management
 * actions visually separate from the conversation timeline.
 */
export function SessionSidebar({
  sessions,
  projects = EMPTY_PROJECTS,
  currentSessionId,
  currentProjectId = null,
  isNewSessionDraftActive = false,
  isLoadingSession,
  hasInitializedSessions,
  isStreaming,
  sidebarTitleIcon,
  sidebarTitle,
  onNewSession,
  onCreateProject,
  onSelectProject,
  onRenameProject,
  onDeleteProject,
  onSelectSession,
  onRenameSession,
  onTogglePinSession,
  onDeleteSession,
  navigationItems = EMPTY_NAVIGATION_ITEMS,
  footer,
}: SessionSidebarProps) {
  const { state } = useSidebar();
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingSessionTitle, setEditingSessionTitle] = useState("");
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingProjectName, setEditingProjectName] = useState("");
  const [expandedProjects, setExpandedProjects] = useState<Record<string, boolean>>({});
  const renameSessionInputRef = useRef<HTMLInputElement | null>(null);
  const renameProjectInputRef = useRef<HTMLInputElement | null>(null);
  const isCollapsed = state === "collapsed";
  const isSessionListPending = isLoadingSession || !hasInitializedSessions;

  useEffect(() => {
    if (editingSessionId) {
      renameSessionInputRef.current?.focus();
      renameSessionInputRef.current?.select();
    }
  }, [editingSessionId]);

  useEffect(() => {
    if (editingProjectId) {
      renameProjectInputRef.current?.focus();
      renameProjectInputRef.current?.select();
    }
  }, [editingProjectId]);

  useEffect(() => {
    setExpandedProjects((currentState) => {
      const nextState: Record<string, boolean> = {};
      projects.forEach((project) => {
        const shouldAutoExpand = project.sessions.some(
          (session) =>
            session.session_id === currentSessionId || isSessionRunning(session),
        );
        nextState[project.project_id] =
          shouldAutoExpand || (currentState[project.project_id] ?? false);
      });
      return nextState;
    });
  }, [currentSessionId, projects]);

  /**
   * Enter inline-title editing so renames stay lightweight and fast.
   */
  const startRenamingSession = (session: SessionListItem) => {
    setEditingSessionId(session.session_id);
    setEditingSessionTitle(session.title ?? "");
  };

  /**
   * Enter inline renaming for one project row without leaving the sidebar.
   */
  const startRenamingProject = (project: ChatSidebarProjectItem) => {
    setEditingProjectId(project.project_id);
    setEditingProjectName(project.name);
  };

  /**
   * Exit session rename mode without touching persisted state.
   */
  const cancelSessionRenaming = () => {
    setEditingSessionId(null);
    setEditingSessionTitle("");
  };

  /**
   * Exit project rename mode without touching persisted state.
   */
  const cancelProjectRenaming = () => {
    setEditingProjectId(null);
    setEditingProjectName("");
  };

  /**
   * Toggle one project's nested session list without changing selection.
   */
  const toggleProjectExpanded = (projectId: string) => {
    setExpandedProjects((currentState) => ({
      ...currentState,
      [projectId]: !(currentState[projectId] ?? false),
    }));
  };

  /**
   * Persist the current session rename draft and fall back to the generated
   * title when the user clears the field entirely.
   */
  const submitSessionRename = async () => {
    if (!editingSessionId) {
      return;
    }

    const nextTitle = editingSessionTitle.trim();
    const sessionId = editingSessionId;
    cancelSessionRenaming();
    await onRenameSession(sessionId, nextTitle.length > 0 ? nextTitle : null);
  };

  /**
   * Persist the current project rename draft while keeping empty names invalid.
   */
  const submitProjectRename = async () => {
    if (!editingProjectId || !onRenameProject) {
      return;
    }

    const nextName = editingProjectName.trim();
    if (nextName.length === 0) {
      cancelProjectRenaming();
      return;
    }

    const projectId = editingProjectId;
    cancelProjectRenaming();
    await onRenameProject(projectId, nextName);
  };

  /**
   * Keep keyboard-driven inline editing aligned with common list behavior.
   */
  const handleRenameKeyDown = async (
    event: KeyboardEvent<HTMLInputElement>,
    scope: "session" | "project",
  ) => {
    event.stopPropagation();
    if (event.key === "Enter") {
      event.preventDefault();
      if (scope === "session") {
        await submitSessionRename();
      } else {
        await submitProjectRename();
      }
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      if (scope === "session") {
        cancelSessionRenaming();
      } else {
        cancelProjectRenaming();
      }
    }
  };

  /**
   * Render one session row so standalone and project-nested sessions stay
   * visually and behaviorally consistent.
   */
  const renderSessionRow = (session: SessionListItem) => {
    const isActive = session.session_id === currentSessionId;
    const isEditing = session.session_id === editingSessionId;
    const isRunning = isSessionRunning(session);

    return (
      <SidebarMenuItem key={session.session_id}>
        {isEditing ? (
          <div className="px-2 py-1">
            <Input
              ref={renameSessionInputRef}
              value={editingSessionTitle}
              onChange={(event) => setEditingSessionTitle(event.target.value)}
              onBlur={() => {
                void submitSessionRename();
              }}
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                void handleRenameKeyDown(event, "session");
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
              className={`h-9 gap-0 rounded-xl px-2.5 pr-8 text-[13px] ${SIDEBAR_ITEM_HOVER_CLASS}`}
            >
              <span
                data-testid={`session-running-indicator-${session.session_id}`}
                aria-hidden={!isRunning}
                className={`flex shrink-0 items-center justify-center overflow-hidden transition-[width,margin,opacity] duration-200 ease-out ${
                  isRunning ? "mr-2 w-4 opacity-100" : "mr-0 w-0 opacity-0"
                }`}
              >
                {isRunning ? (
                  <Loader2
                    className="h-3.5 w-3.5 animate-spin text-sidebar-foreground/60"
                    aria-hidden="true"
                  />
                ) : null}
              </span>
              <span className="min-w-0 flex-1 truncate transition-[transform] duration-200 ease-out">
                {getSessionTitle(session)}
              </span>
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
                    startRenamingSession(session);
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
                isActive={isNewSessionDraftActive}
                tooltip="New Chat"
                onClick={() => {
                  void onNewSession();
                }}
                disabled={isLoadingSession || isStreaming}
                className={SIDEBAR_ITEM_HOVER_CLASS}
              >
                <SquarePen className="h-4 w-4" />
                <span>New Chat</span>
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
                className={SIDEBAR_ITEM_HOVER_CLASS}
              >
                {item.icon}
                <span>{item.label}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
      </SidebarHeader>

      {!isCollapsed ? (
        <SidebarContent className="session-sidebar-scroll-area gap-0">
          {onCreateProject || projects.length > 0 ? (
            <SidebarGroup className="py-2">
              <SidebarGroupLabel className="flex h-6 items-center justify-between px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/42">
                <span>Projects</span>
                {onCreateProject ? (
                  <button
                    type="button"
                    aria-label="New project"
                    onClick={() => {
                      void onCreateProject();
                    }}
                    disabled={isLoadingSession || isStreaming}
                    className="flex h-5 w-5 items-center justify-center rounded-md text-sidebar-foreground/52 transition hover:bg-sidebar-accent hover:text-sidebar-foreground disabled:pointer-events-none disabled:opacity-40"
                  >
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </SidebarGroupLabel>
              <SidebarGroupContent className="px-1 pt-1">
                {projects.length === 0 ? (
                  isSessionListPending ? (
                    <SidebarMenu>
                      <SidebarLoadingPlaceholder kind="project" />
                    </SidebarMenu>
                  ) : onCreateProject ? (
                    <SidebarMenu>
                      <SidebarEmptyAction
                        kind="project"
                        title="New Project"
                        icon={<FolderUp className="h-3.5 w-3.5" />}
                        onClick={onCreateProject}
                        disabled={isLoadingSession || isStreaming}
                      />
                    </SidebarMenu>
                  ) : (
                    <div className="px-3 py-2 text-sm text-muted-foreground">
                      <span>No projects yet</span>
                    </div>
                  )
                ) : (
                  <SidebarMenu>
                    {projects.map((project) => {
                      const isEditing = project.project_id === editingProjectId;
                      const isProjectOverviewActive =
                        currentProjectId === project.project_id &&
                        currentSessionId === null;
                      const hasNestedSessions = project.sessions.length > 0;
                      const isExpanded =
                        expandedProjects[project.project_id] ?? false;

                      return (
                        <div key={project.project_id} className="space-y-1">
                          <SidebarMenuItem>
                            {isEditing ? (
                              <div className="px-2 py-1">
                                <Input
                                  ref={renameProjectInputRef}
                                  value={editingProjectName}
                                  onChange={(event) =>
                                    setEditingProjectName(event.target.value)
                                  }
                                  onBlur={() => {
                                    void submitProjectRename();
                                  }}
                                  onClick={(event) => event.stopPropagation()}
                                  onKeyDown={(event) => {
                                    void handleRenameKeyDown(event, "project");
                                  }}
                                  className="h-8 rounded-lg border-sidebar-border/60 bg-background px-2 text-xs shadow-none focus-visible:ring-2"
                                  aria-label="Rename project"
                                />
                              </div>
                            ) : (
                              <div className="group/project-item relative">
                                {hasNestedSessions ? (
                                  <button
                                    type="button"
                                    aria-label={
                                      isExpanded
                                        ? `Collapse project ${project.name}`
                                        : `Expand project ${project.name}`
                                    }
                                    aria-expanded={isExpanded}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      toggleProjectExpanded(project.project_id);
                                    }}
                                    className="absolute left-2 top-1/2 z-10 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-md text-sidebar-foreground/55 transition-colors duration-200 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                  >
                                    <Folder className="h-3.5 w-3.5 transition-opacity duration-200 group-hover/project-item:opacity-0" />
                                    {isExpanded ? (
                                      <ChevronDown className="absolute h-3.5 w-3.5 opacity-0 transition-opacity duration-200 group-hover/project-item:opacity-100" />
                                    ) : (
                                      <ChevronRight className="absolute h-3.5 w-3.5 opacity-0 transition-opacity duration-200 group-hover/project-item:opacity-100" />
                                    )}
                                  </button>
                                ) : (
                                  <span className="absolute left-2 top-1/2 z-10 flex h-5 w-5 -translate-y-1/2 items-center justify-center text-sidebar-foreground/50">
                                    <Folder className="h-3.5 w-3.5" />
                                  </span>
                                )}

                                <SidebarMenuButton
                                  isActive={isProjectOverviewActive}
                                  tooltip={project.name}
                                  onClick={() => {
                                    void onSelectProject?.(project.project_id);
                                  }}
                                  className={`h-9 rounded-xl pl-8 pr-8 text-[13px] ${SIDEBAR_ITEM_HOVER_CLASS}`}
                                >
                                  <span className="truncate">{project.name}</span>
                                </SidebarMenuButton>
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <SidebarMenuAction
                                      showOnHover
                                      onClick={(event) => {
                                        event.stopPropagation();
                                      }}
                                      title="Project actions"
                                      className="right-2 h-7 w-7 rounded-lg text-sidebar-foreground/45 hover:bg-sidebar-accent hover:text-sidebar-foreground !top-1/2 -translate-y-1/2"
                                    >
                                      <MoreHorizontal className="h-4 w-4" />
                                    </SidebarMenuAction>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent
                                    align="end"
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    <DropdownMenuItem
                                      onSelect={() => {
                                        startRenamingProject(project);
                                      }}
                                    >
                                      <Pencil className="h-4 w-4" />
                                      Rename
                                    </DropdownMenuItem>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                      onSelect={() => {
                                        void onDeleteProject?.(project.project_id);
                                      }}
                                      className="text-destructive focus:text-destructive"
                                    >
                                      <Trash2 className="h-4 w-4" />
                                      Delete
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              </div>
                            )}
                          </SidebarMenuItem>

                          {hasNestedSessions ? (
                            <div
                              aria-hidden={!isExpanded}
                              className={`ml-4 overflow-hidden border-l border-sidebar-border/40 pl-2 transition-[max-height,opacity,margin] duration-200 ease-out ${
                                isExpanded
                                  ? "mt-1 opacity-100"
                                  : "mt-0 opacity-0 pointer-events-none"
                              }`}
                              style={{
                                maxHeight: isExpanded
                                  ? `${project.sessions.length * 44 + 8}px`
                                  : "0px",
                              }}
                            >
                              <SidebarMenu>
                                {project.sessions.map((session) =>
                                  renderSessionRow(session),
                                )}
                              </SidebarMenu>
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </SidebarMenu>
                )}
              </SidebarGroupContent>
            </SidebarGroup>
          ) : null}

          <SidebarGroup className="py-2">
            <SidebarGroupLabel className="h-6 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/42">
              Sessions
            </SidebarGroupLabel>
            <SidebarGroupContent
              className={`${footer ? "session-sidebar-group-content " : ""}px-1 pt-1`}
            >
              {sessions.length === 0 ? (
                isSessionListPending ? (
                  <SidebarMenu>
                    <SidebarLoadingPlaceholder kind="session" />
                  </SidebarMenu>
                ) : (
                  <SidebarMenu>
                    <SidebarEmptyAction
                      kind="session"
                      title="New Chat"
                      icon={<SquarePen className="h-4 w-4" />}
                      onClick={onNewSession}
                      disabled={isLoadingSession || isStreaming}
                    />
                  </SidebarMenu>
                )
              ) : (
                <SidebarMenu>{sessions.map((session) => renderSessionRow(session))}</SidebarMenu>
              )}
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      ) : null}

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
