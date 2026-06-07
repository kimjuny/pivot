import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { flushSync } from "react-dom";
import { Info } from "lucide-react";
import { resolveIcon } from "@/lib/icon-resolver";
import { useNewSessionShortcut } from "@/hooks/use-new-session-shortcut";

import {
  ApiError,
  cancelReactTask,
  compactReactSession,
  createProject,
  createDevSurfaceSession,
  createInstalledSurfaceSession,
  createSession,
  deleteProject,
  deleteSession,
  editReactTask,
  getAgentWebSearchBindings,
  getAgentChatSurfaces,
  type ChatSurfaceDescriptorResponse,
  getFullSessionHistory,
  getPreviewEndpoints,
  getReactContextUsage,
  getReactRuntimeSkills,
  getReactSessionRuntimeDebug,
  getAgents,
  listProjects,
  listSessions,
  migrateSession,
  startReactTask,
  submitMidTaskInput,
  submitReactUserAction,
  updateProject,
  updateSession,
  type ProjectResponse,
  type DevSurfaceSessionResponse,
  type ReactContextUsageSummary,
  type TaskSummary,
  type FullSessionHistoryResponse,
  type ReactSessionRuntimeDebug,
  type InstalledSurfaceSessionResponse,
  type PreviewEndpointResponse,
  type SessionListItem,
  type SessionResponse,
  type WebSearchBinding,
  getApiBaseUrl,
  httpClient,
} from "@/utils/api";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  type AutomationProposal,
  AutomationCreateDialog,
} from "@/components/AutomationCreateDialog";
import type { Agent } from "@/types";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  AUTH_EXPIRED_EVENT,
  getAuthToken,
  isTokenValid,
} from "@/contexts/auth-core";

import { ChatComposer } from "./components/ChatComposer";
import { CompactStatusPill } from "./components/CompactStatusPill";
import { ConversationView } from "./components/ConversationView";
import type { RewindScope } from "./components/UserMessageBubble";
import { RoundAnchor } from "./components/RoundAnchor";
import { ExtensionDock } from "./components/ExtensionDock";
import type { InstalledChatSurfaceDescriptor } from "./components/ExtensionDock";
import { useRegisterChatDebugPanelSection } from "./components/ChatDebugPanelContext";
import ProjectAccessDialog from "./components/ProjectAccessDialog";
import { SessionSidebar } from "./components/SessionSidebar";
import StaleSessionDialog from "@/components/StaleSessionDialog";
import { useChatAutoScroll } from "./hooks/useChatAutoScroll";
import { useChatSessionRuntime } from "./hooks/useChatSessionRuntime";
import { useConversationRounds, type ConversationRound } from "./hooks/useConversationRounds";
import { useChatUploads } from "./hooks/useChatUploads";
import { useScrollUpPagination } from "./hooks/useScrollUpPagination";
import { Spinner } from "@/components/ui/spinner";
import type {
  ChatWebSearchProviderOption,
  ChatPageProps,
  ChatMessage,
  MandatorySkillSelection,
  ChatReplyTarget,
  ChatSidebarProjectItem,
  PlanStepData,
  ReactStreamEvent,
  RecursionRecord,
  SkillChangeApprovalRequest,
  TokenUsage,
} from "./types";
import type { ChatThinkingMode } from "@/utils/llmThinking";
import {
  buildMessagesFromHistory,
  getCanonicalChatMessageId,
  getStreamErrorData,
  isReactStreamEvent,
  parseJson,
  parseTokenRateData,
  toAssistantAttachment,
} from "./utils/chatData";
import {
  getAutoSelectedSessionId,
  resolveSessionIdleTimeoutMs,
} from "./utils/sessionActivity";
import {
  ZERO_RATE_STREAK_TO_RENDER,
  deriveComposerTaskPlan,
  extractSkillChangeApprovalRequest,
  extractSkillChangeApprovalRequestFromClarifyData,
  isClarifyMessage,
} from "./utils/chatSelectors";
import {
  type ActionHandlerContext,
  dispatchPivotActionFromToolResult,
} from "./utils/actionHandlers";

const COMPACT_STATUS_MIN_VISIBLE_MS = 2200;
const COMPACT_SKILL_NAME = "compact";
const COMPACT_SKILL_SELECTION: MandatorySkillSelection = {
  name: COMPACT_SKILL_NAME,
  description:
    "Compact the current session runtime window with optional one-off guidance.",
  path: "/runtime/compact",
};
const DOCK_TRANSITION_MS = 200;
const SESSION_LOADING_OVERLAY_TRANSITION_MS = 200;
const CHAT_HISTORY_PAGE_SIZE = 10;
const OFFICIAL_SAMPLE_SURFACE_KEY = "workspace-editor";
const LOCAL_VITE_RUNTIME_URL = "http://127.0.0.1:5173";
const EMPTY_TASK_SUMMARIES: TaskSummary[] = [];
const EMPTY_LOADED_TASK_IDS = new Set<string>();

function isCompactSkillSelection(skill: MandatorySkillSelection): boolean {
  return skill.name === COMPACT_SKILL_NAME;
}

/**
 * Parse the serialized tool allowlist and determine whether ``web_search`` is
 * available to the chat surface.
 */
function canAccessWebSearchTool(
  toolIds: string | null | undefined,
): boolean {
  if (toolIds === undefined) {
    return false;
  }
  if (toolIds === null) {
    return true;
  }

  try {
    const parsed = JSON.parse(toolIds) as unknown;
    if (!Array.isArray(parsed)) {
      return false;
    }

    return parsed.some(
      (item) => typeof item === "string" && item.trim() === "web_search",
    );
  } catch {
    return false;
  }
}

/**
 * Convert enabled web-search bindings into lightweight selector options while
 * preserving backend ordering for deterministic defaults.
 */
function toWebSearchProviderOptions(
  bindings: WebSearchBinding[],
): ChatWebSearchProviderOption[] {
  return bindings
    .filter((binding) => binding.enabled)
    .map((binding) => ({
      key: binding.provider_key,
      name: binding.manifest.name,
      logoUrl: binding.manifest.logo_url ?? null,
    }));
}

function getToolEventPayload(
  event: ReactStreamEvent,
): { tool_calls?: unknown; tool_results?: unknown } | null {
  if (
    (event.type !== "tool_call" && event.type !== "tool_result") ||
    !event.data ||
    typeof event.data !== "object" ||
    Array.isArray(event.data)
  ) {
    return null;
  }
  return event.data as { tool_calls?: unknown; tool_results?: unknown };
}

function hasPendingToolExecutions(events: ReactStreamEvent[]): boolean {
  const toolCallIds = new Set<string>();
  const toolResultIds = new Set<string>();

  for (const event of events) {
    const payload = getToolEventPayload(event);
    if (!payload) {
      continue;
    }

    if (Array.isArray(payload.tool_calls)) {
      for (const item of payload.tool_calls) {
        if (!item || typeof item !== "object") {
          continue;
        }
        const id = (item as { id?: unknown }).id;
        if (typeof id === "string" && id.length > 0) {
          toolCallIds.add(id);
        }
      }
    }

    if (Array.isArray(payload.tool_results)) {
      for (const item of payload.tool_results) {
        if (!item || typeof item !== "object") {
          continue;
        }
        const id = (item as { tool_call_id?: unknown }).tool_call_id;
        if (typeof id === "string" && id.length > 0) {
          toolResultIds.add(id);
        }
      }
    }
  }

  return toolCallIds.size > 0 && toolResultIds.size < toolCallIds.size;
}

function SurfaceDevDebugContent({
  activeSurfaceSession,
  currentSessionId,
  isCreatingSurfaceSession,
  surfaceCreationError,
  onAttach,
}: {
  activeSurfaceSession: DevSurfaceSessionResponse | null;
  currentSessionId: string | null;
  isCreatingSurfaceSession: boolean;
  surfaceCreationError: string | null;
  onAttach: (runtimeUrl: string) => void;
}) {
  const [runtimeUrlInput, setRuntimeUrlInput] = useState(LOCAL_VITE_RUNTIME_URL);
  const isAttachDisabled = !currentSessionId || isCreatingSurfaceSession;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isAttachDisabled) {
      return;
    }

    onAttach(runtimeUrlInput);
  };

  return (
    <form className="space-y-3" onSubmit={handleSubmit}>
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <Label
            htmlFor="surface-runtime-url"
            className="text-xs font-medium text-muted-foreground"
          >
            Runtime URL
          </Label>
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex items-center text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none"
                  aria-label="Runtime URL details"
                >
                  <Info className="h-3.5 w-3.5 cursor-help" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed">
                Accepts either a dev server root such as{" "}
                <span className="font-mono text-foreground/80">
                  {LOCAL_VITE_RUNTIME_URL}
                </span>{" "}
                or a concrete entry page.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <ButtonGroup className="w-full">
          <Input
            id="surface-runtime-url"
            type="url"
            value={runtimeUrlInput}
            onChange={(event) => setRuntimeUrlInput(event.target.value)}
            aria-label="Runtime URL"
            autoComplete="off"
          />
          <Button
            type="submit"
            variant="outline"
            size="sm"
            disabled={isAttachDisabled}
            className="h-9 shrink-0"
          >
            {isCreatingSurfaceSession ? "Attaching..." : "Attatch"}
          </Button>
        </ButtonGroup>
      </div>

      {surfaceCreationError ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {surfaceCreationError}
        </div>
      ) : null}

      {activeSurfaceSession ? (
        <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground">
              {activeSurfaceSession.display_name}
            </span>
            <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-700 dark:text-amber-300">
              Dev
            </span>
          </div>
          <div className="mt-2">
            Attached to this chat session. Use the chat-header surface icon to
            open the dock.
          </div>
        </div>
      ) : null}
    </form>
  );
}

function normalizePreviewEndpoint(
  preview: unknown,
): PreviewEndpointResponse | null {
  if (!preview || typeof preview !== "object") {
    return null;
  }
  const previewId = (preview as { preview_id?: unknown }).preview_id;
  const sessionId = (preview as { session_id?: unknown }).session_id;
  const workspaceId = (preview as { workspace_id?: unknown }).workspace_id;
  const workspaceLogicalRoot = (
    preview as { workspace_logical_root?: unknown }
  ).workspace_logical_root;
  const title = (preview as { title?: unknown }).title;
  const port = (preview as { port?: unknown }).port;
  const path = (preview as { path?: unknown }).path;
  const hasLaunchRecipe = (preview as { has_launch_recipe?: unknown }).has_launch_recipe;
  const proxyUrl = (preview as { proxy_url?: unknown }).proxy_url;
  const createdAt = (preview as { created_at?: unknown }).created_at;

  if (
    typeof previewId !== "string" ||
    typeof sessionId !== "string" ||
    typeof workspaceId !== "string" ||
    typeof workspaceLogicalRoot !== "string" ||
    typeof title !== "string" ||
    typeof port !== "number" ||
    typeof path !== "string" ||
    typeof hasLaunchRecipe !== "boolean" ||
    typeof proxyUrl !== "string" ||
    typeof createdAt !== "string"
  ) {
    return null;
  }

  return {
    preview_id: previewId,
    session_id: sessionId,
    workspace_id: workspaceId,
    workspace_logical_root: workspaceLogicalRoot,
    title,
    port,
    path,
    has_launch_recipe: hasLaunchRecipe,
    proxy_url: proxyUrl,
    created_at: createdAt,
  };
}

function normalizePreviewEndpointList(
  payload: unknown,
): PreviewEndpointResponse[] {
  if (!Array.isArray(payload)) {
    return [];
  }
  return payload
    .map((item) => normalizePreviewEndpoint(item))
    .filter((item): item is PreviewEndpointResponse => item !== null);
}

function upsertPreviewEndpointList(
  previews: PreviewEndpointResponse[],
  nextPreview: PreviewEndpointResponse,
): PreviewEndpointResponse[] {
  const filtered = previews.filter(
    (preview) => preview.preview_id !== nextPreview.preview_id,
  );
  return [...filtered, nextPreview].sort((left, right) =>
    left.created_at.localeCompare(right.created_at),
  );
}

/**
 * Convert a session creation payload into the sidebar row shape.
 */
function toSessionListItem(session: SessionResponse): SessionListItem {
  return {
    session_id: session.session_id,
    agent_id: session.agent_id,
    type: session.type ?? "client",
    release_id: session.release_id,
    project_id: session.project_id ?? null,
    workspace_id: session.workspace_id ?? null,
    workspace_scope: session.workspace_scope ?? null,
    test_workspace_hash: session.test_workspace_hash ?? null,
    status: session.status,
    runtime_status: session.runtime_status ?? "idle",
    title: session.title,
    is_pinned: session.is_pinned,
    created_at: session.created_at,
    updated_at: session.updated_at,
  };
}

/**
 * Keep sidebar ordering consistent with the backend so optimistic updates do
 * not jump around after the next list refresh.
 */
function sortSessionsForSidebar(
  sessions: SessionListItem[],
): SessionListItem[] {
  return [...sessions].sort((left, right) => {
    if (left.is_pinned !== right.is_pinned) {
      return Number(right.is_pinned) - Number(left.is_pinned);
    }

    return Date.parse(right.updated_at) - Date.parse(left.updated_at);
  });
}

/**
 * Keep project ordering aligned with the freshest session activity underneath
 * each shared workspace instead of relying only on project metadata writes.
 */
function sortProjectsForSidebar(
  projects: ProjectResponse[],
  sessions: SessionListItem[],
): ProjectResponse[] {
  const latestSessionByProject = new Map<string, number>();
  for (const session of sessions) {
    if (!session.project_id) {
      continue;
    }
    const timestamp = Date.parse(session.updated_at);
    const previousTimestamp = latestSessionByProject.get(session.project_id) ?? 0;
    if (timestamp > previousTimestamp) {
      latestSessionByProject.set(session.project_id, timestamp);
    }
  }

  return [...projects].sort((left, right) => {
    const leftTimestamp = Math.max(
      Date.parse(left.updated_at),
      latestSessionByProject.get(left.project_id) ?? 0,
    );
    const rightTimestamp = Math.max(
      Date.parse(right.updated_at),
      latestSessionByProject.get(right.project_id) ?? 0,
    );
    return rightTimestamp - leftTimestamp;
  });
}

/**
 * Merge one updated session row into the local sidebar cache.
 */
function upsertSessionListItem(
  sessions: SessionListItem[],
  nextSession: SessionListItem,
): SessionListItem[] {
  return sortSessionsForSidebar([
    nextSession,
    ...sessions.filter(
      (existingSession) => existingSession.session_id !== nextSession.session_id,
    ),
  ]);
}

/**
 * Update one existing sidebar row without changing its relative order.
 */
function replaceSessionListItem(
  sessions: SessionListItem[],
  nextSession: SessionListItem,
): SessionListItem[] {
  return sessions.map((session) =>
    session.session_id === nextSession.session_id ? nextSession : session,
  );
}

/**
 * Applies one streamed session-title update without reordering the sidebar.
 *
 * Why: session ordering should remain controlled by the server's ``updated_at``
 * field so task activity and sidebar refreshes cannot drift apart.
 */
function applyStreamedSessionTitle(
  sessions: SessionListItem[],
  sessionId: string,
  title: string,
): SessionListItem[] {
  const existingSession = sessions.find((session) => session.session_id === sessionId);
  const nextTitle = title.trim();
  if (!existingSession || nextTitle.length === 0) {
    return sessions;
  }

  if (existingSession.title === nextTitle) {
    return sessions;
  }

  return replaceSessionListItem(sessions, {
    ...existingSession,
    title: nextTitle,
  });
}

/**
 * Narrows live plan payloads so the composer task panel can keep following the
 * active task after a history-based reconnect.
 */
function extractLiveCurrentPlan(event: ReactStreamEvent): PlanStepData[] | undefined {
  if (typeof event.data !== "object" || event.data === null || Array.isArray(event.data)) {
    return undefined;
  }

  if (event.type === "message") {
    const messagePayload = event.data as { current_plan?: PlanStepData[] };
    return Array.isArray(messagePayload.current_plan)
      ? messagePayload.current_plan
      : undefined;
  }

  if (event.type === "plan_update") {
    const planPayload = event.data as { plan?: PlanStepData[] };
    return Array.isArray(planPayload.plan) ? planPayload.plan : undefined;
  }

  return undefined;
}

/**
 * Reads a streamed assistant-proposed session title when one is present.
 */
function extractSessionTitle(event: ReactStreamEvent): string | undefined {
  if (typeof event.data !== "object" || event.data === null || Array.isArray(event.data)) {
    return undefined;
  }

  const sessionTitle = (event.data as { session_title?: unknown }).session_title;
  return typeof sessionTitle === "string" && sessionTitle.trim().length > 0
    ? sessionTitle.trim()
    : undefined;
}

/**
 * Finds the latest assistant clarify message for a given task so the composer
 * can render a readable reply context instead of a bare task identifier.
 */
function findReplyTarget(
  messages: ChatMessage[],
  taskId: string | null,
): ChatReplyTarget | null {
  if (!taskId) {
    return null;
  }

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role === "assistant" &&
      message.task_id === taskId &&
      isClarifyMessage(message) &&
      message.content.trim().length > 0
    ) {
      return {
        taskId,
        question: message.content,
      };
    }
  }

  return null;
}

/**
 * Finds the latest persisted waiting-input task so restored sessions can reopen
 * clarify reply mode without waiting for a fresh SSE event.
 */
function findLatestWaitingReplyTaskId(messages: ChatMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message.role === "assistant" &&
      typeof message.task_id === "string" &&
      message.status === "waiting_input" &&
      isClarifyMessage(message) &&
      !extractSkillChangeApprovalRequest(message)
    ) {
      return message.task_id;
    }
  }

  return null;
}

function SessionLoadingOverlay({ isActive }: { isActive: boolean }) {
  const [isRendered, setIsRendered] = useState(isActive);
  const [isEntered, setIsEntered] = useState(false);

  useEffect(() => {
    if (isActive) {
      setIsRendered(true);
      const firstFrame = window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          setIsEntered(true);
        });
      });
      return () => {
        window.cancelAnimationFrame(firstFrame);
      };
    }

    setIsEntered(false);
    const timeout = window.setTimeout(() => {
      setIsRendered(false);
    }, SESSION_LOADING_OVERLAY_TRANSITION_MS);
    return () => {
      window.clearTimeout(timeout);
    };
  }, [isActive]);

  if (!isRendered) {
    return null;
  }

  return (
    <div
      className="absolute inset-0 z-10 flex items-center justify-center"
      aria-hidden={!isActive}
      data-testid="session-loading-overlay"
    >
      <div
        className="absolute inset-0 transition-[opacity,backdrop-filter,background-color] duration-500 ease-in-out"
        style={{
          opacity: isEntered ? 1 : 0,
          transitionDuration: `${SESSION_LOADING_OVERLAY_TRANSITION_MS}ms`,
          backgroundColor: "transparent",
          backdropFilter: isEntered ? "blur(14px)" : "blur(0px)",
        }}
        data-testid="session-loading-mask"
      />
      <Spinner
        size={20}
        className="relative z-10"
        data-testid="session-loading-spinner"
      />
    </div>
  );
}

/**
 * Coordinates the page-scoped chat state and delegates visual rendering to smaller components.
 */
function ChatContainer({
  agentId,
  sessionType = "client",
  initialSessionId,
  testSnapshot,
  testSnapshotHash,
  agentName,
  agentToolIds,
  primaryLlmId,
  sessionIdleTimeoutMinutes,
  compactThresholdPercent,
  sidebarNavigationItems,
  sidebarTitleIcon,
  sidebarTitle,
  sidebarFooter,
  agentClientState,
  onRuntimeDebugChange,
  onSurfaceDevAttached,
  showCompactDebug,
  initialLlm,
  initialSessions,
  initialProjects,
  initialChatSurfaces,
  initialWebSearchProviders,
}: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const {
    runtime: chatSessionRuntime,
    runtimeRef: chatSessionRuntimeRef,
    dispatch: dispatchChatSessionRuntime,
  } = useChatSessionRuntime();
  const taskSummaries =
    chatSessionRuntime?.taskSummaries ?? EMPTY_TASK_SUMMARIES;
  const loadedTaskIds =
    chatSessionRuntime?.loadedTaskIds ?? EMPTY_LOADED_TASK_IDS;
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [pendingMidTaskInput, setPendingMidTaskInput] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedRecursions, setExpandedRecursions] = useState<
    Record<string, boolean>
  >({});
  const [replyTaskId, setReplyTaskId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionListItem[]>(
    initialSessions ?? [],
  );
  const [projects, setProjects] = useState<ProjectResponse[]>(
    initialProjects ?? [],
  );
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [accessProjectId, setAccessProjectId] = useState<string | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState<boolean>(false);
  const [isInitialized, setIsInitialized] = useState<boolean>(false);
  const [staleSessionId, setStaleSessionId] = useState<string | null>(null);
  const [migratedSessionId, setMigratedSessionId] = useState<string | null>(null);
  const [isMigratingStaleSession, setIsMigratingStaleSession] = useState(false);
  const [isStaleBannerDismissed, setIsStaleBannerDismissed] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isExtensionDockOpen, setIsExtensionDockOpen] = useState(false);
  const [isExtensionDockMounted, setIsExtensionDockMounted] = useState(false);
  const [dockPanelSize, setDockPanelSize] = useState(58);
  const [renderedDockPanelSize, setRenderedDockPanelSize] = useState(0);
  const [isCreatingSurfaceSession, setIsCreatingSurfaceSession] =
    useState(false);
  const [surfaceCreationError, setSurfaceCreationError] = useState<
    string | null
  >(null);
  const [installedChatSurfaces, setInstalledChatSurfaces] = useState<
    InstalledChatSurfaceDescriptor[]
  >(
    initialChatSurfaces?.map((s) => ({
      installationId: s.installation_id,
      packageId: s.package_id,
      surfaceKey: s.surface_key,
      displayName: s.display_name,
      logoUrl: s.logo_url,
      description: s.description ?? "",
      minWidth: s.min_width,
      icon: s.icon,
    })) ?? [],
  );
  const [activeInstalledSurface, setActiveInstalledSurface] =
    useState<InstalledChatSurfaceDescriptor | null>(null);
  const [activeInstalledSurfaceSession, setActiveInstalledSurfaceSession] =
    useState<InstalledSurfaceSessionResponse | null>(null);
  const [activeSurfaceSession, setActiveSurfaceSession] =
    useState<DevSurfaceSessionResponse | null>(null);
  const [previewEndpoints, setPreviewEndpoints] = useState<
    PreviewEndpointResponse[]
  >([]);
  const [activePreviewEndpoint, setActivePreviewEndpoint] =
    useState<PreviewEndpointResponse | null>(null);
  const [reconnectablePreviewSuggestion, setReconnectablePreviewSuggestion] =
    useState<PreviewEndpointResponse | null>(null);
  const [activeContextTaskId, setActiveContextTaskId] = useState<string | null>(
    null,
  );
  const [activeContextIteration, setActiveContextIteration] = useState<
    number | null
  >(null);
  const [contextUsage, setContextUsage] =
    useState<ReactContextUsageSummary | null>(null);
  const [isContextUsageLoading, setIsContextUsageLoading] =
    useState<boolean>(false);
  const [compactStatusMessage, setCompactStatusMessage] = useState<string | null>(
    null,
  );
  const [sessionRuntimeDebug, setSessionRuntimeDebug] =
    useState<ReactSessionRuntimeDebug | null>(null);
  const [isRuntimeDebugLoading, setIsRuntimeDebugLoading] =
    useState<boolean>(false);
  const [runtimeDebugError, setRuntimeDebugError] = useState<string | null>(null);
  const [automationProposal, setAutomationProposal] =
    useState<AutomationProposal | null>(null);
  const [isAutomationDialogOpen, setIsAutomationDialogOpen] = useState(false);
  const [automationAgents, setAutomationAgents] = useState<Agent[]>([]);
  const [webSearchProviders, setWebSearchProviders] = useState<
    ChatWebSearchProviderOption[]
  >(
    initialWebSearchProviders?.map((p) => ({
      key: p.provider_key,
      name: p.name,
      logoUrl: p.logo_url,
    })) ?? [],
  );
  const [selectedWebSearchProvider, setSelectedWebSearchProvider] = useState<
    string | null
  >(null);
  const [selectedThinkingMode, setSelectedThinkingMode] =
    useState<ChatThinkingMode | null>(null);
  const [runtimeSkills, setRuntimeSkills] = useState<MandatorySkillSelection[]>(
    [],
  );
  const [selectedMandatorySkills, setSelectedMandatorySkills] = useState<
    MandatorySkillSelection[]
  >([]);
  const [isManualCompacting, setIsManualCompacting] = useState(false);
  const [composerResetSignal, setComposerResetSignal] = useState(0);
  const [composerFocusSignal, setComposerFocusSignal] = useState(0);
  const messagesRef = useRef<ChatMessage[]>([]);
  const draftMessageRef = useRef("");
  const currentSessionIdRef = useRef<string | null>(null);
  const sessionStreamAbortControllerRef = useRef<AbortController | null>(null);
  const sessionStreamReconnectTimerRef = useRef<number | null>(null);
  const sessionStreamReconnectCountRef = useRef(0);
  const SESSION_STREAM_MAX_RECONNECTS = 10;
  const sessionEventCursorRef = useRef(0);
  const historyReloadInFlightRef = useRef(false);
  const liveAssistantMessageIdRef = useRef<string | null>(null);
  const liveTaskIdRef = useRef<string | null>(null);
  const liveRecursionRef = useRef<RecursionRecord | null>(null);
  const contextUsageRequestIdRef = useRef(0);
  const contextUsageDebounceTimerRef = useRef<number | null>(null);
  const runtimeDebugRequestIdRef = useRef(0);
  const compactStatusStartedAtRef = useRef<number | null>(null);
  const compactStatusClearTimerRef = useRef<number | null>(null);
  const dockTransitionTimerRef = useRef<number | null>(null);
  const dockOpenFrameRef = useRef<number | null>(null);
  const stoppedTaskIdsRef = useRef<Set<string>>(new Set());
  const processedPreviewIntentIdsRef = useRef<Set<string>>(new Set());
  const pendingPreviewSurfaceOpenIdRef = useRef<string | null>(null);
  const openWorkspacePreviewIntentRef = useRef(
    (_previewIntent: {
      preview: PreviewEndpointResponse;
      availablePreviews: PreviewEndpointResponse[];
      activePreviewId: string | null;
    }) => {},
  );
  const actionHandlerContextRef = useRef<ActionHandlerContext>({
    openWorkspacePreviewIntent: (intent: {
      preview: unknown;
      availablePreviews: unknown[];
      activePreviewId: string | null;
    }) => {
      const preview = normalizePreviewEndpoint(intent.preview);
      if (!preview) return;
      openWorkspacePreviewIntentRef.current({
        preview,
        availablePreviews: normalizePreviewEndpointList(intent.availablePreviews),
        activePreviewId: intent.activePreviewId,
      });
    },
    openAutomationProposalDialog: (proposal) => {
      setAutomationProposal(proposal);
      setIsAutomationDialogOpen(true);
      void getAgents().then(setAutomationAgents).catch(() => {});
    },
  });
  const isCompactMode = useMemo(
    () => selectedMandatorySkills.some(isCompactSkillSelection),
    [selectedMandatorySkills],
  );
  const manualCompactSkillNames = useMemo(
    () =>
      selectedMandatorySkills
        .filter((skill) => !isCompactSkillSelection(skill))
        .map((skill) => skill.name),
    [selectedMandatorySkills],
  );
  const availableMandatorySkills = useMemo(() => {
    const visibleSkills = runtimeSkills.filter(
      (skill) => !isCompactSkillSelection(skill),
    );
    if (!currentSessionId) {
      return visibleSkills;
    }
    return [COMPACT_SKILL_SELECTION, ...visibleSkills];
  }, [currentSessionId, runtimeSkills]);

  const {
    pendingFiles,
    readyPendingFiles,
    hasUploadingFiles,
    supportsImageInput,
    supportsThinkingSelector,
    thinkingModes,
    defaultThinkingMode,
    imageInputRef,
    documentInputRef,
    removePendingFile,
    clearPendingFiles,
    discardReadyPendingFiles,
    handleFileInputChange,
    handleDocumentInputChange,
    handlePaste,
  } = useChatUploads(primaryLlmId, initialLlm);
  const {
    scrollContainerRef,
    handleScroll,
    prepareForProgrammaticScroll,
    scrollToMessage,
    pauseAutoScroll,
  } = useChatAutoScroll(messages);

  // Attach auto-scroll handler to the Viewport (the actual scrolling element).
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;
    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, [handleScroll, scrollContainerRef]);

  const sessionIdleTimeoutMs = resolveSessionIdleTimeoutMs(
    sessionIdleTimeoutMinutes,
  );
  const canUseWebSearch = canAccessWebSearchTool(agentToolIds);

  /**
   * Surface development sessions are scoped to one chat session so the debug
   * tooling cannot accidentally keep editing the wrong workspace after a pivot.
   */
  useEffect(() => {
    if (dockTransitionTimerRef.current !== null) {
      window.clearTimeout(dockTransitionTimerRef.current);
      dockTransitionTimerRef.current = null;
    }
    if (dockOpenFrameRef.current !== null) {
      window.cancelAnimationFrame(dockOpenFrameRef.current);
      dockOpenFrameRef.current = null;
    }
    setActiveSurfaceSession(null);
    setActiveInstalledSurface(null);
    setActiveInstalledSurfaceSession(null);
    setPreviewEndpoints([]);
    setActivePreviewEndpoint(null);
    setReconnectablePreviewSuggestion(null);
    setSurfaceCreationError(null);
    setIsExtensionDockOpen(false);
    setIsExtensionDockMounted(false);
    setRenderedDockPanelSize(0);
    processedPreviewIntentIdsRef.current = new Set();
    pendingPreviewSurfaceOpenIdRef.current = null;
  }, [currentSessionId]);

  const clearDockAnimationTimers = useCallback(() => {
    if (dockTransitionTimerRef.current !== null) {
      window.clearTimeout(dockTransitionTimerRef.current);
      dockTransitionTimerRef.current = null;
    }
    if (dockOpenFrameRef.current !== null) {
      window.cancelAnimationFrame(dockOpenFrameRef.current);
      dockOpenFrameRef.current = null;
    }
  }, []);

  const handleExtensionDockOpenChange = useCallback(
    (nextOpen: boolean) => {
      clearDockAnimationTimers();
      setIsExtensionDockOpen(nextOpen);

      if (nextOpen) {
        setIsExtensionDockMounted(true);
        dockOpenFrameRef.current = window.requestAnimationFrame(() => {
          setRenderedDockPanelSize(dockPanelSize);
          dockOpenFrameRef.current = null;
        });
        return;
      }

      setRenderedDockPanelSize(0);
      dockTransitionTimerRef.current = window.setTimeout(() => {
        setIsExtensionDockMounted(false);
        dockTransitionTimerRef.current = null;
      }, DOCK_TRANSITION_MS);
    },
    [clearDockAnimationTimers, dockPanelSize],
  );

  useEffect(() => {
    return () => {
      clearDockAnimationTimers();
    };
  }, [clearDockAnimationTimers]);

  useEffect(() => {
    if (isExtensionDockOpen) {
      setRenderedDockPanelSize(dockPanelSize);
    }
  }, [dockPanelSize, isExtensionDockOpen]);

  /**
   * Clears pending draft estimation so only the latest idle draft reaches the
   * context-usage endpoint.
   */
  const clearContextUsageDebounceTimer = useCallback(() => {
    if (contextUsageDebounceTimerRef.current !== null) {
      window.clearTimeout(contextUsageDebounceTimerRef.current);
      contextUsageDebounceTimerRef.current = null;
    }
  }, []);

  /**
   * Keep the selected thinking mode aligned with the primary LLM capability set.
   */
  useEffect(() => {
    if (!supportsThinkingSelector || thinkingModes.length === 0) {
      setSelectedThinkingMode(null);
      return;
    }

    setSelectedThinkingMode((previous) => {
      if (previous && thinkingModes.includes(previous)) {
        return previous;
      }
      return defaultThinkingMode;
    });
  }, [defaultThinkingMode, supportsThinkingSelector, thinkingModes]);

  /**
   * Cancels any pending delayed compact-status clear so the latest status wins.
   */
  const clearCompactStatusTimer = useCallback(() => {
    if (compactStatusClearTimerRef.current !== null) {
      window.clearTimeout(compactStatusClearTimerRef.current);
      compactStatusClearTimerRef.current = null;
    }
  }, []);

  /**
   * Shows compact progress and records when it became visible.
   */
  const showCompactStatus = useCallback(
    (message: string) => {
      clearCompactStatusTimer();
      compactStatusStartedAtRef.current = Date.now();
      setCompactStatusMessage(message);
    },
    [clearCompactStatusTimer],
  );

  /**
   * Removes compact progress immediately during session resets or fatal errors.
   */
  const clearCompactStatusImmediately = useCallback(() => {
    clearCompactStatusTimer();
    compactStatusStartedAtRef.current = null;
    setCompactStatusMessage(null);
  }, [clearCompactStatusTimer]);

  /**
   * Keeps compact progress visible long enough for people to notice it.
   */
  const clearCompactStatusWithMinimumDelay = useCallback(() => {
    clearCompactStatusTimer();
    const startedAt = compactStatusStartedAtRef.current;
    const clearStatus = () => {
      compactStatusStartedAtRef.current = null;
      compactStatusClearTimerRef.current = null;
      setCompactStatusMessage(null);
    };
    if (startedAt === null) {
      clearStatus();
      return;
    }

    const elapsedMs = Date.now() - startedAt;
    const remainingMs = Math.max(COMPACT_STATUS_MIN_VISIBLE_MS - elapsedMs, 0);
    if (remainingMs === 0) {
      clearStatus();
      return;
    }

    compactStatusClearTimerRef.current = window.setTimeout(
      clearStatus,
      remainingMs,
    );
  }, [clearCompactStatusTimer]);

  /**
   * Loads the latest session runtime debug payload for the floating compact inspector.
   */
  const loadSessionRuntimeDebug = useCallback(
    async (sessionId: string | null) => {
      const requestId = runtimeDebugRequestIdRef.current + 1;
      runtimeDebugRequestIdRef.current = requestId;

      if (!sessionId) {
        setSessionRuntimeDebug(null);
        setRuntimeDebugError(null);
        setIsRuntimeDebugLoading(false);
        return;
      }

      setIsRuntimeDebugLoading(true);
      setRuntimeDebugError(null);
      try {
        const payload = await getReactSessionRuntimeDebug(sessionId);
        if (
          runtimeDebugRequestIdRef.current === requestId &&
          currentSessionIdRef.current === sessionId
        ) {
          setSessionRuntimeDebug(payload);
        }
      } catch (debugError) {
        console.error("Failed to load session runtime debug:", debugError);
        if (
          runtimeDebugRequestIdRef.current === requestId &&
          currentSessionIdRef.current === sessionId
        ) {
          setSessionRuntimeDebug(null);
          setRuntimeDebugError("Failed to load compact debug data");
        }
      } finally {
        if (
          runtimeDebugRequestIdRef.current === requestId &&
          currentSessionIdRef.current === sessionId
        ) {
          setIsRuntimeDebugLoading(false);
        }
      }
    },
    [],
  );

  const standaloneSessions = useMemo(
    () =>
      sortSessionsForSidebar(
        sessions.filter((session) => !session.project_id),
      ),
    [sessions],
  );
  const sidebarProjects: ChatSidebarProjectItem[] = useMemo(
    () =>
      sortProjectsForSidebar(projects, sessions).map((project) => ({
        ...project,
        sessions: sortSessionsForSidebar(
          sessions.filter((session) => session.project_id === project.project_id),
        ),
      })),
    [projects, sessions],
  );

  /**
   * Reload project and session navigation data so sidebar metadata stays fresh
   * after task activity or workspace management actions.
   */
  const refreshSidebarData = useCallback(
    async (): Promise<{
      projects: ProjectResponse[];
      sessions: SessionListItem[];
    }> => {
      const [sessionResponse, projectResponse] = await Promise.all([
        listSessions(agentId, 50, { type: sessionType }),
        listProjects(agentId),
      ]);
      setSessions(sessionResponse.sessions);
      setProjects(projectResponse.projects);
      return {
        projects: projectResponse.projects,
        sessions: sessionResponse.sessions,
      };
    },
    [agentId, sessionType],
  );

  /**
   * Commits a fully prepared message snapshot to both React state and the
   * synchronous ref mirror used by the live SSE merger.
   */
  const commitMessages = useCallback((nextMessages: ChatMessage[]) => {
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
  }, []);

  /**
   * Applies one message-state update synchronously so consecutive SSE events can
   * build on the latest merged recursion snapshot before React flushes a render.
   */
  const updateMessages = useCallback(
    (
      updater: (previousMessages: ChatMessage[]) => ChatMessage[],
    ): ChatMessage[] => {
      const nextMessages = updater(messagesRef.current);
      commitMessages(nextMessages);
      return nextMessages;
    },
    [commitMessages],
  );

  /**
   * Stops the current session event stream without changing task state on the server.
   */
  const stopSessionStream = useCallback(() => {
    if (sessionStreamReconnectTimerRef.current !== null) {
      window.clearTimeout(sessionStreamReconnectTimerRef.current);
      sessionStreamReconnectTimerRef.current = null;
    }
    if (sessionStreamAbortControllerRef.current) {
      sessionStreamAbortControllerRef.current.abort();
      sessionStreamAbortControllerRef.current = null;
    }
    sessionStreamReconnectCountRef.current = 0;
  }, []);

  /**
   * Rebuilds in-memory tracking refs from the latest rendered message list.
   *
   * Why: reconnectable session streams can resume against history-loaded
   * messages, so task-local refs must be recoverable from persisted UI state.
   */
  const syncLiveRefsFromMessages = useCallback((nextMessages: ChatMessage[]) => {
    stoppedTaskIdsRef.current = new Set(
      nextMessages
        .filter(
          (message) =>
            message.role === "assistant" &&
            message.status === "stopped" &&
            typeof message.task_id === "string",
        )
        .map((message) => message.task_id as string),
    );

    const runningAssistant = [...nextMessages]
      .reverse()
      .find(
        (message) =>
          message.role === "assistant" &&
          message.task_id &&
          message.status === "running",
      );
    const activeRecursion = [...(runningAssistant?.recursions ?? [])]
      .reverse()
      .find((recursion) => recursion.status === "running");

    liveAssistantMessageIdRef.current = runningAssistant?.id ?? null;
    liveTaskIdRef.current = runningAssistant?.task_id ?? null;
    liveRecursionRef.current = activeRecursion ?? null;
  }, []);

  /**
   * Rehydrates the visible timeline and task-scoped affordances from a
   * persisted history snapshot, including clarify reply mode.
   */
  const applyHistoryMessages = useCallback(
    (nextMessages: ChatMessage[]) => {
      syncLiveRefsFromMessages(nextMessages);
      setReplyTaskId(findLatestWaitingReplyTaskId(nextMessages));
      setIsStreaming(
        nextMessages.some(
          (message) =>
            message.role === "assistant" && message.status === "running",
        ),
      );
      commitMessages(nextMessages);
    },
    [commitMessages, syncLiveRefsFromMessages],
  );

  const isTaskLoaded = useCallback((taskId: string) => {
    return chatSessionRuntimeRef.current?.loadedTaskIds.has(taskId) ?? false;
  }, [chatSessionRuntimeRef]);

  const canLoadOlderTasks = useCallback(() => {
    const runtime = chatSessionRuntimeRef.current;
    return Boolean(
      runtime?.olderStatus === "idle" && runtime.oldestLoadedTaskId,
    );
  }, [chatSessionRuntimeRef]);

  const isOlderTaskLoadInFlight = useCallback(() => {
    return chatSessionRuntimeRef.current?.olderStatus === "loading";
  }, [chatSessionRuntimeRef]);

  const getMessageContentTop = useCallback(
    (container: HTMLElement, element: HTMLElement): number | null => {
      const contentElement = container.firstElementChild as HTMLElement | null;
      if (!contentElement) return null;

      return (
        element.getBoundingClientRect().top -
        contentElement.getBoundingClientRect().top
      );
    },
    [],
  );

  const captureFirstVisibleMessageAnchor = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return null;

    const containerRect = container.getBoundingClientRect();
    const messageElements = Array.from(
      container.querySelectorAll<HTMLElement>("[data-message-id]"),
    );

    for (const element of messageElements) {
      const rect = element.getBoundingClientRect();
      if (rect.bottom > containerRect.top && rect.top < containerRect.bottom) {
        const contentTop = getMessageContentTop(container, element);
        if (contentTop === null) return null;

        return {
          messageId: element.dataset.messageId ?? "",
          contentTop,
        };
      }
    }

    return null;
  }, [getMessageContentTop, scrollContainerRef]);

  const restoreVisibleMessageAnchor = useCallback(
    (anchor: { messageId: string; contentTop: number } | null) => {
      if (!anchor || anchor.messageId.length === 0) return;

      const container = scrollContainerRef.current;
      if (!container) return;

      const element = container.querySelector<HTMLElement>(
        `[data-message-id="${anchor.messageId}"]`,
      );
      if (!element) return;

      const nextContentTop = getMessageContentTop(container, element);
      if (nextContentTop === null) return;

      container.scrollTop += nextContentTop - anchor.contentTop;
    },
    [getMessageContentTop, scrollContainerRef],
  );

  /**
   * Hydrates pagination state from a full-history API response and renders
   * the returned tasks as messages.  Used by every code-path that calls
   * getFullSessionHistory.
   */
  const loadHistoryResponse = useCallback(
    (history: FullSessionHistoryResponse, isInitialLoad: boolean) => {
      if (history.session_id !== currentSessionIdRef.current) {
        return [];
      }

      if (isInitialLoad) {
        dispatchChatSessionRuntime({
          type: "HYDRATE_HISTORY",
          sessionId: history.session_id,
          taskSummaries: history.task_summaries,
          tasks: history.tasks,
          hasMoreOlder: history.has_more_older,
          pageSize: CHAT_HISTORY_PAGE_SIZE,
        });
        prepareForProgrammaticScroll();
      }

      const nextMessages = buildMessagesFromHistory(history.tasks);
      if (isInitialLoad) {
        applyHistoryMessages(nextMessages);
      }
      return nextMessages;
    },
    [
      applyHistoryMessages,
      dispatchChatSessionRuntime,
      prepareForProgrammaticScroll,
    ],
  );

  /**
   * Loads older tasks when the user scrolls near the top. Prepends the
   * returned messages and compensates scroll position so the viewport
   * stays visually stable.
   */
  const loadOlderTasks = useCallback(
    async (
      limit: number,
      options: { preserveScroll?: boolean } = {},
    ) => {
      const sessionId = currentSessionIdRef.current;
      const runtime = chatSessionRuntimeRef.current;
      if (
        !sessionId ||
        !runtime ||
        runtime.sessionId !== sessionId ||
        runtime.olderStatus !== "idle" ||
        !runtime.oldestLoadedTaskId
      ) {
        return [];
      }

      const shouldPreserveScroll = options.preserveScroll ?? true;
      dispatchChatSessionRuntime({ type: "START_LOAD_OLDER", sessionId });
      pauseAutoScroll();
      const visibleAnchor = shouldPreserveScroll
        ? captureFirstVisibleMessageAnchor()
        : null;

      try {
        const history = await getFullSessionHistory(sessionId, {
          limit,
          beforeTaskId: runtime.oldestLoadedTaskId,
        });
        dispatchChatSessionRuntime({
          type: "APPLY_OLDER_PAGE",
          sessionId,
          tasks: history.tasks,
          hasMoreOlder: history.has_more_older,
        });
        if (history.tasks.length === 0) {
          return [];
        }

        const olderMsgs = loadHistoryResponse(history, false);
        const loadedTaskIds = history.tasks.map((task) => task.task_id);

        if (shouldPreserveScroll) {
          flushSync(() => {
            updateMessages((prev) => [...olderMsgs, ...prev]);
          });
          restoreVisibleMessageAnchor(visibleAnchor);
        } else {
          updateMessages((prev) => [...olderMsgs, ...prev]);
        }
        return loadedTaskIds;
      } catch (err) {
        console.error("Failed to load older tasks:", err);
        dispatchChatSessionRuntime({ type: "FAIL_LOAD_OLDER", sessionId });
        return [];
      }
    },
    [
      captureFirstVisibleMessageAnchor,
      chatSessionRuntimeRef,
      dispatchChatSessionRuntime,
      loadHistoryResponse,
      pauseAutoScroll,
      restoreVisibleMessageAnchor,
      updateMessages,
    ],
  );

  const { isLoadingOlder, loadUntilTask } = useScrollUpPagination({
    scrollContainerRef,
    messages,
    canLoadOlder: canLoadOlderTasks,
    isOlderLoading: isOlderTaskLoadInFlight,
    loadOlderTasks,
    isTaskLoaded,
  });

  /**
   * Handles anchor-dot navigation. For loaded rounds, scrolls directly.
   * For unloaded rounds, loads batches until the target is found, then scrolls.
   */
  const handleNavigateToRound = useCallback(
    async (round: ConversationRound) => {
      if (round.isLoaded) {
        scrollToMessage(round.userMessageId);
        return;
      }
      const found = await loadUntilTask(round.taskId);
      if (found) {
        requestAnimationFrame(() => scrollToMessage(round.userMessageId));
      }
    },
    [scrollToMessage, loadUntilTask],
  );

  /**
   * Applies a local stopped state immediately so the chat surface acknowledges
   * the user's stop request before the backend finishes unwinding the iteration.
   */
  const markTaskStopped = useCallback(
    (taskId: string, timestamp: string) => {
      stoppedTaskIdsRef.current.add(taskId);
      setIsStreaming(false);
      setActiveContextTaskId(null);
      setActiveContextIteration(null);
      liveAssistantMessageIdRef.current = null;
      liveTaskIdRef.current = null;
      liveRecursionRef.current = null;

      updateMessages((messagesSnapshot) =>
        messagesSnapshot.map((message) => {
          if (message.task_id !== taskId) {
            return message;
          }

          return {
            ...message,
            status: "stopped" as const,
            timestamp,
            recursions: (message.recursions || []).map((recursion) =>
              recursion.status === "running"
                ? {
                    ...recursion,
                    status: "stopped" as const,
                    endTime: timestamp,
                  }
                : recursion,
            ),
          };
        }),
      );
    },
    [updateMessages],
  );

  /**
   * Applies one normalized ReAct event onto the visible conversation state.
   */
  const applyStreamEvent = useCallback(
    (event: ReactStreamEvent) => {
      if (typeof event.event_id === "number") {
        sessionEventCursorRef.current = Math.max(
          sessionEventCursorRef.current,
          event.event_id,
        );
      }

      if (
        stoppedTaskIdsRef.current.has(event.task_id) &&
        event.type !== "task_cancelled"
      ) {
        return;
      }

      // Unified pivot_action dispatch for tool_result events.
      if (
        event.type === "tool_result" &&
        event.data &&
        typeof event.data === "object"
      ) {
        const toolResults = (event.data as { tool_results?: unknown })
          .tool_results;
        dispatchPivotActionFromToolResult(
          toolResults,
          actionHandlerContextRef.current,
        );

        // Refresh debug panel after file-related tool results so the Files
        // tab stays current during a running task.
        if (showCompactDebug && currentSessionIdRef.current) {
          void loadSessionRuntimeDebug(currentSessionIdRef.current);
        }
      }

      if (event.type === "compact_start") {
        showCompactStatus("Compacting context. Please wait before stopping.");
        return;
      }

      if (event.type === "compact_complete") {
        const compactData =
          typeof event.data === "object" && event.data !== null
            ? (event.data as { usage_after?: ReactContextUsageSummary })
            : undefined;
        if (compactData?.usage_after) {
          setContextUsage(compactData.usage_after);
        }
        void loadSessionRuntimeDebug(currentSessionIdRef.current);
        clearCompactStatusWithMinimumDelay();
        return;
      }

      if (event.type === "compact_failed") {
        clearCompactStatusWithMinimumDelay();
        return;
      }

      // Mid-task user input was consumed by the engine.
      if (event.type === "user_input") {
        const msg = (event.data as { message?: string })?.message ?? "";
        setPendingMidTaskInput(null);
        if (msg) {
          // The input was dequeued at the start of iteration N (event.iteration),
          // but the bubble should appear after recursion N-1 (the one that just finished).
          const targetIdx = Math.max(0, event.iteration - 1);
          updateMessages((prev) =>
            prev.map((m) => {
              if (m.role !== "assistant" || m.task_id !== event.task_id) {
                return m;
              }
              const base = m.midTaskInputs ?? [];
              const len = Math.max(base.length, m.recursions?.length ?? 0, targetIdx + 1);
              const inputs: ({ message: string; timestamp: string } | undefined)[] = Array.from(
                { length: len },
                (_, idx) => base[idx] ?? undefined,
              );
              inputs[targetIdx] = { message: msg, timestamp: event.timestamp };
              return {
                ...m,
                midTaskInputs: inputs,
              };
            }),
          );
        }
        return;
      }

      // Mid-task user input was discarded (task ended before consumption).
      if (event.type === "user_input_discarded") {
        setPendingMidTaskInput(null);
        setComposerFocusSignal((prev) => prev + 1);
        return;
      }

      const targetTaskId = event.task_id;
      const previous = messagesRef.current;
      const liveMessage = liveAssistantMessageIdRef.current
        ? previous.find(
            (message) => message.id === liveAssistantMessageIdRef.current,
          ) ?? null
        : null;
      let targetMessageId =
        liveMessage &&
        (liveMessage.task_id === targetTaskId ||
          liveMessage.task_id === undefined ||
          liveTaskIdRef.current === targetTaskId)
          ? liveMessage.id
          : null;

      if (!targetMessageId) {
        targetMessageId =
          [...previous].reverse().find(
            (message) =>
              message.role === "assistant" && message.task_id === targetTaskId,
          )?.id ?? null;
      }

      if (!targetMessageId) {
        if (
          currentSessionId &&
          !historyReloadInFlightRef.current &&
          event.task_id.length > 0
        ) {
          historyReloadInFlightRef.current = true;
          void getFullSessionHistory(currentSessionId, {
            limit: CHAT_HISTORY_PAGE_SIZE,
          })
            .then((history) => {
              loadHistoryResponse(history, true);
              sessionEventCursorRef.current = Math.max(
                sessionEventCursorRef.current,
                history.last_event_id,
              );
            })
            .catch((historyError) => {
              console.error(
                "Failed to hydrate session after unseen task event:",
                historyError,
              );
            })
            .finally(() => {
              historyReloadInFlightRef.current = false;
            });
        }
        return;
      }

      const targetMessage =
        previous.find((message) => message.id === targetMessageId) ?? null;
      const matchingRecursionFromMessage = [...(targetMessage?.recursions ?? [])]
        .reverse()
        .find((recursion) => {
          if (event.trace_id && recursion.trace_id) {
            return recursion.trace_id === event.trace_id;
          }
          return recursion.iteration === event.iteration;
        });
      const runningRecursionFromMessage = [...(targetMessage?.recursions ?? [])]
        .reverse()
        .find((recursion) => {
          if (recursion.status !== "running") {
            return false;
          }
          if (event.trace_id && recursion.trace_id) {
            return recursion.trace_id === event.trace_id;
          }
          return true;
        });
      const currentRecursionFromRefs =
        liveTaskIdRef.current === event.task_id &&
        liveRecursionRef.current &&
        ((!event.trace_id && liveRecursionRef.current.iteration === event.iteration) ||
          (event.trace_id &&
            liveRecursionRef.current.trace_id === event.trace_id))
          ? liveRecursionRef.current
          : null;

      const sessionTitle = extractSessionTitle(event);
      const streamedSessionId = currentSessionIdRef.current;
      if (sessionTitle && streamedSessionId) {
        setSessions((previousSessions) =>
          applyStreamedSessionTitle(previousSessions, streamedSessionId, sessionTitle),
        );
      }

      if (event.type === "recursion_start") {
        setIsStreaming(true);
        setActiveContextTaskId(event.task_id);
        setActiveContextIteration(event.iteration);

        if (matchingRecursionFromMessage) {
          if (matchingRecursionFromMessage.status !== "running") {
            return;
          }

          const resumedRecursion: RecursionRecord = {
            ...matchingRecursionFromMessage,
            trace_id: event.trace_id ?? matchingRecursionFromMessage.trace_id,
            events: matchingRecursionFromMessage.events.some(
              (existingEvent) =>
                existingEvent.type === "recursion_start" &&
                existingEvent.iteration === event.iteration &&
                existingEvent.trace_id === (event.trace_id ?? existingEvent.trace_id),
            )
              ? matchingRecursionFromMessage.events
              : [event, ...matchingRecursionFromMessage.events],
            status: "running",
            startTime: matchingRecursionFromMessage.startTime || event.timestamp,
          };

          liveTaskIdRef.current = event.task_id;
          liveAssistantMessageIdRef.current = targetMessageId;
          liveRecursionRef.current = resumedRecursion;

          updateMessages((messagesSnapshot) =>
            messagesSnapshot.map((message) => {
              if (message.id !== targetMessageId) {
                return message;
              }

              const updatedRecursions = (message.recursions || []).map((recursion) =>
                recursion.uid === resumedRecursion.uid
                  ? { ...resumedRecursion }
                  : recursion,
              );

              return {
                ...message,
                task_id: event.task_id,
                status: "running" as const,
                recursions: updatedRecursions,
              };
            }),
          );
          return;
        }

        const newRecursion: RecursionRecord = {
          uid: `live-${event.task_id}-${event.trace_id ?? `iter-${event.iteration}`}`,
          iteration: event.iteration,
          trace_id: event.trace_id ?? null,
          events: [event],
          status: "running",
          startTime: event.timestamp,
          liveTokensPerSecond: undefined,
          estimatedCompletionTokens: 0,
          hasSeenPositiveRate: false,
          zeroRateStreak: 0,
        };

        liveTaskIdRef.current = event.task_id;
        liveAssistantMessageIdRef.current = targetMessageId;
        liveRecursionRef.current = newRecursion;

        updateMessages((messagesSnapshot) =>
          messagesSnapshot.map((message) => {
            if (message.id !== targetMessageId) {
              return message;
            }

            const updatedRecursions = (message.recursions || []).map((recursion) =>
              recursion.status === "running"
                ? {
                    ...recursion,
                    status: "completed" as const,
                    endTime: event.timestamp,
                  }
                : recursion,
            );

            return {
              ...message,
              task_id: event.task_id,
              status: "running" as const,
              content:
                message.pendingUserAction?.kind === "skill_change_approval"
                  ? ""
                  : message.content,
              pendingUserAction: undefined,
              recursions: [...updatedRecursions, newRecursion],
            };
          }),
        );
        return;
      }

      if (
        event.type === "answer" ||
        event.type === "clarify" ||
        event.type === "task_cancelled" ||
        event.type === "task_complete" ||
        event.type === "error"
      ) {
        const streamError =
          event.type === "error" ? getStreamErrorData(event.data) : undefined;
        const isTerminalError = streamError?.terminal ?? true;

        if (
          event.type === "clarify" ||
          event.type === "task_complete" ||
          event.type === "task_cancelled" ||
          (event.type === "error" && isTerminalError)
        ) {
          void refreshSidebarData().catch((refreshError) => {
            console.error(
              "Failed to refresh session list after task activity changed:",
              refreshError,
            );
          });
        }

        let finalizedRecursion: RecursionRecord | null = null;
        const currentRecursion =
          currentRecursionFromRefs ?? runningRecursionFromMessage ?? null;

        if (currentRecursion) {
          finalizedRecursion = {
            ...currentRecursion,
            trace_id: event.trace_id || currentRecursion.trace_id,
            events: [...currentRecursion.events, event],
            status:
              event.type === "error"
                ? "error"
                : event.type === "task_cancelled"
                  ? "stopped"
                  : "completed",
            endTime: event.timestamp,
            tokens: event.tokens ?? currentRecursion.tokens,
            errorLog:
              event.type === "error"
                ? (streamError?.message ?? currentRecursion.errorLog)
                : currentRecursion.errorLog,
          };
        }

        if (event.type === "clarify") {
          const approvalRequest = extractSkillChangeApprovalRequestFromClarifyData(
            event.data,
          );
          setIsStreaming(false);
          setActiveContextTaskId(null);
          setActiveContextIteration(null);
          clearCompactStatusWithMinimumDelay();
          setReplyTaskId(approvalRequest ? null : event.task_id);
          liveTaskIdRef.current = event.task_id;
          liveRecursionRef.current = finalizedRecursion;
        } else if (
          event.type === "task_complete" ||
          event.type === "task_cancelled" ||
          (event.type === "error" && isTerminalError)
        ) {
          setIsStreaming(false);
          setActiveContextTaskId(null);
          setActiveContextIteration(null);
          if (showCompactDebug && currentSessionIdRef.current) {
            void loadSessionRuntimeDebug(currentSessionIdRef.current);
          }
          clearCompactStatusWithMinimumDelay();
          setReplyTaskId((previousTaskId) =>
            previousTaskId === event.task_id ? null : previousTaskId,
          );
          liveTaskIdRef.current = null;
          liveRecursionRef.current = null;
          liveAssistantMessageIdRef.current = null;
          if (event.type === "task_cancelled") {
            stoppedTaskIdsRef.current.add(event.task_id);
          }
        } else if (event.type === "error") {
          setIsStreaming(true);
          setActiveContextTaskId(event.task_id);
          setActiveContextIteration(null);
          liveTaskIdRef.current = event.task_id;
          liveAssistantMessageIdRef.current = targetMessageId;
          liveRecursionRef.current = null;
        } else {
          setReplyTaskId((previousTaskId) =>
            previousTaskId === event.task_id ? null : previousTaskId,
          );
          liveTaskIdRef.current = event.task_id;
          liveAssistantMessageIdRef.current = targetMessageId;
          liveRecursionRef.current = finalizedRecursion;
        }

        updateMessages((messagesSnapshot) =>
          messagesSnapshot.map((message) => {
            if (message.id !== targetMessageId) {
              return message;
            }

            const updatedRecursions = (message.recursions || []).map((recursion) =>
              finalizedRecursion && recursion.uid === finalizedRecursion.uid
                ? { ...finalizedRecursion }
                : recursion.status === "running" &&
                    (event.type === "task_complete" ||
                      event.type === "task_cancelled")
                  ? {
                      ...recursion,
                      status:
                        event.type === "task_cancelled"
                          ? ("stopped" as const)
                          : ("completed" as const),
                      endTime: event.timestamp,
                    }
                  : recursion
            );

            if (event.type === "answer") {
              const answerData = event.data as {
                answer?: string;
                attachments?: Array<{
                  attachment_id: string;
                  display_name: string;
                  original_name: string;
                  mime_type: string;
                  extension: string;
                  size_bytes: number;
                  render_kind: "markdown" | "pdf" | "image" | "text" | "download";
                  workspace_relative_path: string;
                  created_at: string;
                }>;
              } | undefined;
              return {
                ...message,
                recursions: updatedRecursions,
                pendingUserAction: undefined,
                content: answerData?.answer ?? message.content,
                errorMessage: undefined,
                assistantAttachments: Array.isArray(answerData?.attachments)
                  ? answerData.attachments.map((attachment) =>
                      toAssistantAttachment(attachment),
                    )
                  : message.assistantAttachments,
              };
            }

            if (event.type === "clarify") {
              const clarifyData = event.data as { question?: string } | undefined;
              const approvalRequest = extractSkillChangeApprovalRequestFromClarifyData(
                event.data,
              );
              return {
                ...message,
                recursions: updatedRecursions,
                content:
                  approvalRequest?.message && approvalRequest.message.trim().length > 0
                    ? `${clarifyData?.question ?? message.content}\n\n${approvalRequest.message}`
                    : (clarifyData?.question ?? message.content),
                pendingUserAction: approvalRequest
                  ? {
                      kind: "skill_change_approval",
                      approvalRequest,
                    }
                  : undefined,
                status: "waiting_input" as const,
                errorMessage: undefined,
                timestamp: event.timestamp,
              };
            }

            if (event.type === "error") {
              if (!isTerminalError) {
                return {
                  ...message,
                  recursions: updatedRecursions,
                  pendingUserAction: undefined,
                  status: "running" as const,
                  errorMessage: undefined,
                  content: "",
                  timestamp: event.timestamp,
                };
              }

              return {
                ...message,
                recursions: updatedRecursions,
                pendingUserAction: undefined,
                status: "error" as const,
                errorMessage: streamError?.message ?? message.errorMessage,
                timestamp: event.timestamp,
              };
            }

            if (event.type === "task_cancelled") {
              return {
                ...message,
                recursions: updatedRecursions,
                pendingUserAction: undefined,
                status: "stopped" as const,
                errorMessage: undefined,
              };
            }

            return {
              ...message,
              recursions: updatedRecursions,
              pendingUserAction: undefined,
              status: "completed" as const,
              errorMessage: undefined,
              totalTokens: event.total_tokens ?? message.totalTokens,
            };
          }),
        );
        return;
      }

      const canAppendToCompletedRecursion = Boolean(
        matchingRecursionFromMessage &&
          (event.type === "tool_call" ||
            event.type === "tool_result" ||
            event.type === "tool_payload_delta" ||
            event.type === "answer_delta" ||
            ((event.type === "message" ||
              event.type === "action") &&
              event.tokens)),
      );
      const currentRecursion =
        (currentRecursionFromRefs?.status === "running"
          ? currentRecursionFromRefs
          : null) ??
        (matchingRecursionFromMessage?.status === "running"
          ? matchingRecursionFromMessage
          : canAppendToCompletedRecursion
            ? matchingRecursionFromMessage
            : runningRecursionFromMessage) ??
        null;
      if (!currentRecursion) {
        return;
      }

      liveTaskIdRef.current = event.task_id;
      liveAssistantMessageIdRef.current = targetMessageId;

      const updatedEvents: ReactStreamEvent[] = [...currentRecursion.events, event];
      let nextRecursion: RecursionRecord = {
        ...currentRecursion,
        trace_id: event.trace_id || currentRecursion.trace_id,
        events: updatedEvents,
      };
      const nextCurrentPlan = extractLiveCurrentPlan(event);

      if (event.type === "token_rate") {
        const tokenRate = parseTokenRateData(event.data);
        if (tokenRate) {
          const previousRate = currentRecursion.liveTokensPerSecond;
          const previousHasSeenPositiveRate =
            currentRecursion.hasSeenPositiveRate === true;
          const previousZeroRateStreak = currentRecursion.zeroRateStreak ?? 0;

          let nextRate: number | undefined = previousRate;
          let nextHasSeenPositiveRate = previousHasSeenPositiveRate;
          let nextZeroRateStreak = previousZeroRateStreak;

          if (tokenRate.tokensPerSecond > 0) {
            nextRate = tokenRate.tokensPerSecond;
            nextHasSeenPositiveRate = true;
            nextZeroRateStreak = 0;
          } else if (!previousHasSeenPositiveRate) {
            nextRate = undefined;
            nextZeroRateStreak = 0;
          } else {
            nextZeroRateStreak = previousZeroRateStreak + 1;
            if (nextZeroRateStreak >= ZERO_RATE_STREAK_TO_RENDER) {
              nextRate = 0;
            }
          }

          nextRecursion = {
            ...nextRecursion,
            liveTokensPerSecond: nextRate,
            estimatedCompletionTokens: tokenRate.estimatedCompletionTokens,
            hasSeenPositiveRate: nextHasSeenPositiveRate,
            zeroRateStreak: nextZeroRateStreak,
          };
        }
      } else if (event.type === "reasoning") {
        nextRecursion = {
          ...nextRecursion,
          thinking: `${currentRecursion.thinking ?? ""}${event.delta ?? ""}`,
          tokens: event.tokens ?? currentRecursion.tokens,
        };
      } else if (event.type === "content") {
        nextRecursion = {
          ...nextRecursion,
          message: `${currentRecursion.message ?? ""}${event.delta ?? ""}`,
        };
      } else if (event.type === "message") {
        nextRecursion = {
          ...nextRecursion,
          message: event.delta ?? "",
          tokens: event.tokens ?? currentRecursion.tokens,
        };
      } else if (event.type === "action") {
        const isToolCallAction = event.delta === "CALL_TOOL";
        nextRecursion = {
          ...nextRecursion,
          action: event.delta ?? "",
          status: isToolCallAction ? "running" : "completed",
          endTime: isToolCallAction ? undefined : event.timestamp,
          tokens: event.tokens ?? currentRecursion.tokens,
        };
      } else if (
        event.type === "tool_call" ||
        event.type === "tool_result" ||
        event.type === "tool_payload_delta" ||
        event.type === "answer_delta"
      ) {
        const hasPendingTools = hasPendingToolExecutions(updatedEvents);
        nextRecursion = {
          ...nextRecursion,
          status: hasPendingTools ? "running" : "completed",
          endTime: hasPendingTools ? undefined : event.timestamp,
        };
      }

      liveRecursionRef.current = nextRecursion;

      updateMessages((messagesSnapshot) =>
        messagesSnapshot.map((message) => {
          if (message.id !== targetMessageId) {
            return message;
          }

          const updatedRecursions = (message.recursions || []).map((recursion) =>
            recursion.uid === nextRecursion.uid ? { ...nextRecursion } : recursion,
          );

          return {
            ...message,
            recursions: updatedRecursions,
            content:
              event.type === "answer_delta"
                ? `${
                    message.content ??
                    ""
                  }${
                    typeof event.data === "object" &&
                    event.data !== null &&
                    !Array.isArray(event.data) &&
                    typeof (event.data as { delta?: unknown }).delta === "string"
                      ? ((event.data as { delta?: string }).delta ?? "")
                      : ""
                  }`
                : message.content,
            currentPlan: nextCurrentPlan ?? message.currentPlan,
          };
        }),
      );
    },
    [
      clearCompactStatusWithMinimumDelay,
      loadHistoryResponse,
      currentSessionId,
      loadSessionRuntimeDebug,
      refreshSidebarData,
      showCompactDebug,
      showCompactStatus,
      updateMessages,
    ],
  );

  /**
   * Opens a reconnectable SSE stream for the selected session.
   */
  const openSessionStream = useCallback(
    (sessionId: string, initialCursor: number) => {
      stopSessionStream();
      sessionEventCursorRef.current = initialCursor;
      sessionStreamReconnectCountRef.current = 0;
      const controller = new AbortController();
      sessionStreamAbortControllerRef.current = controller;

      const connect = async () => {
        if (!isTokenValid()) {
          window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
          return;
        }

        try {
          const token = getAuthToken();
          const headers: Record<string, string> = {};
          if (token) {
            headers.Authorization = `Bearer ${token}`;
          }

          const response = await httpClient(
            `${getApiBaseUrl()}/react/sessions/${sessionId}/events/stream?after_id=${sessionEventCursorRef.current}`,
            {
              headers,
              signal: controller.signal,
            },
          );

          if (response.status === 401) {
            window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
            return;
          }

          if (!response.ok || !response.body) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }

          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              break;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (!line.trim() || line.startsWith(":")) {
                continue;
              }
              if (!line.startsWith("data: ")) {
                continue;
              }

              const parsedEvent = parseJson(line.slice(6).trim());
              if (!isReactStreamEvent(parsedEvent)) {
                continue;
              }
              applyStreamEvent(parsedEvent);
            }
          }
        } catch (streamError) {
          if (
            streamError instanceof Error &&
            streamError.name === "AbortError"
          ) {
            return;
          }
          console.error("Session stream disconnected:", streamError);
          scheduleReconnect();
        }

        function scheduleReconnect() {
          if (
            !controller.signal.aborted &&
            currentSessionIdRef.current === sessionId &&
            sessionStreamReconnectCountRef.current < SESSION_STREAM_MAX_RECONNECTS
          ) {
            sessionStreamReconnectCountRef.current += 1;
            const backoff = Math.min(
              1000 * 2 ** (sessionStreamReconnectCountRef.current - 1),
              30_000,
            );
            sessionStreamReconnectTimerRef.current = window.setTimeout(() => {
              void connect();
            }, backoff);
          }
        }
      };

      void connect();
    },
    [applyStreamEvent, stopSessionStream],
  );

  useEffect(() => {
    const initSessions = async () => {
      if (
        isInitialized ||
        isLoadingSession ||
        (sessionType === "studio_test" && testSnapshot && !testSnapshotHash)
      ) {
        return;
      }

      setIsLoadingSession(true);
      try {
        let existingSessions: SessionListItem[];
        if (initialSessions && initialProjects) {
          existingSessions = sessions;
        } else {
          const sidebarData = await refreshSidebarData();
          existingSessions = sidebarData.sessions;
        }

        if (existingSessions.length > 0) {
          const requestedSessionId =
            typeof initialSessionId === "string" &&
            initialSessionId.trim().length > 0
              ? initialSessionId.trim()
              : null;
          const requestedSession = requestedSessionId
            ? existingSessions.find(
                (session) => session.session_id === requestedSessionId,
              )
            : null;
          const studioMatchingSessions =
            sessionType === "studio_test"
              ? testSnapshotHash
                ? existingSessions.filter(
                    (session) => session.test_workspace_hash === testSnapshotHash,
                  )
                : []
              : existingSessions;
          const autoSelectedSessionId =
            requestedSession?.session_id ??
            requestedSessionId ??
            (sessionType === "studio_test"
              ? getAutoSelectedSessionId(
                  studioMatchingSessions,
                  Date.now(),
                  sessionIdleTimeoutMs,
                )
              : getAutoSelectedSessionId(
                  existingSessions,
                  Date.now(),
                  sessionIdleTimeoutMs,
                ));

          setCurrentSessionId(autoSelectedSessionId);
          currentSessionIdRef.current = autoSelectedSessionId;
          setCurrentProjectId(
            existingSessions.find(
              (session) => session.session_id === autoSelectedSessionId,
            )?.project_id ?? null,
          );
          setReplyTaskId(null);
          setActiveContextTaskId(null);
          setActiveContextIteration(null);

          if (autoSelectedSessionId) {
            dispatchChatSessionRuntime({
              type: "INIT_SESSION",
              sessionId: autoSelectedSessionId,
              pageSize: CHAT_HISTORY_PAGE_SIZE,
            });
            try {
              const history = await getFullSessionHistory(autoSelectedSessionId, {
                limit: CHAT_HISTORY_PAGE_SIZE,
              });
              loadHistoryResponse(history, true);
              openSessionStream(
                autoSelectedSessionId,
                history.resume_from_event_id,
              );
            } catch (historyError) {
              console.error(
                "Failed to load initial session history:",
                historyError,
              );
            }
          } else {
            commitMessages([]);
            setIsStreaming(false);
          }
        } else {
          // No sessions in the sidebar list, but a specific session was
          // requested via URL (e.g. an automation session). Load it directly.
          const fallbackSessionId =
            typeof initialSessionId === "string" &&
            initialSessionId.trim().length > 0
              ? initialSessionId.trim()
              : null;

          if (fallbackSessionId) {
            setCurrentProjectId(null);
            setCurrentSessionId(fallbackSessionId);
            currentSessionIdRef.current = fallbackSessionId;
            setReplyTaskId(null);
            setActiveContextTaskId(null);
            setActiveContextIteration(null);
            dispatchChatSessionRuntime({
              type: "INIT_SESSION",
              sessionId: fallbackSessionId,
              pageSize: CHAT_HISTORY_PAGE_SIZE,
            });

            try {
              const history = await getFullSessionHistory(fallbackSessionId, {
                limit: CHAT_HISTORY_PAGE_SIZE,
              });
              loadHistoryResponse(history, true);
              openSessionStream(
                fallbackSessionId,
                history.resume_from_event_id,
              );
            } catch (historyError) {
              console.error(
                "Failed to load requested session history:",
                historyError,
              );
            }
          } else {
            setCurrentProjectId(null);
            setCurrentSessionId(null);
            currentSessionIdRef.current = null;
            setReplyTaskId(null);
            setActiveContextTaskId(null);
            setActiveContextIteration(null);
            dispatchChatSessionRuntime({ type: "RESET_DRAFT" });
            syncLiveRefsFromMessages([]);
            commitMessages([]);
            setIsStreaming(false);
            stopSessionStream();
          }
        }

        setIsInitialized(true);
      } catch (initError) {
        console.error("Failed to initialize sessions:", initError);
        setError("Failed to initialize session");
      } finally {
        setIsLoadingSession(false);
      }
    };

    void initSessions();
  }, [
    agentId,
    isInitialized,
    initialSessionId,
    initialSessions,
    initialProjects,
    isLoadingSession,
    dispatchChatSessionRuntime,
    loadHistoryResponse,
    refreshSidebarData,
    sessionIdleTimeoutMs,
    openSessionStream,
    stopSessionStream,
    commitMessages,
    sessionType,
    sessions,
    syncLiveRefsFromMessages,
    testSnapshot,
    testSnapshotHash,
  ]);

  useEffect(() => {
    return () => {
      stopSessionStream();
      clearCompactStatusTimer();
    };
  }, [clearCompactStatusTimer, stopSessionStream]);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
    setComposerFocusSignal((s) => s + 1);
  }, [currentSessionId]);

  useEffect(() => {
    if (!currentSessionId) {
      setPreviewEndpoints([]);
      setActivePreviewEndpoint(null);
      setReconnectablePreviewSuggestion(null);
      return;
    }

    let isCancelled = false;
    const loadPreviewRegistry = async () => {
      try {
        const nextPreviews = await getPreviewEndpoints(currentSessionId);
        if (isCancelled) {
          return;
        }
        setPreviewEndpoints(nextPreviews);
        setActivePreviewEndpoint(
          nextPreviews.length > 0 ? nextPreviews[nextPreviews.length - 1] : null,
        );
        if (
          nextPreviews.length > 0 ||
          currentSessionIdRef.current !== currentSessionId ||
          sessionType !== "studio_test" ||
          !testSnapshotHash
        ) {
          setReconnectablePreviewSuggestion(null);
          return;
        }

        const historicalStudioSessions = [...sessions]
          .filter(
            (session) =>
              session.session_id !== currentSessionId &&
              session.test_workspace_hash === testSnapshotHash,
          )
          .sort(
            (left, right) =>
              Date.parse(right.updated_at) - Date.parse(left.updated_at),
          );

        for (const session of historicalStudioSessions) {
          const historicalPreviews = await getPreviewEndpoints(session.session_id);
          if (isCancelled) {
            return;
          }
          const reconnectablePreview = [...historicalPreviews]
            .reverse()
            .find((preview) => preview.has_launch_recipe);
          if (reconnectablePreview) {
            setReconnectablePreviewSuggestion(reconnectablePreview);
            return;
          }
        }

        setReconnectablePreviewSuggestion(null);
      } catch (previewError) {
        console.error("Failed to load preview registry:", previewError);
        if (isCancelled) {
          return;
        }
        setPreviewEndpoints([]);
        setActivePreviewEndpoint(null);
        setReconnectablePreviewSuggestion(null);
      }
    };

    void loadPreviewRegistry();

    return () => {
      isCancelled = true;
    };
  }, [currentSessionId, sessionType, sessions, testSnapshotHash]);

  useEffect(() => {
    if (!showCompactDebug) {
      return;
    }
    void loadSessionRuntimeDebug(currentSessionId);
  }, [currentSessionId, loadSessionRuntimeDebug, showCompactDebug]);

  // Why: client sessions pinned to an older Agent release must prompt the
  // user to migrate. Already-migrated sessions show a different dialog.
  // The banner reappears each time the user navigates to a stale/migrated session.
  useEffect(() => {
    if (currentSessionId === null) {
      setStaleSessionId(null);
      setMigratedSessionId(null);
      return;
    }
    const current = sessions.find(
      (session) => session.session_id === currentSessionId,
    );
    if (current?.type === "client" && current.migrated_to_session_id) {
      setMigratedSessionId(current.migrated_to_session_id);
      setStaleSessionId(null);
      setIsStaleBannerDismissed(false);
    } else if (current?.type === "client" && current.is_stale) {
      setStaleSessionId(currentSessionId);
      setMigratedSessionId(null);
      setIsStaleBannerDismissed(false);
    } else {
      setStaleSessionId((previous) =>
        previous === currentSessionId ? null : previous,
      );
      setMigratedSessionId(null);
    }
  }, [currentSessionId, sessions]);

  useEffect(() => {
    onRuntimeDebugChange?.({
      currentSessionId,
      isCompacting: compactStatusMessage !== null,
      compactStatusMessage,
      loadState:
        currentSessionId === null
          ? "idle"
          : isRuntimeDebugLoading
            ? "loading"
            : runtimeDebugError
              ? "error"
              : "ready",
      runtimeDebug: sessionRuntimeDebug,
      contextUsage,
      compactThresholdPercent: compactThresholdPercent ?? null,
      error: runtimeDebugError,
    });
  }, [
    compactThresholdPercent,
    compactStatusMessage,
    contextUsage,
    currentSessionId,
    isRuntimeDebugLoading,
    onRuntimeDebugChange,
    runtimeDebugError,
    sessionRuntimeDebug,
  ]);

  const readyPendingFileIds = readyPendingFiles.map((file) => file.fileId);
  const readyPendingFileIdsKey = readyPendingFileIds.join(",");

  useEffect(() => {
    let isCancelled = false;

    const loadRuntimeSkills = async () => {
      try {
        const visibleSkills = await getReactRuntimeSkills({
          agent_id: agentId,
          session_id: currentSessionId,
          session_type: sessionType,
          test_snapshot: currentSessionId ? undefined : testSnapshot,
        });
        if (isCancelled) {
          return;
        }

        setRuntimeSkills(
          visibleSkills.map((skill) => ({
            name: skill.name,
            description: skill.description,
            path: skill.path,
          })),
        );
      } catch (loadError) {
        if (isCancelled) {
          return;
        }

        console.error("Failed to load runtime-visible skills:", loadError);
        setRuntimeSkills([]);
      }
    };

    void loadRuntimeSkills();

    return () => {
      isCancelled = true;
    };
  }, [agentId, currentSessionId, sessionType, testSnapshot]);

  useEffect(() => {
    const visibleSkillNames = new Set(runtimeSkills.map((skill) => skill.name));
    setSelectedMandatorySkills((previous) =>
      previous.filter((skill) => visibleSkillNames.has(skill.name)),
    );
  }, [runtimeSkills]);

  useEffect(() => {
    if (initialChatSurfaces) {
      setInstalledChatSurfaces(
        initialChatSurfaces.map((s) => ({
          installationId: s.installation_id,
          packageId: s.package_id,
          surfaceKey: s.surface_key,
          displayName: s.display_name,
          logoUrl: s.logo_url,
          description: s.description ?? "",
          minWidth: s.min_width,
          icon: s.icon,
        })),
      );
      return;
    }

    let isCancelled = false;

    const loadInstalledChatSurfaces = async () => {
      try {
        const surfaces = await getAgentChatSurfaces(agentId);
        if (isCancelled) {
          return;
        }
        setInstalledChatSurfaces(
          surfaces.map((s: ChatSurfaceDescriptorResponse) => ({
            installationId: s.installation_id,
            packageId: s.package_id,
            surfaceKey: s.surface_key,
            displayName: s.display_name,
            logoUrl: s.logo_url,
            description: s.description ?? "",
            minWidth: s.min_width,
            icon: s.icon,
          })),
        );
      } catch (loadError) {
        if (isCancelled) {
          return;
        }

        console.error(
          "Failed to load installed chat surfaces for the current agent:",
          loadError,
        );
        setInstalledChatSurfaces([]);
      }
    };

    void loadInstalledChatSurfaces();

    return () => {
      isCancelled = true;
    };
  }, [agentId, initialChatSurfaces]);

  useEffect(() => {
    if (!canUseWebSearch) {
      setWebSearchProviders([]);
      setSelectedWebSearchProvider(null);
      return;
    }

    if (initialWebSearchProviders) {
      setWebSearchProviders(
        initialWebSearchProviders.map((p) => ({
          key: p.provider_key,
          name: p.name,
          logoUrl: p.logo_url,
        })),
      );
      return;
    }

    let isCancelled = false;

    const loadWebSearchProviders = async () => {
      try {
        const bindings = await getAgentWebSearchBindings(agentId);
        if (isCancelled) {
          return;
        }

        setWebSearchProviders(toWebSearchProviderOptions(bindings));
      } catch (loadError) {
        if (isCancelled) {
          return;
        }

        console.error("Failed to load chat web search providers:", loadError);
        setWebSearchProviders([]);
      }
    };

    void loadWebSearchProviders();

    return () => {
      isCancelled = true;
    };
  }, [agentId, canUseWebSearch, initialWebSearchProviders]);

  useEffect(() => {
    if (webSearchProviders.length === 0) {
      if (selectedWebSearchProvider !== null) {
        setSelectedWebSearchProvider(null);
      }
      return;
    }

    const hasCurrentSelection = webSearchProviders.some(
      (provider) => provider.key === selectedWebSearchProvider,
    );
    if (!hasCurrentSelection) {
      setSelectedWebSearchProvider(webSearchProviders[0]?.key ?? null);
    }
  }, [selectedWebSearchProvider, webSearchProviders]);

  const requestDraftContextUsageEstimate = useCallback(() => {
    const draftFileIds = readyPendingFileIdsKey
      ? readyPendingFileIdsKey.split(",")
      : [];
    const requestId = contextUsageRequestIdRef.current + 1;
    contextUsageRequestIdRef.current = requestId;
    setIsContextUsageLoading(true);

    void getReactContextUsage({
      agent_id: agentId,
      session_id: currentSessionId,
      task_id: replyTaskId,
      draft_message: isCompactMode ? "" : draftMessageRef.current,
      file_ids: draftFileIds,
      session_type: sessionType,
      test_snapshot: currentSessionId ? undefined : testSnapshot,
      mandatory_skill_names: manualCompactSkillNames,
    })
      .then((usage) => {
        if (contextUsageRequestIdRef.current === requestId) {
          setContextUsage(usage);
        }
      })
      .catch((contextError) => {
        console.error("Failed to estimate context usage:", contextError);
        if (contextUsageRequestIdRef.current === requestId) {
          setContextUsage(null);
          clearCompactStatusImmediately();
        }
      })
      .finally(() => {
        if (contextUsageRequestIdRef.current === requestId) {
          setIsContextUsageLoading(false);
        }
      });
  }, [
    agentId,
    clearCompactStatusImmediately,
    currentSessionId,
    readyPendingFileIdsKey,
    replyTaskId,
    isCompactMode,
    manualCompactSkillNames,
    sessionType,
    testSnapshot,
  ]);

  /**
   * Debounces draft-driven context requests so high-frequency typing and IME
   * composition do not force the whole chat surface through synchronous work.
   */
  const scheduleDraftContextUsageEstimate = useCallback(() => {
    clearContextUsageDebounceTimer();
    if (isStreaming) {
      return;
    }

    contextUsageDebounceTimerRef.current = window.setTimeout(() => {
      contextUsageDebounceTimerRef.current = null;
      requestDraftContextUsageEstimate();
    }, 250);
  }, [
    clearContextUsageDebounceTimer,
    isStreaming,
    requestDraftContextUsageEstimate,
  ]);

  useEffect(() => {
    scheduleDraftContextUsageEstimate();

    return clearContextUsageDebounceTimer;
  }, [clearContextUsageDebounceTimer, scheduleDraftContextUsageEstimate]);

  useEffect(() => {
    if (isStreaming) {
      clearContextUsageDebounceTimer();
    }
  }, [clearContextUsageDebounceTimer, isStreaming]);

  useEffect(() => {
    if (!isStreaming || !activeContextTaskId) {
      return;
    }

    const runEstimate = () => {
      const requestId = contextUsageRequestIdRef.current + 1;
      contextUsageRequestIdRef.current = requestId;
      setIsContextUsageLoading(true);

      void getReactContextUsage({
        agent_id: agentId,
        session_id: currentSessionId,
        task_id: activeContextTaskId,
        draft_message: "",
        file_ids: [],
        session_type: sessionType,
      })
        .then((usage) => {
          if (contextUsageRequestIdRef.current === requestId) {
            setContextUsage(usage);
          }
        })
        .catch((contextError) => {
          console.error("Failed to estimate context usage:", contextError);
          if (contextUsageRequestIdRef.current === requestId) {
            setContextUsage(null);
            clearCompactStatusImmediately();
          }
        })
        .finally(() => {
          if (contextUsageRequestIdRef.current === requestId) {
            setIsContextUsageLoading(false);
          }
        });
    };

    runEstimate();
  }, [
    activeContextIteration,
    activeContextTaskId,
    agentId,
    clearCompactStatusImmediately,
    currentSessionId,
    isStreaming,
    sessionType,
  ]);

  /**
   * Enter a blank draft state while optionally keeping one project selected.
   */
  const enterDraftState = async (nextProjectId: string | null) => {
    setIsLoadingSession(true);
    try {
      await clearPendingFiles();
      prepareForProgrammaticScroll();

      setCurrentProjectId(nextProjectId);
      setCurrentSessionId(null);
      currentSessionIdRef.current = null;
      dispatchChatSessionRuntime({ type: "RESET_DRAFT" });
      commitMessages([]);
      setReplyTaskId(null);
      setSelectedMandatorySkills([]);
      setActiveContextTaskId(null);
      setActiveContextIteration(null);
      setContextUsage(null);
      clearCompactStatusImmediately();
      setError(null);
      syncLiveRefsFromMessages([]);
      stopSessionStream();
      setIsStreaming(false);
    } catch (createError) {
      console.error("Failed to prepare new session draft:", createError);
      setError("Failed to prepare new session draft");
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * Enters a standalone draft and postpones session persistence until send time.
   */
  const handleNewSession = async () => {
    await enterDraftState(null);
  };

  useNewSessionShortcut(() => {
    if (!isStreaming) {
      void enterDraftState(null);
    }
  });

  /**
   * Opens one project-level draft so the next send creates a session inside
   * the selected shared workspace.
   */
  const handleSelectProject = async (projectId: string) => {
    await enterDraftState(projectId);
  };

  /**
   * Creates a new project with a lightweight default name and opens its draft.
   */
  const handleCreateProject = async () => {
    try {
      const project = await createProject({
        agent_id: agentId,
        name: "New Project",
      });
      setProjects((previous) =>
        sortProjectsForSidebar([...previous, project], sessions),
      );
      await enterDraftState(project.project_id);
      setError(null);
    } catch (projectError) {
      console.error("Failed to create project:", projectError);
      setError("Failed to create project");
    }
  };

  /**
   * Applies a user-provided project name from the sidebar.
   */
  const handleRenameProject = async (
    projectId: string,
    name: string | null,
  ) => {
    if (!name) {
      return;
    }

    try {
      const updatedProject = await updateProject(projectId, { name });
      setProjects((previous) =>
        sortProjectsForSidebar(
          previous.map((project) =>
            project.project_id === projectId ? updatedProject : project,
          ),
          sessions,
        ),
      );
      setError(null);
    } catch (renameError) {
      console.error("Failed to rename project:", renameError);
      setError("Failed to rename project");
    }
  };

  const handleManageProjectAccess = (projectId: string) => {
    setAccessProjectId(projectId);
  };

  /**
   * Deletes a project and all of its child sessions, then clears any active
   * draft or session that depended on that shared workspace.
   */
  const handleDeleteProject = async (projectId: string) => {
    try {
      await deleteProject(projectId);
      const remainingProjects = projects.filter(
        (project) => project.project_id !== projectId,
      );
      const remainingSessions = sessions.filter(
        (session) => session.project_id !== projectId,
      );
      setProjects(remainingProjects);
      setSessions(remainingSessions);

      const currentSessionProjectId =
        sessions.find((session) => session.session_id === currentSessionId)?.project_id ??
        null;
      if (currentProjectId === projectId || currentSessionProjectId === projectId) {
        await enterDraftState(null);
      }
      setError(null);
    } catch (deleteError) {
      console.error("Failed to delete project:", deleteError);
      setError("Failed to delete project");
    }
  };

  /**
   * Loads the selected session history into the current chat surface.
   */
  const handleSelectSession = async (sessionId: string) => {
    if (sessionId === currentSessionId || isLoadingSession) {
      return;
    }

    const selectedSession = sessions.find((session) => session.session_id === sessionId);
    setCurrentProjectId(selectedSession?.project_id ?? null);
    setCurrentSessionId(sessionId);
    currentSessionIdRef.current = sessionId;
    setIsLoadingSession(true);
    setReplyTaskId(null);
    setSelectedMandatorySkills([]);
    dispatchChatSessionRuntime({
      type: "INIT_SESSION",
      sessionId,
      pageSize: CHAT_HISTORY_PAGE_SIZE,
    });
    setActiveContextTaskId(null);
    setActiveContextIteration(null);
    setContextUsage(null);
    clearCompactStatusImmediately();
    prepareForProgrammaticScroll();
    await clearPendingFiles();
    stopSessionStream();

    try {
      const history = await getFullSessionHistory(sessionId, {
        limit: CHAT_HISTORY_PAGE_SIZE,
      });
      loadHistoryResponse(history, true);
      openSessionStream(sessionId, history.resume_from_event_id);
    } catch (historyError) {
      console.error("Failed to load session history:", historyError);
      syncLiveRefsFromMessages([]);
      commitMessages([]);
      setIsStreaming(false);
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * Deletes a session and keeps the sidebar and active view consistent afterwards.
   */
  const handleDeleteSession = async (sessionId: string) => {
    try {
      const deletedSession = sessions.find((session) => session.session_id === sessionId);
      await deleteSession(sessionId);

      const remainingSessions = sessions.filter(
        (session) => session.session_id !== sessionId,
      );
      setSessions(remainingSessions);

      if (sessionId === currentSessionId) {
        setReplyTaskId(null);
        setActiveContextTaskId(null);
        setActiveContextIteration(null);
        setContextUsage(null);
        clearCompactStatusImmediately();

        if (deletedSession?.project_id) {
          const siblingProjectSessions = remainingSessions.filter(
            (session) => session.project_id === deletedSession.project_id,
          );
          if (siblingProjectSessions.length > 0) {
            await handleSelectSession(siblingProjectSessions[0].session_id);
          } else {
            await enterDraftState(deletedSession.project_id);
          }
        } else if (remainingSessions.length > 0) {
          await handleSelectSession(
            remainingSessions.find((session) => !session.project_id)?.session_id ??
              remainingSessions[0].session_id,
          );
        } else {
          await enterDraftState(null);
          setIsInitialized(false);
        }
      }
    } catch (deleteError) {
      console.error("Failed to delete session:", deleteError);
      setError("Failed to delete session");
    }
  };

  /**
   * Migrate a stale client session onto the agent's latest release.
   * Creates a new session, copies private workspace files server-side, and
   * marks the old session closed. Switches the UI to the new session.
   */
  const handleMigrateStaleSession = async () => {
    if (staleSessionId === null || isMigratingStaleSession) return;
    setIsMigratingStaleSession(true);
    try {
      const { new_session_id } = await migrateSession(staleSessionId);
      setStaleSessionId(null);
      const { sessions: refreshedSessions } = await refreshSidebarData();
      const newSession = refreshedSessions.find(
        (session) => session.session_id === new_session_id,
      );
      if (newSession) {
        await handleSelectSession(new_session_id);
      }
    } catch (migrateError) {
      console.error("Failed to migrate stale session:", migrateError);
      setError(
        migrateError instanceof Error
          ? migrateError.message
          : "Failed to migrate session",
      );
    } finally {
      setIsMigratingStaleSession(false);
    }
  };

  /**
   * Dismiss the stale session banner without navigating away.
   *
   * Why: the user should stay on the stale session and browse history
   * freely. The composer stays disabled for stale sessions regardless
   * of whether the banner is visible.
   */
  const handleDismissStaleBanner = () => {
    setIsStaleBannerDismissed(true);
  };

  /**
   * Navigate from a migrated (old) session to its replacement.
   */
  const handleGoToMigratedSession = (targetSessionId: string) => {
    setMigratedSessionId(null);
    void handleSelectSession(targetSessionId);
  };

  /**
   * Applies a user-provided sidebar title and keeps local ordering in sync.
   */
  const handleRenameSession = async (
    sessionId: string,
    title: string | null,
  ) => {
    try {
      const updatedSession = await updateSession(sessionId, { title });
      const nextSession = toSessionListItem(updatedSession);
      setSessions((previous) =>
        replaceSessionListItem(previous, nextSession),
      );
      setError(null);
    } catch (renameError) {
      console.error("Failed to rename session:", renameError);
      setError("Failed to rename session");
    }
  };

  /**
   * Moves a session into or out of the pinned section while preserving the
   * same ordering rules used by the server.
   */
  const handleTogglePinSession = async (
    sessionId: string,
    isPinned: boolean,
  ) => {
    try {
      const updatedSession = await updateSession(sessionId, {
        is_pinned: isPinned,
      });
      setSessions((previous) =>
        upsertSessionListItem(previous, toSessionListItem(updatedSession)),
      );
      setError(null);
    } catch (pinError) {
      console.error("Failed to update session pin state:", pinError);
      setError("Failed to update session pin state");
    }
  };

  /**
   * Requests cancellation for the active task from the composer.
   */
  const handleStop = useCallback(() => {
    const activeTaskId = liveTaskIdRef.current;
    if (!activeTaskId) {
      return;
    }

    markTaskStopped(activeTaskId, new Date().toISOString());
    setError(null);

    void cancelReactTask(activeTaskId)
      .then(() =>
        refreshSidebarData().catch((refreshError) => {
          console.error(
            "Failed to refresh session list after stopping task:",
            refreshError,
          );
        }),
      )
      .catch((cancelError) => {
        console.error("Failed to cancel task:", cancelError);
        stoppedTaskIdsRef.current.delete(activeTaskId);
        setError("Failed to stop execution");
        if (currentSessionIdRef.current) {
          void getFullSessionHistory(currentSessionIdRef.current, {
            limit: CHAT_HISTORY_PAGE_SIZE,
          })
            .then((history) => {
              loadHistoryResponse(history, true);
            })
            .catch((historyError) => {
              console.error(
                "Failed to restore session after stop request failed:",
                historyError,
              );
            });
        }
      });
  }, [loadHistoryResponse, markTaskStopped, refreshSidebarData]);

  /**
   * Sends the current composer state and incrementally applies streamed backend updates.
   */
  const sendMessage = useCallback(
    async (options?: {
      messageOverride?: string;
      replyTaskIdOverride?: string | null;
      includeReadyAttachments?: boolean;
    }) => {
      const pendingMessage = options?.messageOverride ?? draftMessageRef.current;
      const currentReplyTaskId = options?.replyTaskIdOverride ?? replyTaskId;
      const isClarifyReply = Boolean(currentReplyTaskId);
      const isManualCompactRequest = selectedMandatorySkills.some(
        isCompactSkillSelection,
      );
      let assistantMessageId: string | null = null;
      const includeReadyAttachments = options?.includeReadyAttachments ?? true;
      const filesToSend = includeReadyAttachments ? readyPendingFiles : [];
      const sentAttachments = filesToSend.map((file) => ({
        fileId: file.fileId,
        kind: file.kind,
        originalName: file.originalName,
        mimeType: file.mimeType,
        format: file.format,
        extension: file.extension,
        width: file.width,
        height: file.height,
        sizeBytes: file.sizeBytes,
        pageCount: file.pageCount,
        canExtractText: file.canExtractText,
        suspectedScanned: file.suspectedScanned,
        textEncoding: file.textEncoding,
        previewUrl: file.previewUrl,
      }));

      prepareForProgrammaticScroll();

      try {
        let activeSessionId = currentSessionId;
        const requestTaskId = currentReplyTaskId;
        let shouldResetConversation = false;
        let initialCursor = sessionEventCursorRef.current;
        let optimisticUserMessageId: string | null = null;

        if (!activeSessionId) {
          const session = await createSession(agentId, {
            projectId: currentProjectId,
            type: sessionType,
            testSnapshot: sessionType === "studio_test" ? testSnapshot : undefined,
          });
          activeSessionId = session.session_id;
          shouldResetConversation = true;
          const sessionItem = toSessionListItem(session);
          setCurrentProjectId(session.project_id ?? currentProjectId);
          setCurrentSessionId(activeSessionId);
          currentSessionIdRef.current = activeSessionId;
          dispatchChatSessionRuntime({
            type: "INIT_SESSION",
            sessionId: activeSessionId,
            pageSize: CHAT_HISTORY_PAGE_SIZE,
          });
          setSessions((previous) => upsertSessionListItem(previous, sessionItem));
          initialCursor = 0;
          openSessionStream(activeSessionId, initialCursor);

          const firstMessage = pendingMessage.trim();
          if (firstMessage) {
            const provisionalTitle =
              firstMessage.length > 20
                ? firstMessage.slice(0, 20) + "..."
                : firstMessage;
            void updateSession(activeSessionId, {
              title: provisionalTitle,
            }).then((updated) => {
              setSessions((previous) =>
                upsertSessionListItem(previous, toSessionListItem(updated)),
              );
            });
          }
        }

        if (currentReplyTaskId) {
          setReplyTaskId(null);
        }
        setActiveContextIteration(null);

        if (!isTokenValid()) {
          window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
          throw new Error("Token expired or invalid. Please log in again.");
        }

        if (isManualCompactRequest) {
          if (!activeSessionId) {
            throw new Error("Compact is only available after a session has started.");
          }
          setError(null);
          showCompactStatus("Compacting context. Please wait before stopping.");
          setIsManualCompacting(true);
          try {
            let compactResult;
            try {
              compactResult = await compactReactSession(
                activeSessionId,
                pendingMessage.trim(),
              );
            } catch (compactError) {
              if (
                compactError instanceof ApiError &&
                compactError.status === 404 &&
                compactError.message === "Not Found"
              ) {
                throw new Error(
                  "Manual compact endpoint is unavailable. Please restart the backend and try again.",
                );
              }
              throw compactError;
            }
            draftMessageRef.current = "";
            setComposerResetSignal((previous) => previous + 1);
            setSelectedMandatorySkills([]);
            setContextUsage(compactResult.usage_after);
            await loadSessionRuntimeDebug(activeSessionId);
            clearCompactStatusWithMinimumDelay();
            void refreshSidebarData().catch((refreshError) => {
              console.error(
                "Failed to refresh session list after manual compact:",
                refreshError,
              );
            });
            return;
          } finally {
            setIsManualCompacting(false);
          }
        }

        const userTimestamp = new Date().toISOString();
        optimisticUserMessageId = isClarifyReply
          ? `user-${currentReplyTaskId}-clarify-reply-${Date.now()}`
          : `user-${Date.now()}`;
        const userMessage: ChatMessage = {
          id: optimisticUserMessageId,
          role: "user",
          content: pendingMessage,
          attachments: sentAttachments,
          mandatorySkills: selectedMandatorySkills,
          timestamp: userTimestamp,
        };
        assistantMessageId = isClarifyReply
          ? `assistant-${currentReplyTaskId}-resume-${Date.now()}`
          : `assistant-${Date.now()}`;
        const assistantMessage: ChatMessage = {
          id: assistantMessageId,
          role: "assistant",
          content: "",
          timestamp: new Date(Date.now() + 1).toISOString(),
          recursions: [],
          status: "running" as const,
        };

        if (shouldResetConversation) {
          commitMessages([userMessage, assistantMessage]);
        } else {
          updateMessages((previous) => [
            ...previous.map((message) =>
              isClarifyReply &&
              message.role === "assistant" &&
              message.task_id === currentReplyTaskId &&
              message.status === "waiting_input"
                ? { ...message, status: "completed" as const }
                : message,
            ),
            userMessage,
            assistantMessage,
          ]);
        }
        draftMessageRef.current = "";
        setComposerResetSignal((previous) => previous + 1);
        setSelectedMandatorySkills([]);
        if (includeReadyAttachments) {
          discardReadyPendingFiles();
        }
        setError(null);
        clearCompactStatusImmediately();
        setIsStreaming(true);
        liveAssistantMessageIdRef.current = assistantMessageId;
        liveTaskIdRef.current = null;
        liveRecursionRef.current = null;

        const launchResult = await startReactTask({
          agent_id: agentId,
          message: userMessage.content,
          task_id: requestTaskId,
          session_id: activeSessionId,
          file_ids: filesToSend.map((file) => file.fileId),
          web_search_provider: selectedWebSearchProvider,
          thinking_mode: selectedThinkingMode,
          mandatory_skill_names: manualCompactSkillNames,
        });

        if (!sessionStreamAbortControllerRef.current && activeSessionId) {
          openSessionStream(
            activeSessionId,
            Math.max(initialCursor, launchResult.cursor_before_start),
          );
        } else {
          sessionEventCursorRef.current = Math.max(
            sessionEventCursorRef.current,
            launchResult.cursor_before_start,
          );
        }

        const canonicalAssistantId =
          isClarifyReply && assistantMessageId
            ? assistantMessageId
            : getCanonicalChatMessageId("assistant", launchResult.task_id);
        const canonicalUserId =
          isClarifyReply && optimisticUserMessageId
            ? optimisticUserMessageId
            : getCanonicalChatMessageId("user", launchResult.task_id);
        updateMessages((previous) =>
          previous.map((message) =>
            message.id === assistantMessageId
              ? {
                  ...message,
                  id: canonicalAssistantId,
                  task_id: launchResult.task_id,
                  status: "running" as const,
                }
              : message.id === optimisticUserMessageId
                ? {
                    ...message,
                    id: canonicalUserId,
                    task_id: launchResult.task_id,
                  }
                : message,
          ),
        );
        liveAssistantMessageIdRef.current = canonicalAssistantId;
        liveTaskIdRef.current = launchResult.task_id;
        // Register the new task in pagination state for the anchor.
        if (!isClarifyReply) {
          dispatchChatSessionRuntime({
            type: "REGISTER_NEW_TASK",
            sessionId: launchResult.session_id ?? activeSessionId,
            task: {
              task_id: launchResult.task_id,
              preview: pendingMessage.trim().slice(0, 100),
              status: "running",
              created_at: new Date().toISOString(),
            },
            isBrandNewSession: shouldResetConversation,
            pageSize: CHAT_HISTORY_PAGE_SIZE,
          });
        }
        void refreshSidebarData().catch((refreshError) => {
          console.error(
            "Failed to refresh session list after task launch:",
            refreshError,
          );
        });
      } catch (streamError) {
        setActiveContextTaskId(null);
        setActiveContextIteration(null);
        clearCompactStatusImmediately();
        if (
          streamError instanceof ApiError &&
          streamError.code === "session_stale" &&
          currentSessionId
        ) {
          setStaleSessionId(currentSessionId);
          void refreshSidebarData().catch(() => {});
        }
        const normalizedError =
          streamError instanceof Error
            ? streamError
            : new Error(String(streamError));
        setError(normalizedError.message);
        if (assistantMessageId) {
          const errorTime = new Date().toISOString();
          updateMessages((previous) =>
            previous.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    status: "error",
                    errorMessage: normalizedError.message,
                    timestamp: errorTime,
                  }
                : message,
            ),
          );
        }
        setIsStreaming(false);
      }
    },
    [
      agentId,
      clearCompactStatusImmediately,
      clearCompactStatusWithMinimumDelay,
      currentProjectId,
      commitMessages,
      currentSessionId,
      discardReadyPendingFiles,
      dispatchChatSessionRuntime,
      loadSessionRuntimeDebug,
      manualCompactSkillNames,
      openSessionStream,
      prepareForProgrammaticScroll,
      readyPendingFiles,
      refreshSidebarData,
      replyTaskId,
      selectedMandatorySkills,
      selectedThinkingMode,
      selectedWebSearchProvider,
      sessionType,
      showCompactStatus,
      testSnapshot,
      updateMessages,
    ],
  );

  /**
   * Sends an explicit approval or rejection reply for a pending inline skill change request.
   */
  const handleSkillChangeDecision = useCallback((
    decision: "approve" | "reject",
    taskId: string,
    _request: SkillChangeApprovalRequest,
  ) => {
    setError(null);
    setIsStreaming(true);
    setReplyTaskId(null);
    setActiveContextTaskId(null);
    setActiveContextIteration(null);
    clearCompactStatusImmediately();
    updateMessages((messagesSnapshot) =>
      messagesSnapshot.map((message) =>
        message.task_id === taskId && message.role === "assistant"
          ? {
              ...message,
              status: "running" as const,
              content:
                message.pendingUserAction?.kind === "skill_change_approval"
                  ? ""
                  : message.content,
              pendingUserAction: undefined,
            }
          : message,
      ),
    );

    void submitReactUserAction(taskId, decision)
      .then(() => {
        void refreshSidebarData().catch((refreshError) => {
          console.error(
            "Failed to refresh session list after user action:",
            refreshError,
          );
        });
      })
      .catch((actionError) => {
        console.error("Failed to submit pending user action:", actionError);
        setIsStreaming(false);
        setError("Failed to submit approval decision");
        if (currentSessionIdRef.current) {
          void getFullSessionHistory(currentSessionIdRef.current, {
            limit: CHAT_HISTORY_PAGE_SIZE,
          })
            .then((history) => {
              loadHistoryResponse(history, true);
            })
            .catch((historyError) => {
              console.error(
                "Failed to restore session after approval submission failed:",
                historyError,
              );
            });
        }
      });
  }, [
    loadHistoryResponse,
    clearCompactStatusImmediately,
    refreshSidebarData,
    updateMessages,
  ]);

  /**
   * Tracks recursion accordion state per message without leaking that detail into message models.
   */
  const toggleRecursion = useCallback((messageId: string, recursionUid: string) => {
    pauseAutoScroll();
    const key = `${messageId}-${recursionUid}`;
    setExpandedRecursions((previous) => ({
      ...previous,
      [key]: !previous[key],
    }));
  }, [pauseAutoScroll]);

  /**
   * Mirrors the latest composer draft into a ref so send and estimate paths
   * can read it without promoting each keystroke into top-level React state.
   */
  const handleDraftChange = useCallback(
    (value: string) => {
      draftMessageRef.current = value;
      scheduleDraftContextUsageEstimate();
    },
    [scheduleDraftContextUsageEstimate],
  );

  /**
   * Sends one explicit draft payload from the locally owned composer state.
   */
  const handleSubmitMessage = useCallback(
    (message: string) => {
      if (hasUploadingFiles) {
        return;
      }
      // Mid-task input: inject user message into the running task.
      if (isStreaming && liveTaskIdRef.current) {
        setPendingMidTaskInput(message);
        void submitMidTaskInput(liveTaskIdRef.current, message).then(() => {
          setComposerResetSignal((prev) => prev + 1);
          draftMessageRef.current = "";
        }).catch(() => {
          setPendingMidTaskInput(null);
        });
        return;
      }
      if (isStreaming) {
        return;
      }
      if (
        sessionType === "studio_test" &&
        agentClientState === "draining_for_upgrade"
      ) {
        // Why: a half-upgraded extension cannot serve the test chat without
        // risking inconsistent runtime behavior; let the draining state finish.
        setError(
          "Agent is preparing for an extension upgrade. New tasks are blocked until the upgrade finishes.",
        );
        return;
      }
      if (message.trim().length === 0 && readyPendingFiles.length === 0 && !isCompactMode) {
        return;
      }

      void sendMessage({ messageOverride: message });
    },
    [
      agentClientState,
      hasUploadingFiles,
      isCompactMode,
      isStreaming,
      readyPendingFiles.length,
      sendMessage,
      sessionType,
    ],
  );

  /**
   * Rewinds conversation to the given task, replaces the user message, and
   * starts a fresh task from that point.
   */
  const handleEditSubmit = useCallback(
    async (taskId: string, newMessage: string, rewindScope: RewindScope) => {
      if (isStreaming) return;

      setIsStreaming(true);
      setError(null);
      clearCompactStatusImmediately();

      try {
        const launchResult = await editReactTask(
          taskId,
          newMessage,
          rewindScope,
        );

        // Truncate local messages: find the user message for this task and
        // keep everything before it.
        const editIndex = messagesRef.current.findIndex(
          (m) => m.role === "user" && m.task_id === taskId,
        );
        if (editIndex === -1) {
          // Fallback: just append (should not happen)
          commitMessages([]);
        } else {
          commitMessages(messagesRef.current.slice(0, editIndex));
        }

        // Create optimistic user + assistant messages for the new task.
        const userTimestamp = new Date().toISOString();
        const tempUserId = `user-${Date.now()}`;
        const tempAssistantId = `assistant-${Date.now()}`;
        const userMessage: ChatMessage = {
          id: tempUserId,
          role: "user",
          content: newMessage,
          timestamp: userTimestamp,
          task_id: launchResult.task_id,
        };
        const assistantMessage: ChatMessage = {
          id: tempAssistantId,
          role: "assistant",
          content: "",
          timestamp: new Date(Date.now() + 1).toISOString(),
          recursions: [],
          status: "running",
          task_id: launchResult.task_id,
        };
        commitMessages([
          ...messagesRef.current,
          userMessage,
          assistantMessage,
        ]);

        // Wire up the SSE stream.
        const canonicalUserId = getCanonicalChatMessageId(
          "user",
          launchResult.task_id,
        );
        const canonicalAssistantId = getCanonicalChatMessageId(
          "assistant",
          launchResult.task_id,
        );

        if (sessionStreamAbortControllerRef.current) {
          sessionStreamAbortControllerRef.current.abort();
          sessionStreamAbortControllerRef.current = null;
        }

        if (launchResult.session_id) {
          setCurrentSessionId(launchResult.session_id);
          currentSessionIdRef.current = launchResult.session_id;
          openSessionStream(
            launchResult.session_id,
            launchResult.cursor_before_start,
          );
        }

        // Remap optimistic IDs to canonical IDs.
        updateMessages((prev) =>
          prev.map((m) =>
            m.id === tempUserId
              ? { ...m, id: canonicalUserId, task_id: launchResult.task_id }
              : m.id === tempAssistantId
                ? {
                    ...m,
                    id: canonicalAssistantId,
                    task_id: launchResult.task_id,
                  }
                : m,
          ),
        );

        liveAssistantMessageIdRef.current = canonicalAssistantId;
        liveTaskIdRef.current = launchResult.task_id;

        dispatchChatSessionRuntime({
          type: "REPLACE_TASK_FROM",
          sessionId: launchResult.session_id ?? currentSessionId ?? "",
          fromTaskId: taskId,
          replacementTask: {
            task_id: launchResult.task_id,
            preview: newMessage.slice(0, 100),
            status: "running",
            created_at: userTimestamp,
          },
        });

        draftMessageRef.current = "";
        setComposerResetSignal((prev) => prev + 1);
      } catch (err) {
        setIsStreaming(false);
        if (err instanceof ApiError) {
          setError(err.message);
        } else {
          setError(
            err instanceof Error ? err.message : "Failed to edit task",
          );
        }
      }
    },
    [
      isStreaming,
      commitMessages,
      openSessionStream,
      dispatchChatSessionRuntime,
      clearCompactStatusImmediately,
      currentSessionId,
      updateMessages,
    ],
  );

  /**
   * Stabilizes approval and rejection actions so memoized timeline rows can
   * skip work when unrelated composer state changes elsewhere.
   */
  const handleApproveSkillChange = useCallback(
    (taskId: string, request: SkillChangeApprovalRequest) => {
      handleSkillChangeDecision("approve", taskId, request);
    },
    [handleSkillChangeDecision],
  );

  /**
   * Stabilizes rejection actions for memoized assistant rows.
   */
  const handleRejectSkillChange = useCallback(
    (taskId: string, request: SkillChangeApprovalRequest) => {
      handleSkillChangeDecision("reject", taskId, request);
    },
    [handleSkillChangeDecision],
  );

  /**
   * Stabilizes mandatory-skill chip mutations so the composer can memoize well.
   */
  const handleAddMandatorySkill = useCallback((skill: MandatorySkillSelection) => {
    setSelectedMandatorySkills((previous) => {
      if (previous.some((item) => item.name === skill.name)) {
        return previous;
      }
      if (isCompactSkillSelection(skill)) {
        return [skill];
      }
      const withoutCompact = previous.filter(
        (item) => !isCompactSkillSelection(item),
      );
      return [...withoutCompact, skill];
    });
  }, []);

  /**
   * Removes one selected skill without recreating the callback every render.
   */
  const handleRemoveMandatorySkill = useCallback((skillName: string) => {
    setSelectedMandatorySkills((previous) =>
      previous.filter((skill) => skill.name !== skillName),
    );
  }, []);

  /**
   * Keeps clarify-dismissal referentially stable for the memoized composer.
   */
  const handleCancelReply = useCallback(() => {
    setReplyTaskId(null);
  }, []);

  /**
   * Create one temporary development surface binding for the active chat
   * session so the debug affordance and header icon can share the same host
   * state instead of maintaining parallel launch paths.
   */
  const handleCreateSurfaceDevSession = useCallback(
    async (nextSurfaceKey: string, nextRuntimeUrl: string) => {
      if (!currentSessionId || isCreatingSurfaceSession) {
        return;
      }

      setIsCreatingSurfaceSession(true);
      setSurfaceCreationError(null);

      try {
        const nextSurfaceSession = await createDevSurfaceSession({
          sessionId: currentSessionId,
          surfaceKey: nextSurfaceKey,
          devServerUrl: nextRuntimeUrl,
        });
        setActiveInstalledSurface(null);
        setActiveInstalledSurfaceSession(null);
        setActiveSurfaceSession(nextSurfaceSession);
        handleExtensionDockOpenChange(true);
        onSurfaceDevAttached?.();
      } catch (error) {
        setSurfaceCreationError(
          error instanceof Error
            ? error.message
            : "Failed to attach development surface.",
        );
      } finally {
        setIsCreatingSurfaceSession(false);
      }
    },
    [
      currentSessionId,
      handleExtensionDockOpenChange,
      isCreatingSurfaceSession,
      onSurfaceDevAttached,
    ],
  );

  /**
   * Opens one installed surface through the same shared dock host used by dev
   * sessions so product and debug entry points stay behaviorally aligned.
   */
  const handleOpenInstalledSurface = useCallback(
    async (surface: InstalledChatSurfaceDescriptor) => {
      if (!currentSessionId || isCreatingSurfaceSession) {
        return;
      }

      const isSameInstalledSurface =
        activeInstalledSurface?.installationId === surface.installationId &&
        activeInstalledSurface.surfaceKey === surface.surfaceKey;
      if (isSameInstalledSurface && isExtensionDockOpen) {
        handleExtensionDockOpenChange(false);
        return;
      }

      setIsCreatingSurfaceSession(true);
      setSurfaceCreationError(null);
      try {
        const nextInstalledSurfaceSession = await createInstalledSurfaceSession({
          sessionId: currentSessionId,
          extensionInstallationId: surface.installationId,
          surfaceKey: surface.surfaceKey,
        });
        setActiveSurfaceSession(null);
        setActiveInstalledSurface(surface);
        setActiveInstalledSurfaceSession(nextInstalledSurfaceSession);
        handleExtensionDockOpenChange(true);
      } catch (error) {
        setSurfaceCreationError(
          error instanceof Error
            ? error.message
            : "Failed to open the installed surface.",
        );
      } finally {
        setIsCreatingSurfaceSession(false);
      }
    },
    [
      activeInstalledSurface,
      currentSessionId,
      handleExtensionDockOpenChange,
      isCreatingSurfaceSession,
      isExtensionDockOpen,
    ],
  );

  /**
   * Apply one streamed preview intent by reusing the shared workspace-editor
   * dock instead of introducing a second preview-only shell.
   */
  const handleOpenWorkspacePreviewIntent = useCallback(
    ({
      activePreviewId,
      availablePreviews,
      preview,
    }: {
      preview: PreviewEndpointResponse;
      availablePreviews: PreviewEndpointResponse[];
      activePreviewId: string | null;
    }) => {
      if (
        processedPreviewIntentIdsRef.current.has(preview.preview_id)
      ) {
        return;
      }
      processedPreviewIntentIdsRef.current.add(preview.preview_id);
      pendingPreviewSurfaceOpenIdRef.current = preview.preview_id;
      setPreviewEndpoints((previous) => {
        if (availablePreviews.length > 0) {
          return availablePreviews;
        }
        return upsertPreviewEndpointList(previous, preview);
      });
      if (activePreviewId) {
        const matchingPreview = availablePreviews.find(
          (item) => item.preview_id === activePreviewId,
        );
        setActivePreviewEndpoint(matchingPreview ?? preview);
      } else {
        setActivePreviewEndpoint(preview);
      }

      if (
        activeSurfaceSession?.surface_key === OFFICIAL_SAMPLE_SURFACE_KEY
      ) {
        pendingPreviewSurfaceOpenIdRef.current = null;
        handleExtensionDockOpenChange(true);
        return;
      }

      if (
        activeInstalledSurfaceSession &&
        activeInstalledSurface?.surfaceKey === OFFICIAL_SAMPLE_SURFACE_KEY
      ) {
        pendingPreviewSurfaceOpenIdRef.current = null;
        handleExtensionDockOpenChange(true);
        return;
      }
    },
    [
      activeInstalledSurface,
      activeInstalledSurfaceSession,
      activeSurfaceSession,
      handleExtensionDockOpenChange,
    ],
  );

  openWorkspacePreviewIntentRef.current = (previewIntent) => {
    void handleOpenWorkspacePreviewIntent(previewIntent);
  };

  useEffect(() => {
    if (
      !activePreviewEndpoint ||
      pendingPreviewSurfaceOpenIdRef.current !== activePreviewEndpoint.preview_id
    ) {
      return;
    }

    if (activeSurfaceSession?.surface_key === OFFICIAL_SAMPLE_SURFACE_KEY) {
      pendingPreviewSurfaceOpenIdRef.current = null;
      handleExtensionDockOpenChange(true);
      return;
    }

    if (
      activeInstalledSurfaceSession &&
      activeInstalledSurface?.surfaceKey === OFFICIAL_SAMPLE_SURFACE_KEY
    ) {
      pendingPreviewSurfaceOpenIdRef.current = null;
      handleExtensionDockOpenChange(true);
      return;
    }

    const installedWorkspaceEditor = installedChatSurfaces.find(
      (surface) => surface.surfaceKey === OFFICIAL_SAMPLE_SURFACE_KEY,
    );
    if (!installedWorkspaceEditor || !currentSessionId || isCreatingSurfaceSession) {
      return;
    }

    pendingPreviewSurfaceOpenIdRef.current = null;
    void handleOpenInstalledSurface(installedWorkspaceEditor);
  }, [
    activeInstalledSurface,
    activeInstalledSurfaceSession,
    activePreviewEndpoint,
    activeSurfaceSession,
    currentSessionId,
    handleExtensionDockOpenChange,
    handleOpenInstalledSurface,
    installedChatSurfaces,
    isCreatingSurfaceSession,
  ]);

  const surfaceDevDebugSection = useMemo(() => {
    return {
      key: "surface-dev",
      title: (
        <div className="flex items-center gap-1.5">
          <span>Surface Dev</span>
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex items-center text-muted-foreground transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:outline-none"
                  aria-label="Surface Dev details"
                >
                  <Info className="h-3.5 w-3.5 cursor-help" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs leading-relaxed">
                Attach one local surface runtime to this chat session and open it
                from the chat header.
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      ),
      content: (
        <SurfaceDevDebugContent
          activeSurfaceSession={activeSurfaceSession}
          currentSessionId={currentSessionId}
          isCreatingSurfaceSession={isCreatingSurfaceSession}
          surfaceCreationError={surfaceCreationError}
          onAttach={(runtimeUrl) => {
            void handleCreateSurfaceDevSession(
              OFFICIAL_SAMPLE_SURFACE_KEY,
              runtimeUrl,
            );
          }}
        />
      ),
    };
  }, [
    activeSurfaceSession,
    currentSessionId,
    handleCreateSurfaceDevSession,
    isCreatingSurfaceSession,
    surfaceCreationError,
  ]);

  useRegisterChatDebugPanelSection(surfaceDevDebugSection);

  const headerSurfaceButtons = useMemo(() => {
    if (isExtensionDockOpen) {
      return [];
    }

    const installedButtons = installedChatSurfaces.map((surface) => {
      const isActive =
        activeInstalledSurface?.packageId === surface.packageId &&
        activeInstalledSurface.surfaceKey === surface.surfaceKey;
      const IconComponent = resolveIcon(surface.icon);

      if (IconComponent) {
        return (
          <Tooltip key={`installed:${surface.packageId}:${surface.surfaceKey}`}>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => {
                  void handleOpenInstalledSurface(surface);
                }}
                className={`pointer-events-auto inline-flex h-8 w-8 items-center justify-center rounded-lg border bg-background/95 shadow-sm backdrop-blur transition-colors ${
                  isActive && isExtensionDockOpen
                    ? "border-primary/50 text-foreground"
                    : "border-border/70 text-muted-foreground hover:bg-accent/70 hover:text-foreground"
                }`}
                aria-label={surface.displayName}
              >
                <IconComponent className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              {surface.displayName}
            </TooltipContent>
          </Tooltip>
        );
      }

      return (
        <button
          key={`installed:${surface.packageId}:${surface.surfaceKey}`}
          type="button"
          onClick={() => {
            void handleOpenInstalledSurface(surface);
          }}
          className={`pointer-events-auto inline-flex h-8 items-center gap-2 rounded-lg border bg-background/95 px-3 text-xs font-medium shadow-sm backdrop-blur transition-colors ${
            isActive && isExtensionDockOpen
              ? "border-primary/50 text-foreground"
              : "border-border/70 text-muted-foreground hover:bg-accent/70 hover:text-foreground"
          }`}
          aria-label={`Open surface ${surface.surfaceKey}`}
          title={surface.displayName}
        >
          {surface.logoUrl ? (
            <img
              src={surface.logoUrl}
              alt=""
              className="h-4 w-4 rounded-sm object-cover"
            />
          ) : (
            <span className="inline-flex h-4 w-4 items-center justify-center rounded-sm bg-muted text-[9px] font-semibold uppercase text-foreground/80">
              {surface.displayName.slice(0, 1)}
            </span>
          )}
          <span className="max-w-28 truncate">{surface.displayName}</span>
        </button>
      );
    });

    const isDevSurfaceActive =
      activeSurfaceSession !== null &&
      activeInstalledSurface === null &&
      isExtensionDockOpen;

    const devButtons = activeSurfaceSession
      ? [
          <button
            key={`dev:${activeSurfaceSession.surface_session_id}`}
            type="button"
            onClick={() => {
              setActiveInstalledSurface(null);
              setActiveInstalledSurfaceSession(null);
              handleExtensionDockOpenChange(!isDevSurfaceActive);
            }}
            className={`pointer-events-auto inline-flex h-8 items-center gap-2 rounded-lg border bg-background/95 px-3 text-xs font-medium shadow-sm backdrop-blur transition-colors ${
              isDevSurfaceActive
                ? "border-primary/50 text-foreground"
                : "border-border/70 text-muted-foreground hover:bg-accent/70 hover:text-foreground"
            }`}
            aria-label={`Toggle surface ${activeSurfaceSession.surface_key}`}
          >
            <span className="inline-flex h-5 items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-300">
              Dev
            </span>
            <span className="max-w-32 truncate">
              {activeSurfaceSession.display_name}
            </span>
          </button>,
        ]
      : [];

    return [...installedButtons, ...devButtons];
  }, [
    activeInstalledSurface,
    handleOpenInstalledSurface,
    handleExtensionDockOpenChange,
    activeSurfaceSession,
    installedChatSurfaces,
    isExtensionDockOpen,
  ]);

  const conversationRounds = useConversationRounds(taskSummaries, loadedTaskIds);

  const isConversationEmpty = messages.length === 0;
  const composerTaskPlan = useMemo(
    () => deriveComposerTaskPlan(messages),
  [messages],
  );
  const replyTarget = useMemo(
    () => findReplyTarget(messages, replyTaskId),
    [messages, replyTaskId],
  );
  const selectedProject = useMemo(
    () =>
      sidebarProjects.find((project) => project.project_id === currentProjectId) ??
      null,
    [currentProjectId, sidebarProjects],
  );
  const accessProject = useMemo(
    () =>
      projects.find((project) => project.project_id === accessProjectId) ?? null,
    [accessProjectId, projects],
  );
  const isNewSessionDraftActive =
    currentSessionId === null && currentProjectId === null;
  const chatWorkspacePane = (
    <div
      className="relative flex min-w-0 flex-1 flex-col overflow-hidden"
      aria-busy={isLoadingSession}
    >
      <SessionLoadingOverlay isActive={isLoadingSession} />
      <RoundAnchor
        rounds={conversationRounds}
        onNavigateToRound={(round) => { void handleNavigateToRound(round); }}
        scrollContainerRef={scrollContainerRef}
      />
      <ScrollArea
        viewportRef={scrollContainerRef}
        className="flex-1"
      >
        <div className="mx-auto max-w-3xl px-4 pb-2 pt-4 [overflow-anchor:none]">
          {selectedProject && currentSessionId === null && messages.length === 0 ? (
            <div className="rounded-3xl border border-border/70 bg-card/70 p-6 shadow-sm">
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                  Project Workspace
                </p>
                <h2 className="text-2xl font-semibold tracking-tight text-foreground">
                  {selectedProject.name}
                </h2>
                <p className="text-sm text-muted-foreground">
                  Your next message will start a new session inside this shared
                  project workspace.
                </p>
              </div>
              <div className="mt-5 flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => {
                    void handleNewSession();
                  }}
                  className="inline-flex h-9 items-center rounded-lg border border-input bg-background px-4 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground"
                >
                  New Private Session
                </button>
                {selectedProject.sessions.length > 0 ? (
                  <button
                    type="button"
                    onClick={() => {
                      void handleSelectSession(selectedProject.sessions[0].session_id);
                    }}
                    className="inline-flex h-9 items-center rounded-lg border border-border bg-accent/50 px-4 text-sm font-medium transition-colors hover:bg-accent"
                  >
                    Open Latest Session
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <ConversationView
              messages={messages}
              agentName={agentName}
              expandedRecursions={expandedRecursions}
              isStreaming={isStreaming}
              onToggleRecursion={toggleRecursion}
              onReplyTask={setReplyTaskId}
              onEditSubmit={handleEditSubmit}
              onApproveSkillChange={handleApproveSkillChange}
              onRejectSkillChange={handleRejectSkillChange}
            />
          )}
          <div className="h-1" />
        </div>
      </ScrollArea>
      {isLoadingOlder && (
        <div className="pointer-events-none absolute left-1/2 top-3 z-10 flex -translate-x-1/2 items-center rounded-full border border-border/70 bg-background/95 px-3 py-1.5 shadow-sm backdrop-blur">
          <Spinner size={14} className="text-muted-foreground" />
          <span className="ml-2 text-xs text-muted-foreground">Loading...</span>
        </div>
      )}

      <CompactStatusPill message={compactStatusMessage} />

      {sessionType === "studio_test" && agentClientState === "draining_for_upgrade" ? (
        <div className="mx-3 mb-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          This agent is preparing for an extension upgrade. New tasks are paused until
          the safe upgrade finishes or is forced to complete.
        </div>
      ) : null}

      <ChatComposer
        sessionId={currentSessionId}
        error={error}
        compactStatusMessage={compactStatusMessage}
        pendingMidTaskInput={pendingMidTaskInput}
        replyTarget={replyTarget}
        pendingFiles={pendingFiles}
        isStreaming={isStreaming}
        canSendMessage={
          staleSessionId === null &&
          migratedSessionId === null &&
          !isManualCompacting
        }
        isInputDisabled={isManualCompacting}
        isConversationEmpty={isConversationEmpty}
        hasUploadingFiles={hasUploadingFiles}
        taskPlan={composerTaskPlan}
        contextUsage={contextUsage}
        isContextUsageLoading={isContextUsageLoading}
        isCompacting={compactStatusMessage !== null}
        supportsImageInput={supportsImageInput}
        thinkingModes={thinkingModes}
        selectedThinkingMode={selectedThinkingMode}
        webSearchProviders={webSearchProviders}
        selectedWebSearchProvider={selectedWebSearchProvider}
        availableMandatorySkills={availableMandatorySkills}
        selectedMandatorySkills={selectedMandatorySkills}
        imageInputRef={imageInputRef}
        documentInputRef={documentInputRef}
        resetDraftSignal={composerResetSignal}
        focusSignal={composerFocusSignal}
        onInputChange={handleDraftChange}
        onAddMandatorySkill={handleAddMandatorySkill}
        onRemoveMandatorySkill={handleRemoveMandatorySkill}
        onThinkingModeChange={setSelectedThinkingMode}
        onWebSearchProviderChange={setSelectedWebSearchProvider}
        onPaste={handlePaste}
        onSubmitMessage={handleSubmitMessage}
        onStop={handleStop}
        onCancelReply={handleCancelReply}
        onImageInputChange={handleFileInputChange}
        onDocumentInputChange={handleDocumentInputChange}
        onRemovePendingFile={removePendingFile}
      />
    </div>
  );

  const isSidebarVisible = !isExtensionDockOpen && isSidebarOpen;
  const shouldRenderDockLayout = isExtensionDockMounted;
  const chatPanelSize = 100 - renderedDockPanelSize;
  const activeDockMinWidth =
    activeInstalledSurface?.minWidth && activeInstalledSurface.minWidth > 0
      ? activeInstalledSurface.minWidth
      : 420;

  return (
    <SidebarProvider
      defaultOpen
      open={isSidebarVisible}
      onOpenChange={setIsSidebarOpen}
    >
      <SessionSidebar
        sessions={standaloneSessions}
        projects={sidebarProjects}
        currentSessionId={currentSessionId}
        currentProjectId={currentProjectId}
        isNewSessionDraftActive={isNewSessionDraftActive}
        isLoadingSession={isLoadingSession}
        hasInitializedSessions={isInitialized}
        isStreaming={isStreaming}
        sidebarTitleIcon={sidebarTitleIcon}
        sidebarTitle={sidebarTitle}
        onNewSession={handleNewSession}
        onCreateProject={handleCreateProject}
        onSelectProject={handleSelectProject}
        onRenameProject={handleRenameProject}
        onManageProjectAccess={handleManageProjectAccess}
        onDeleteProject={handleDeleteProject}
        onSelectSession={handleSelectSession}
        onRenameSession={handleRenameSession}
        onTogglePinSession={handleTogglePinSession}
        onDeleteSession={handleDeleteSession}
        navigationItems={sidebarNavigationItems}
        footer={sidebarFooter}
      />

      <ProjectAccessDialog
        open={accessProjectId !== null}
        onOpenChange={(open) => {
          if (!open) {
            setAccessProjectId(null);
          }
        }}
        projectId={accessProjectId}
        projectName={accessProject?.name ?? null}
        onSaved={async () => {
          await refreshSidebarData();
        }}
      />

      <SidebarInset className="relative flex flex-1 overflow-hidden bg-background text-foreground">
        <div className="pointer-events-none absolute left-3 top-3 z-20">
          <SidebarTrigger className="pointer-events-auto h-8 w-8 rounded-lg bg-transparent text-muted-foreground shadow-none hover:bg-accent/70 hover:text-foreground" />
        </div>
        {headerSurfaceButtons.length > 0 ? (
          <TooltipProvider delayDuration={150}>
            <div className="pointer-events-none absolute right-3 top-3 z-20 flex items-center gap-2">
              {headerSurfaceButtons}
            </div>
          </TooltipProvider>
        ) : null}

        {shouldRenderDockLayout ? (
          <ResizablePanelGroup
            direction="horizontal"
            className="min-h-0 flex-1"
            onLayout={(sizes) => {
              const nextDockSize = sizes[1] ?? 0;
              if (nextDockSize > 0) {
                setDockPanelSize(nextDockSize);
                setRenderedDockPanelSize(nextDockSize);
              }
            }}
          >
            <ResizablePanel size={chatPanelSize} minSize={26}>
              {chatWorkspacePane}
            </ResizablePanel>
            <ResizableHandle
              withHandle
              className={`bg-border/70 transition-opacity duration-200 ${
                renderedDockPanelSize <= 0
                  ? "pointer-events-none opacity-0"
                  : "opacity-100"
              }`}
            />
            <ResizablePanel
              size={renderedDockPanelSize}
              minSize={0}
              minSizePx={activeDockMinWidth}
            >
              <ExtensionDock
                isOpen={isExtensionDockMounted}
                onOpenChange={handleExtensionDockOpenChange}
                activeSurfaceSession={activeSurfaceSession}
                activeInstalledSurface={activeInstalledSurface}
                activeInstalledSurfaceSession={activeInstalledSurfaceSession}
                previewEndpoints={previewEndpoints}
                activePreviewEndpoint={activePreviewEndpoint}
                reconnectablePreviewSuggestion={reconnectablePreviewSuggestion}
              />
            </ResizablePanel>
          </ResizablePanelGroup>
        ) : (
          <div className="flex min-h-0 flex-1">{chatWorkspacePane}</div>
        )}
      </SidebarInset>
      <StaleSessionDialog
        isOpen={
          (staleSessionId !== null || migratedSessionId !== null) &&
          !isStaleBannerDismissed
        }
        onMigrate={() => {
          void handleMigrateStaleSession();
        }}
        onClose={handleDismissStaleBanner}
        isMigrating={isMigratingStaleSession}
        migratedSessionId={migratedSessionId}
        onGoToMigrated={handleGoToMigratedSession}
      />
      <AutomationCreateDialog
        open={isAutomationDialogOpen}
        agents={automationAgents}
        defaultAgentId={agentId}
        proposal={automationProposal ?? undefined}
        onClose={() => {
          setIsAutomationDialogOpen(false);
          setAutomationProposal(null);
        }}
        onCreated={() => {
          setIsAutomationDialogOpen(false);
          setAutomationProposal(null);
        }}
      />
    </SidebarProvider>
  );
}

export default ChatContainer;
