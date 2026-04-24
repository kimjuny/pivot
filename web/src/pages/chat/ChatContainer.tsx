import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  cancelReactTask,
  createProject,
  createDevSurfaceSession,
  createInstalledSurfaceSession,
  createSession,
  deleteProject,
  deleteSession,
  getAgentWebSearchBindings,
  getAgentExtensionPackages,
  getFullSessionHistory,
  getPreviewEndpoints,
  getReactContextUsage,
  getReactRuntimeSkills,
  getReactSessionRuntimeDebug,
  listProjects,
  listSessions,
  startReactTask,
  submitReactUserAction,
  updateProject,
  updateSession,
  type ProjectResponse,
  type DevSurfaceSessionResponse,
  type AgentExtensionPackage,
  type ReactContextUsageSummary,
  type ReactSessionRuntimeDebug,
  type InstalledSurfaceSessionResponse,
  type PreviewEndpointResponse,
  type SessionListItem,
  type SessionResponse,
  type WebSearchBinding,
  getApiBaseUrl,
  httpClient,
} from "@/utils/api";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { Input } from "@/components/ui/input";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  AUTH_EXPIRED_EVENT,
  getAuthToken,
  isTokenValid,
} from "@/contexts/auth-core";

import { ChatComposer } from "./components/ChatComposer";
import { ConversationView } from "./components/ConversationView";
import { ExtensionDock } from "./components/ExtensionDock";
import type { InstalledChatSurfaceDescriptor } from "./components/ExtensionDock";
import { useRegisterChatDebugPanelSection } from "./components/ChatDebugPanelContext";
import { SessionSidebar } from "./components/SessionSidebar";
import { useChatAutoScroll } from "./hooks/useChatAutoScroll";
import { useChatUploads } from "./hooks/useChatUploads";
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

const COMPACT_STATUS_MIN_VISIBLE_MS = 2200;
const DOCK_TRANSITION_MS = 200;
const OFFICIAL_SAMPLE_SURFACE_KEY = "workspace-editor";
const LOCAL_VITE_RUNTIME_URL = "http://127.0.0.1:5173";

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

/**
 * Flatten enabled agent extension packages into one header-friendly installed
 * chat surface list.
 */
function toInstalledChatSurfaces(
  packages: AgentExtensionPackage[],
): InstalledChatSurfaceDescriptor[] {
  const installedSurfaces: InstalledChatSurfaceDescriptor[] = [];

  packages.forEach((pkg) => {
    const selectedBinding = pkg.selected_binding;
    const selectedInstallation = selectedBinding?.installation;
    if (
      !selectedBinding ||
      !selectedBinding.enabled ||
      !selectedInstallation ||
      selectedInstallation.status !== "active"
    ) {
      return;
    }

    const contributionItemsByKey = new Map(
      selectedInstallation.contribution_items
        .filter((item) => item.type === "chat_surface")
        .map((item) => [item.key ?? item.name, item]),
    );
    (selectedInstallation.contribution_summary.chat_surfaces ?? []).forEach(
      (surfaceKey) => {
        const contributionItem = contributionItemsByKey.get(surfaceKey);
        const normalizedMinWidth =
          typeof contributionItem?.min_width === "number" &&
          Number.isFinite(contributionItem.min_width) &&
          contributionItem.min_width > 0
            ? contributionItem.min_width
            : null;
        installedSurfaces.push({
          installationId: selectedInstallation.id,
          packageId: pkg.package_id,
          surfaceKey,
          displayName:
            contributionItem?.name && contributionItem.name.trim().length > 0
              ? contributionItem.name.trim()
              : surfaceKey,
          logoUrl: pkg.logo_url,
          description:
            contributionItem?.description && contributionItem.description.trim().length > 0
              ? contributionItem.description.trim()
              : pkg.description,
          minWidth: normalizedMinWidth,
        });
      },
    );
  });

  return installedSurfaces;
}

function extractWorkspacePreviewIntent(
  event: ReactStreamEvent,
): {
  preview: PreviewEndpointResponse;
  availablePreviews: PreviewEndpointResponse[];
  activePreviewId: string | null;
} | null {
  if (event.type !== "tool_result" || !event.data || typeof event.data !== "object") {
    return null;
  }

  const toolResults = (event.data as { tool_results?: unknown }).tool_results;
  if (!Array.isArray(toolResults)) {
    return null;
  }

  for (const item of toolResults) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const result = (item as { result?: unknown; success?: unknown }).result;
    const success = (item as { success?: unknown }).success;
    if (success !== true || !result || typeof result !== "object") {
      continue;
    }

    const uiIntent = (result as { ui_intent?: unknown }).ui_intent;
    if (!uiIntent || typeof uiIntent !== "object") {
      continue;
    }
    if (
      (uiIntent as { type?: unknown }).type !== "open_workspace_web_preview"
    ) {
      continue;
    }

    const preview = normalizePreviewEndpoint(
      (uiIntent as { preview?: unknown }).preview,
    );
    if (!preview) {
      continue;
    }
    return {
      preview,
      availablePreviews: normalizePreviewEndpointList(
        (uiIntent as { available_previews?: unknown }).available_previews,
      ),
      activePreviewId:
        typeof (uiIntent as { active_preview_id?: unknown }).active_preview_id ===
        "string"
          ? String(
              (uiIntent as { active_preview_id?: unknown }).active_preview_id,
            )
          : null,
    };
  }

  return null;
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
    type: session.type ?? "consumer",
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

  if (event.type === "summary") {
    const summaryPayload = event.data as { current_plan?: PlanStepData[] };
    return Array.isArray(summaryPayload.current_plan)
      ? summaryPayload.current_plan
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

/**
 * Coordinates the page-scoped chat state and delegates visual rendering to smaller components.
 */
function ChatContainer({
  agentId,
  sessionType = "consumer",
  initialSessionId,
  testSnapshot,
  testSnapshotHash,
  agentName,
  agentToolIds,
  primaryLlmId,
  sessionIdleTimeoutMinutes,
  sidebarNavigationItems,
  sidebarTitleIcon,
  sidebarTitle,
  sidebarFooter,
  onRuntimeDebugChange,
}: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRecursions, setExpandedRecursions] = useState<
    Record<string, boolean>
  >({});
  const [replyTaskId, setReplyTaskId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState<boolean>(false);
  const [isInitialized, setIsInitialized] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isExtensionDockOpen, setIsExtensionDockOpen] = useState(false);
  const [isExtensionDockMounted, setIsExtensionDockMounted] = useState(false);
  const [dockPanelSize, setDockPanelSize] = useState(58);
  const [renderedDockPanelSize, setRenderedDockPanelSize] = useState(0);
  const [surfaceRuntimeUrlInput, setSurfaceRuntimeUrlInput] = useState(
    LOCAL_VITE_RUNTIME_URL,
  );
  const [isCreatingSurfaceSession, setIsCreatingSurfaceSession] =
    useState(false);
  const [surfaceCreationError, setSurfaceCreationError] = useState<
    string | null
  >(null);
  const [installedChatSurfaces, setInstalledChatSurfaces] = useState<
    InstalledChatSurfaceDescriptor[]
  >([]);
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
  const [webSearchProviders, setWebSearchProviders] = useState<
    ChatWebSearchProviderOption[]
  >([]);
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
  const [composerResetSignal, setComposerResetSignal] = useState(0);
  const messagesRef = useRef<ChatMessage[]>([]);
  const draftMessageRef = useRef("");
  const currentSessionIdRef = useRef<string | null>(null);
  const sessionStreamAbortControllerRef = useRef<AbortController | null>(null);
  const sessionStreamReconnectTimerRef = useRef<number | null>(null);
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
  } = useChatUploads(primaryLlmId);
  const { scrollContainerRef, handleScroll, prepareForProgrammaticScroll } =
    useChatAutoScroll(messages);
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

      const previewIntent = extractWorkspacePreviewIntent(event);
      if (previewIntent) {
        openWorkspacePreviewIntentRef.current(previewIntent);
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
          void getFullSessionHistory(currentSessionId)
            .then((history) => {
              const nextMessages = buildMessagesFromHistory(history.tasks);
              applyHistoryMessages(nextMessages);
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

      if (event.type === "compact_start") {
        showCompactStatus(
          "Compacting context. Please wait before stopping.",
        );
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
          clearCompactStatusImmediately();
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
          clearCompactStatusImmediately();
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
                timestamp: event.timestamp,
                errorMessage: undefined,
              };
            }

            return {
              ...message,
              recursions: updatedRecursions,
              pendingUserAction: undefined,
              status: "completed" as const,
              errorMessage: undefined,
              timestamp: event.timestamp,
              totalTokens: event.total_tokens ?? message.totalTokens,
            };
          }),
        );
        return;
      }

      const canAppendToCompletedRecursion =
        event.type === "tool_call" || event.type === "tool_result";
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
      } else if (event.type === "observe") {
        nextRecursion = {
          ...nextRecursion,
          observe: event.delta ?? "",
          tokens: event.tokens ?? currentRecursion.tokens,
        };
      } else if (event.type === "reasoning") {
        nextRecursion = {
          ...nextRecursion,
          thinking: `${currentRecursion.thinking ?? ""}${event.delta ?? ""}`,
          tokens: event.tokens ?? currentRecursion.tokens,
        };
      } else if (event.type === "reason") {
        nextRecursion = {
          ...nextRecursion,
          reason: event.delta ?? "",
          tokens: event.tokens ?? currentRecursion.tokens,
        };
      } else if (event.type === "summary") {
        nextRecursion = {
          ...nextRecursion,
          summary: event.delta ?? "",
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
      } else if (event.type === "tool_call" || event.type === "tool_result") {
        nextRecursion = {
          ...nextRecursion,
          status: "completed",
          endTime: event.timestamp,
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
            currentPlan: nextCurrentPlan ?? message.currentPlan,
          };
        }),
      );
    },
    [
      clearCompactStatusImmediately,
      clearCompactStatusWithMinimumDelay,
      applyHistoryMessages,
      currentSessionId,
      loadSessionRuntimeDebug,
      refreshSidebarData,
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
        }

        if (
          !controller.signal.aborted &&
          currentSessionIdRef.current === sessionId
        ) {
          sessionStreamReconnectTimerRef.current = window.setTimeout(() => {
            void connect();
          }, 1000);
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
        const { sessions: existingSessions } = await refreshSidebarData();

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
            try {
              const history = await getFullSessionHistory(autoSelectedSessionId);
              const nextMessages = buildMessagesFromHistory(history.tasks);
              applyHistoryMessages(nextMessages);
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
          setCurrentProjectId(null);
          setCurrentSessionId(null);
          currentSessionIdRef.current = null;
          setReplyTaskId(null);
          setActiveContextTaskId(null);
          setActiveContextIteration(null);
          syncLiveRefsFromMessages([]);
          commitMessages([]);
          setIsStreaming(false);
          stopSessionStream();
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
    isLoadingSession,
    refreshSidebarData,
    sessionIdleTimeoutMs,
    openSessionStream,
    stopSessionStream,
    applyHistoryMessages,
    commitMessages,
    sessionType,
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
    void loadSessionRuntimeDebug(currentSessionId);
  }, [currentSessionId, loadSessionRuntimeDebug]);

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
      error: runtimeDebugError,
    });
  }, [
    compactStatusMessage,
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
    let isCancelled = false;

    const loadInstalledChatSurfaces = async () => {
      try {
        const extensionPackages = await getAgentExtensionPackages(agentId);
        if (isCancelled) {
          return;
        }
        setInstalledChatSurfaces(toInstalledChatSurfaces(extensionPackages));
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
  }, [agentId]);

  useEffect(() => {
    if (!canUseWebSearch) {
      setWebSearchProviders([]);
      setSelectedWebSearchProvider(null);
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
  }, [agentId, canUseWebSearch]);

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
      draft_message: draftMessageRef.current,
      file_ids: draftFileIds,
      session_type: sessionType,
      test_snapshot: currentSessionId ? undefined : testSnapshot,
      mandatory_skill_names: selectedMandatorySkills.map((skill) => skill.name),
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
    selectedMandatorySkills,
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
    setActiveContextTaskId(null);
    setActiveContextIteration(null);
    setContextUsage(null);
    clearCompactStatusImmediately();
    prepareForProgrammaticScroll();
    await clearPendingFiles();
    stopSessionStream();

    try {
      const history = await getFullSessionHistory(sessionId);
      const nextMessages = buildMessagesFromHistory(history.tasks);
      applyHistoryMessages(nextMessages);
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
          void getFullSessionHistory(currentSessionIdRef.current)
            .then((history) => {
              const nextMessages = buildMessagesFromHistory(history.tasks);
              applyHistoryMessages(nextMessages);
            })
            .catch((historyError) => {
              console.error(
                "Failed to restore session after stop request failed:",
                historyError,
              );
            });
        }
      });
  }, [applyHistoryMessages, markTaskStopped, refreshSidebarData]);

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
          setSessions((previous) => upsertSessionListItem(previous, sessionItem));
          initialCursor = 0;
          openSessionStream(activeSessionId, initialCursor);
        }

        if (currentReplyTaskId) {
          setReplyTaskId(null);
        }
        setActiveContextIteration(null);

        if (!isTokenValid()) {
          window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
          throw new Error("Token expired or invalid. Please log in again.");
        }

        const messageTimestamp = new Date().toISOString();
        optimisticUserMessageId = isClarifyReply
          ? `user-${currentReplyTaskId}-clarify-reply-${Date.now()}`
          : `user-${Date.now()}`;
        const userMessage: ChatMessage = {
          id: optimisticUserMessageId,
          role: "user",
          content: pendingMessage,
          attachments: sentAttachments,
          mandatorySkills: selectedMandatorySkills,
          timestamp: messageTimestamp,
        };
        assistantMessageId = isClarifyReply
          ? `assistant-${currentReplyTaskId}-resume-${Date.now()}`
          : `assistant-${Date.now()}`;
        const assistantMessage: ChatMessage = {
          id: assistantMessageId,
          role: "assistant",
          content: "",
          timestamp: messageTimestamp,
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
          mandatory_skill_names: selectedMandatorySkills.map((skill) => skill.name),
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
      commitMessages,
      currentProjectId,
      currentSessionId,
      discardReadyPendingFiles,
      openSessionStream,
      prepareForProgrammaticScroll,
      readyPendingFiles,
      refreshSidebarData,
      replyTaskId,
      selectedMandatorySkills,
      selectedThinkingMode,
      selectedWebSearchProvider,
      sessionType,
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
          void getFullSessionHistory(currentSessionIdRef.current)
            .then((history) => {
              const nextMessages = buildMessagesFromHistory(history.tasks);
              applyHistoryMessages(nextMessages);
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
    applyHistoryMessages,
    clearCompactStatusImmediately,
    refreshSidebarData,
    updateMessages,
  ]);

  /**
   * Tracks recursion accordion state per message without leaking that detail into message models.
   */
  const toggleRecursion = useCallback((messageId: string, recursionUid: string) => {
    const key = `${messageId}-${recursionUid}`;
    setExpandedRecursions((previous) => ({
      ...previous,
      [key]: !previous[key],
    }));
  }, []);

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
      if (isStreaming || hasUploadingFiles) {
        return;
      }
      if (message.trim().length === 0 && readyPendingFiles.length === 0) {
        return;
      }

      void sendMessage({ messageOverride: message });
    },
    [hasUploadingFiles, isStreaming, readyPendingFiles.length, sendMessage],
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
    setSelectedMandatorySkills((previous) =>
      previous.some((item) => item.name === skill.name)
        ? previous
        : [...previous, skill],
    );
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
        handleExtensionDockOpenChange(false);
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
    [currentSessionId, handleExtensionDockOpenChange, isCreatingSurfaceSession],
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
      title: "Surface Dev",
      description:
        "Attach one local surface runtime to this chat session and open it from the chat header.",
      content: (
        <div className="space-y-3">
          <label className="block">
            <div className="mb-1 text-xs font-medium text-muted-foreground">
              Runtime URL
            </div>
            <Input
              type="url"
              value={surfaceRuntimeUrlInput}
              onChange={(event) =>
                setSurfaceRuntimeUrlInput(event.target.value)
              }
            />
            <div className="mt-2 text-xs leading-5 text-muted-foreground">
              Accepts either a dev server root such as{" "}
              <span className="font-mono text-foreground/80">
                {LOCAL_VITE_RUNTIME_URL}
              </span>{" "}
              or a concrete entry page.
            </div>
          </label>

          <button
            type="button"
            onClick={() => {
              void handleCreateSurfaceDevSession(
                OFFICIAL_SAMPLE_SURFACE_KEY,
                surfaceRuntimeUrlInput,
              );
            }}
            disabled={!currentSessionId || isCreatingSurfaceSession}
            className="inline-flex h-9 items-center rounded-lg border border-border/70 bg-foreground px-3 text-sm font-medium text-background transition-colors hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isCreatingSurfaceSession ? "Attaching..." : "Attach Dev Surface"}
          </button>

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
                Attached to this chat session. Use the chat-header surface icon
                to open the dock.
              </div>
            </div>
          ) : null}
        </div>
      ),
    };
  }, [
    activeSurfaceSession,
    currentSessionId,
    handleCreateSurfaceDevSession,
    isCreatingSurfaceSession,
    surfaceCreationError,
    surfaceRuntimeUrlInput,
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
  const isNewSessionDraftActive =
    currentSessionId === null && currentProjectId === null;
  const chatWorkspacePane = (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges]"
        onScroll={handleScroll}
      >
        <div className="mx-auto max-w-3xl px-4 pb-2 pt-4">
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
              onApproveSkillChange={handleApproveSkillChange}
              onRejectSkillChange={handleRejectSkillChange}
            />
          )}
          <div className="h-1" />
        </div>
      </div>

      <ChatComposer
        error={error}
        compactStatusMessage={compactStatusMessage}
        replyTarget={replyTarget}
        pendingFiles={pendingFiles}
        isStreaming={isStreaming}
        isConversationEmpty={isConversationEmpty}
        hasUploadingFiles={hasUploadingFiles}
        taskPlan={composerTaskPlan}
        contextUsage={contextUsage}
        isContextUsageLoading={isContextUsageLoading}
        supportsImageInput={supportsImageInput}
        thinkingModes={thinkingModes}
        selectedThinkingMode={selectedThinkingMode}
        webSearchProviders={webSearchProviders}
        selectedWebSearchProvider={selectedWebSearchProvider}
        availableMandatorySkills={runtimeSkills}
        selectedMandatorySkills={selectedMandatorySkills}
        imageInputRef={imageInputRef}
        documentInputRef={documentInputRef}
        resetDraftSignal={composerResetSignal}
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
        onDeleteProject={handleDeleteProject}
        onSelectSession={handleSelectSession}
        onRenameSession={handleRenameSession}
        onTogglePinSession={handleTogglePinSession}
        onDeleteSession={handleDeleteSession}
        navigationItems={sidebarNavigationItems}
        footer={sidebarFooter}
      />

      <SidebarInset className="relative flex flex-1 overflow-hidden bg-background text-foreground">
        <div className="pointer-events-none absolute left-3 top-3 z-20">
          <SidebarTrigger className="pointer-events-auto h-8 w-8 rounded-lg bg-transparent text-muted-foreground shadow-none hover:bg-accent/70 hover:text-foreground" />
        </div>
        {headerSurfaceButtons.length > 0 ? (
          <div className="pointer-events-none absolute right-3 top-3 z-20 flex items-center gap-2">
            {headerSurfaceButtons}
          </div>
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
    </SidebarProvider>
  );
}

export default ChatContainer;
