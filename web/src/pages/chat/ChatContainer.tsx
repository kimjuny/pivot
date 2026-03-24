import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import {
  cancelReactTask,
  createSession,
  deleteSession,
  getAgentWebSearchBindings,
  getFullSessionHistory,
  getReactContextUsage,
  getReactSessionRuntimeDebug,
  listSessions,
  startReactTask,
  submitReactUserAction,
  updateSession,
  type ReactContextUsageSummary,
  type ReactSessionRuntimeDebug,
  type SessionListItem,
  type SessionResponse,
  type WebSearchBinding,
  API_BASE_URL,
} from "@/utils/api";
import {
  AUTH_EXPIRED_EVENT,
  getAuthToken,
  isTokenValid,
} from "@/contexts/auth-core";

import { ChatComposer } from "./components/ChatComposer";
import { ConversationView } from "./components/ConversationView";
import { SessionSidebar } from "./components/SessionSidebar";
import { useChatAutoScroll } from "./hooks/useChatAutoScroll";
import { useChatUploads } from "./hooks/useChatUploads";
import type {
  ChatWebSearchProviderOption,
  ChatPageProps,
  ChatMessage,
  ChatReplyTarget,
  PlanStepData,
  ReactStreamEvent,
  RecursionRecord,
  SkillChangeApprovalRequest,
  TokenUsage,
} from "./types";
import type { ChatThinkingMode } from "@/utils/llmThinking";
import {
  buildMessagesFromHistory,
  isReactStreamEvent,
  parseJson,
  parseTokenRateData,
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
 * Convert a session creation payload into the sidebar row shape.
 */
function toSessionListItem(session: SessionResponse): SessionListItem {
  return {
    session_id: session.session_id,
    agent_id: session.agent_id,
    status: session.status,
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
  agentName,
  agentToolIds,
  primaryLlmId,
  sessionIdleTimeoutMinutes,
  onRuntimeDebugChange,
}: ChatPageProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRecursions, setExpandedRecursions] = useState<
    Record<string, boolean>
  >({});
  const [replyTaskId, setReplyTaskId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState<boolean>(false);
  const [isInitialized, setIsInitialized] = useState<boolean>(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
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
  const messagesRef = useRef<ChatMessage[]>([]);
  const currentSessionIdRef = useRef<string | null>(null);
  const sessionStreamAbortControllerRef = useRef<AbortController | null>(null);
  const sessionStreamReconnectTimerRef = useRef<number | null>(null);
  const sessionEventCursorRef = useRef(0);
  const historyReloadInFlightRef = useRef(false);
  const liveAssistantMessageIdRef = useRef<string | null>(null);
  const liveTaskIdRef = useRef<string | null>(null);
  const liveRecursionRef = useRef<RecursionRecord | null>(null);
  const contextUsageRequestIdRef = useRef(0);
  const runtimeDebugRequestIdRef = useRef(0);
  const compactStatusStartedAtRef = useRef<number | null>(null);
  const compactStatusClearTimerRef = useRef<number | null>(null);
  const stoppedTaskIdsRef = useRef<Set<string>>(new Set());

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

  /**
   * Reloads the sidebar session list so metadata stays in sync after task completion.
   */
  const refreshSessionList = useCallback(async (): Promise<SessionListItem[]> => {
    const response = await listSessions(agentId);
    setSessions(response.sessions);
    return response.sessions;
  }, [agentId]);

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
          (message.status === "running" || message.status === "skill_resolving"),
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
            skillSelection:
              message.skillSelection?.status === "loading"
                ? {
                    ...message.skillSelection,
                    status: "done",
                    count: 0,
                    selectedSkills: [],
                  }
                : message.skillSelection,
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
          previous.find(
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

      if (event.type === "skill_resolution_start") {
        setIsStreaming(true);
        liveTaskIdRef.current = event.task_id;
        liveAssistantMessageIdRef.current = targetMessageId;
        liveRecursionRef.current = null;
        setActiveContextTaskId(event.task_id);
        setActiveContextIteration(null);
        updateMessages((messagesSnapshot) =>
          messagesSnapshot.map((message) =>
            message.id === targetMessageId
              ? {
                  ...message,
                  task_id: event.task_id,
                  status: "skill_resolving" as const,
                  skillSelection: {
                    status: "loading",
                    count: 0,
                    selectedSkills: [],
                  },
                }
              : message,
          ),
        );
        return;
      }

      if (event.type === "skill_resolution_result") {
        setIsStreaming(true);
        const skillData = event.data as
          | {
              count?: number;
              selected_skills?: string[];
              duration_ms?: number;
              tokens?: TokenUsage;
            }
          | undefined;
        const selectedSkills = skillData?.selected_skills ?? [];
        const selectedCount =
          typeof skillData?.count === "number"
            ? skillData.count
            : selectedSkills.length;

        liveTaskIdRef.current = event.task_id;
        liveAssistantMessageIdRef.current = targetMessageId;
        updateMessages((messagesSnapshot) =>
          messagesSnapshot.map((message) =>
            message.id === targetMessageId
              ? {
                  ...message,
                  task_id: event.task_id,
                  status: "running" as const,
                  skillSelection: {
                    status: "done",
                    count: selectedCount,
                    selectedSkills,
                    durationMs: skillData?.duration_ms,
                    tokens: skillData?.tokens,
                  },
                }
              : message,
          ),
        );
        return;
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
              skillSelection:
                message.skillSelection?.status === "loading"
                  ? {
                      ...message.skillSelection,
                      status: "done",
                      count: 0,
                      selectedSkills: [],
                    }
                  : message.skillSelection,
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
        if (
          event.type === "clarify" ||
          event.type === "task_complete" ||
          event.type === "task_cancelled" ||
          event.type === "error"
        ) {
          void refreshSessionList().catch((refreshError) => {
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
          event.type === "error"
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
              const answerData = event.data as { answer?: string } | undefined;
              return {
                ...message,
                recursions: updatedRecursions,
                pendingUserAction: undefined,
                content: answerData?.answer ?? message.content,
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
                timestamp: event.timestamp,
              };
            }

            if (event.type === "error") {
              return {
                ...message,
                recursions: updatedRecursions,
                pendingUserAction: undefined,
                status: "error" as const,
                content:
                  (event.data as { error?: string } | undefined)?.error ??
                  message.content,
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
                skillSelection:
                  message.skillSelection?.status === "loading"
                    ? {
                        ...message.skillSelection,
                        status: "done",
                        count: 0,
                        selectedSkills: [],
                      }
                    : message.skillSelection,
              };
            }

            return {
              ...message,
              recursions: updatedRecursions,
              pendingUserAction: undefined,
              status: "completed" as const,
              timestamp: event.timestamp,
              totalTokens: event.total_tokens ?? message.totalTokens,
            };
          }),
        );
        return;
      }

      const currentRecursion =
        currentRecursionFromRefs ??
        (matchingRecursionFromMessage?.status === "running"
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
        nextRecursion = {
          ...nextRecursion,
          action: event.delta ?? "",
          status: "completed",
          endTime: event.timestamp,
          tokens: event.tokens ?? currentRecursion.tokens,
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
      refreshSessionList,
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

          const response = await fetch(
            `${API_BASE_URL}/react/sessions/${sessionId}/events/stream?after_id=${sessionEventCursorRef.current}`,
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
      if (isInitialized || isLoadingSession) {
        return;
      }

      setIsLoadingSession(true);
      try {
        const existingSessions = await refreshSessionList();

        if (existingSessions.length > 0) {
          const autoSelectedSessionId = getAutoSelectedSessionId(
            existingSessions,
            Date.now(),
            sessionIdleTimeoutMs,
          );

          setCurrentSessionId(autoSelectedSessionId);
          currentSessionIdRef.current = autoSelectedSessionId;
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
    isLoadingSession,
    refreshSessionList,
    sessionIdleTimeoutMs,
    openSessionStream,
    stopSessionStream,
    applyHistoryMessages,
    commitMessages,
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

  const canSendMessage =
    !isStreaming &&
    !hasUploadingFiles &&
    (inputMessage.trim().length > 0 || readyPendingFiles.length > 0);
  const readyPendingFileIds = readyPendingFiles.map((file) => file.fileId);
  const readyPendingFileIdsKey = readyPendingFileIds.join(",");

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

  useEffect(() => {
    if (isStreaming) {
      return;
    }

    const draftFileIds = readyPendingFileIdsKey
      ? readyPendingFileIdsKey.split(",")
      : [];
    const timer = window.setTimeout(() => {
      const requestId = contextUsageRequestIdRef.current + 1;
      contextUsageRequestIdRef.current = requestId;
      setIsContextUsageLoading(true);

      void getReactContextUsage({
        agent_id: agentId,
        session_id: currentSessionId,
        task_id: replyTaskId,
        draft_message: inputMessage,
        file_ids: draftFileIds,
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
    }, 250);

    return () => window.clearTimeout(timer);
  }, [
    agentId,
    clearCompactStatusImmediately,
    currentSessionId,
    inputMessage,
    isStreaming,
    readyPendingFileIdsKey,
    replyTaskId,
  ]);

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
  ]);

  /**
   * Enters a blank draft state and postpones session persistence until send time.
   */
  const handleNewSession = async () => {
    setIsLoadingSession(true);
    try {
      await clearPendingFiles();
      prepareForProgrammaticScroll();

      setCurrentSessionId(null);
      currentSessionIdRef.current = null;
      commitMessages([]);
      setReplyTaskId(null);
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
   * Loads the selected session history into the current chat surface.
   */
  const handleSelectSession = async (sessionId: string) => {
    if (sessionId === currentSessionId || isLoadingSession) {
      return;
    }

    setCurrentSessionId(sessionId);
    currentSessionIdRef.current = sessionId;
    setIsLoadingSession(true);
    setReplyTaskId(null);
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

        if (remainingSessions.length > 0) {
          await handleSelectSession(remainingSessions[0].session_id);
        } else {
          await clearPendingFiles();
          setCurrentSessionId(null);
          currentSessionIdRef.current = null;
          setActiveContextTaskId(null);
          setActiveContextIteration(null);
          setContextUsage(null);
          clearCompactStatusImmediately();
          syncLiveRefsFromMessages([]);
          commitMessages([]);
          setIsInitialized(false);
          stopSessionStream();
          setIsStreaming(false);
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
  const handleStop = () => {
    const activeTaskId = liveTaskIdRef.current;
    if (activeTaskId) {
      markTaskStopped(activeTaskId, new Date().toISOString());
      setError(null);

      void cancelReactTask(activeTaskId)
        .then(() =>
          refreshSessionList().catch((refreshError) => {
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
    }
  };

  /**
   * Sends the current composer state and incrementally applies streamed backend updates.
   */
  const sendMessage = async (options?: {
    messageOverride?: string;
    replyTaskIdOverride?: string | null;
  }) => {
    const pendingMessage = options?.messageOverride ?? inputMessage;
    const currentReplyTaskId = options?.replyTaskIdOverride ?? replyTaskId;
    let assistantMessageId: string | null = null;
    const filesToSend = options?.messageOverride ? [] : readyPendingFiles;
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

      if (!activeSessionId) {
        const session = await createSession(agentId);
        activeSessionId = session.session_id;
        shouldResetConversation = true;
        const sessionItem = toSessionListItem(session);
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

      setSessions((previous) =>
        previous,
      );
      const messageTimestamp = new Date().toISOString();
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: pendingMessage,
        attachments: sentAttachments,
        timestamp: messageTimestamp,
      };
      assistantMessageId = `assistant-${Date.now()}`;
      const assistantMessageStatus = currentReplyTaskId
        ? ("running" as const)
        : ("skill_resolving" as const);
      const assistantMessage: ChatMessage = {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        timestamp: messageTimestamp,
        recursions: [],
        status: assistantMessageStatus,
      };

      if (shouldResetConversation) {
        commitMessages([userMessage, assistantMessage]);
      } else {
        updateMessages((previous) => [...previous, userMessage, assistantMessage]);
      }
      setInputMessage("");
      if (!options?.messageOverride) {
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

      updateMessages((previous) =>
        previous.map((message) =>
          message.id === assistantMessageId
            ? {
                ...message,
                task_id: launchResult.task_id,
                status: assistantMessageStatus,
              }
            : message,
        ),
      );
      liveTaskIdRef.current = launchResult.task_id;
      void refreshSessionList().catch((refreshError) => {
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
                  content: `Error: ${normalizedError.message}`,
                  timestamp: errorTime,
                }
              : message,
          ),
        );
      }
      setIsStreaming(false);
    }
  };

  /**
   * Sends an explicit approval or rejection reply for a pending inline skill change request.
   */
  const handleSkillChangeDecision = (
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
        void refreshSessionList().catch((refreshError) => {
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
  };

  /**
   * Keeps enter-to-send behavior local to the composer while preserving shift+enter for multiline input.
   */
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSendMessage) {
        void sendMessage();
      }
    }
  };

  /**
   * Normalizes form submission into the same send path used by the enter shortcut.
   */
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSendMessage) {
      return;
    }

    void sendMessage();
  };

  /**
   * Tracks recursion accordion state per message without leaking that detail into message models.
   */
  const toggleRecursion = (messageId: string, recursionUid: string) => {
    const key = `${messageId}-${recursionUid}`;
    setExpandedRecursions((previous) => ({
      ...previous,
      [key]: !previous[key],
    }));
  };

  const isConversationEmpty = messages.length === 0;
  const composerTaskPlan = deriveComposerTaskPlan(messages);
  const replyTarget = findReplyTarget(messages, replyTaskId);

  return (
    <div className="flex h-full overflow-hidden bg-background text-foreground">
      <SessionSidebar
        sessions={sessions}
        currentSessionId={currentSessionId}
        isLoadingSession={isLoadingSession}
        isStreaming={isStreaming}
        isCollapsed={isSidebarCollapsed}
        onToggleCollapsed={() => setIsSidebarCollapsed((previous) => !previous)}
        onNewSession={handleNewSession}
        onSelectSession={handleSelectSession}
        onRenameSession={handleRenameSession}
        onTogglePinSession={handleTogglePinSession}
        onDeleteSession={handleDeleteSession}
      />

      <div className="flex flex-1 flex-col overflow-hidden">
        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto [scrollbar-gutter:stable_both-edges]"
          onScroll={handleScroll}
        >
          <div className="mx-auto max-w-3xl px-4 pb-2 pt-4">
            <ConversationView
              messages={messages}
              agentName={agentName}
              expandedRecursions={expandedRecursions}
              isStreaming={isStreaming}
              onToggleRecursion={toggleRecursion}
              onReplyTask={setReplyTaskId}
              onApproveSkillChange={(taskId, request) =>
                handleSkillChangeDecision("approve", taskId, request)
              }
              onRejectSkillChange={(taskId, request) =>
                handleSkillChangeDecision("reject", taskId, request)
              }
            />
            <div className="h-1" />
          </div>
        </div>

        <ChatComposer
          inputMessage={inputMessage}
          error={error}
          compactStatusMessage={compactStatusMessage}
          replyTarget={replyTarget}
          pendingFiles={pendingFiles}
          canSendMessage={canSendMessage}
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
          imageInputRef={imageInputRef}
          documentInputRef={documentInputRef}
          onInputChange={setInputMessage}
          onThinkingModeChange={setSelectedThinkingMode}
          onWebSearchProviderChange={setSelectedWebSearchProvider}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          onSubmit={handleSubmit}
          onStop={handleStop}
          onCancelReply={() => setReplyTaskId(null)}
          onImageInputChange={handleFileInputChange}
          onDocumentInputChange={handleDocumentInputChange}
          onRemovePendingFile={removePendingFile}
        />
      </div>
    </div>
  );
}

export default ChatContainer;
