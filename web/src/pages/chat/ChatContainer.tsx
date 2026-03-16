import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import {
  cancelReactTask,
  createSession,
  deleteSession,
  getFullSessionHistory,
  getReactContextUsage,
  listSessions,
  startReactTask,
  type ReactContextUsageSummary,
  type SessionListItem,
  type SessionResponse,
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
  ChatMessage,
  PlanStepData,
  ReactChatInterfaceProps,
  ReactStreamEvent,
  RecursionRecord,
  TokenUsage,
} from "./types";
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
} from "./utils/chatSelectors";

/**
 * Convert a session creation payload into the sidebar row shape.
 */
function toSessionListItem(session: SessionResponse): SessionListItem {
  return {
    session_id: session.session_id,
    agent_id: session.agent_id,
    status: session.status,
    subject: session.subject?.content || null,
    created_at: session.created_at,
    updated_at: session.updated_at,
    message_count: 0,
  };
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
 * Coordinates the page-scoped chat state and delegates visual rendering to smaller components.
 */
function ChatContainer({
  agentId,
  agentName,
  primaryLlmId,
  sessionIdleTimeoutMinutes,
}: ReactChatInterfaceProps) {
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

  const {
    pendingFiles,
    readyPendingFiles,
    hasUploadingFiles,
    supportsImageInput,
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
              syncLiveRefsFromMessages(nextMessages);
              commitMessages(nextMessages);
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
        event.type === "task_complete" ||
        event.type === "error"
      ) {
        let finalizedRecursion: RecursionRecord | null = null;
        const currentRecursion =
          currentRecursionFromRefs ?? runningRecursionFromMessage ?? null;

        if (currentRecursion) {
          finalizedRecursion = {
            ...currentRecursion,
            trace_id: event.trace_id || currentRecursion.trace_id,
            events: [...currentRecursion.events, event],
            status: event.type === "error" ? "error" : "completed",
            endTime: event.timestamp,
            tokens: event.tokens ?? currentRecursion.tokens,
          };
        }

        if (event.type === "clarify") {
          setIsStreaming(false);
          setActiveContextTaskId(null);
          setActiveContextIteration(null);
          liveTaskIdRef.current = event.task_id;
          liveRecursionRef.current = finalizedRecursion;
        } else if (event.type === "task_complete" || event.type === "error") {
          setIsStreaming(false);
          setActiveContextTaskId(null);
          setActiveContextIteration(null);
          liveTaskIdRef.current = null;
          liveRecursionRef.current = null;
          liveAssistantMessageIdRef.current = null;
        } else {
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
                    event.type === "task_complete"
                  ? {
                      ...recursion,
                      status: "completed" as const,
                      endTime: event.timestamp,
                    }
                  : recursion
            );

            if (event.type === "answer") {
              const answerData = event.data as { answer?: string } | undefined;
              return {
                ...message,
                recursions: updatedRecursions,
                content: answerData?.answer ?? message.content,
              };
            }

            if (event.type === "clarify") {
              const clarifyData = event.data as { question?: string } | undefined;
              return {
                ...message,
                recursions: updatedRecursions,
                content: clarifyData?.question ?? message.content,
                status: "waiting_input" as const,
                timestamp: event.timestamp,
              };
            }

            if (event.type === "error") {
              return {
                ...message,
                recursions: updatedRecursions,
                status: "error" as const,
                content:
                  (event.data as { error?: string } | undefined)?.error ??
                  message.content,
                timestamp: event.timestamp,
              };
            }

            void refreshSessionList().catch((refreshError) => {
              console.error(
                "Failed to refresh session list after task completion:",
                refreshError,
              );
            });
            return {
              ...message,
              recursions: updatedRecursions,
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
      } else if (event.type === "thought") {
        nextRecursion = {
          ...nextRecursion,
          thought: event.delta ?? "",
          tokens: event.tokens ?? currentRecursion.tokens,
        };
      } else if (event.type === "abstract") {
        nextRecursion = {
          ...nextRecursion,
          abstract: event.delta ?? "",
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
      commitMessages,
      currentSessionId,
      refreshSessionList,
      syncLiveRefsFromMessages,
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
          setReplyTaskId(null);
          setActiveContextTaskId(null);
          setActiveContextIteration(null);

          if (autoSelectedSessionId) {
            try {
              const history = await getFullSessionHistory(autoSelectedSessionId);
              const nextMessages = buildMessagesFromHistory(history.tasks);
              syncLiveRefsFromMessages(nextMessages);
              setIsStreaming(
                nextMessages.some(
                  (message) =>
                    message.role === "assistant" && message.status === "running",
                ),
              );
              commitMessages(nextMessages);
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
    syncLiveRefsFromMessages,
    commitMessages,
  ]);

  useEffect(() => stopSessionStream, [stopSessionStream]);

  useEffect(() => {
    currentSessionIdRef.current = currentSessionId;
  }, [currentSessionId]);

  const canSendMessage =
    !isStreaming &&
    !hasUploadingFiles &&
    (inputMessage.trim().length > 0 || readyPendingFiles.length > 0);
  const readyPendingFileIds = readyPendingFiles.map((file) => file.fileId);
  const readyPendingFileIdsKey = readyPendingFileIds.join(",");

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
    prepareForProgrammaticScroll();
    await clearPendingFiles();
    stopSessionStream();

    try {
      const history = await getFullSessionHistory(sessionId);
      const nextMessages = buildMessagesFromHistory(history.tasks);
      syncLiveRefsFromMessages(nextMessages);
      setIsStreaming(
        nextMessages.some(
          (message) =>
            message.role === "assistant" && message.status === "running",
        ),
      );
      commitMessages(nextMessages);
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

        if (remainingSessions.length > 0) {
          await handleSelectSession(remainingSessions[0].session_id);
        } else {
          await clearPendingFiles();
          setCurrentSessionId(null);
          currentSessionIdRef.current = null;
          setActiveContextTaskId(null);
          setActiveContextIteration(null);
          setContextUsage(null);
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
   * Requests cancellation for the active task from the composer.
   */
  const handleStop = () => {
    if (liveTaskIdRef.current) {
      void cancelReactTask(liveTaskIdRef.current).catch((cancelError) => {
        console.error("Failed to cancel task:", cancelError);
        setError("Failed to stop execution");
      });
    }
  };

  /**
   * Sends the current composer state and incrementally applies streamed backend updates.
   */
  const sendMessage = async () => {
    const pendingMessage = inputMessage;
    const currentReplyTaskId = replyTaskId;
    let assistantMessageId: string | null = null;
    const filesToSend = readyPendingFiles;
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
        setSessions((previous) => [
          sessionItem,
          ...previous.filter(
            (existingSession) =>
              existingSession.session_id !== sessionItem.session_id,
          ),
        ]);
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
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: pendingMessage,
        attachments: sentAttachments,
        timestamp: messageTimestamp,
      };
      assistantMessageId = `assistant-${Date.now()}`;
      const assistantMessage: ChatMessage = {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        timestamp: messageTimestamp,
        recursions: [],
        status: "running",
      };

      if (shouldResetConversation) {
        commitMessages([userMessage, assistantMessage]);
      } else {
        updateMessages((previous) => [...previous, userMessage, assistantMessage]);
      }
      setInputMessage("");
      discardReadyPendingFiles();
      setError(null);
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
                status: "skill_resolving",
              }
            : message,
        ),
      );
      liveTaskIdRef.current = launchResult.task_id;
    } catch (streamError) {
      setActiveContextTaskId(null);
      setActiveContextIteration(null);
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
              onToggleRecursion={toggleRecursion}
              onReplyTask={setReplyTaskId}
            />
            <div className="h-1" />
          </div>
        </div>

        <ChatComposer
          inputMessage={inputMessage}
          error={error}
          replyTaskId={replyTaskId}
          pendingFiles={pendingFiles}
          canSendMessage={canSendMessage}
          isStreaming={isStreaming}
          isConversationEmpty={isConversationEmpty}
          hasUploadingFiles={hasUploadingFiles}
          taskPlan={composerTaskPlan}
          contextUsage={contextUsage}
          isContextUsageLoading={isContextUsageLoading}
          supportsImageInput={supportsImageInput}
          imageInputRef={imageInputRef}
          documentInputRef={documentInputRef}
          onInputChange={setInputMessage}
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
