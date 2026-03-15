import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import {
  createSession,
  deleteSession,
  getFullSessionHistory,
  getReactContextUsage,
  listSessions,
  type ReactContextUsageSummary,
  type SessionListItem,
  type SessionResponse,
  API_BASE_URL,
} from "@/utils/api";
import {
  AUTH_EXPIRED_EVENT,
  getAuthToken,
  getStoredUser,
  isTokenValid,
} from "@/contexts/auth-core";

import { ChatComposer } from "./components/ChatComposer";
import { ConversationView } from "./components/ConversationView";
import { SessionSidebar } from "./components/SessionSidebar";
import { useChatAutoScroll } from "./hooks/useChatAutoScroll";
import { useChatUploads } from "./hooks/useChatUploads";
import type {
  ChatMessage,
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
import { hasSessionExceededIdleTimeout } from "./utils/sessionActivity";
import { ZERO_RATE_STREAK_TO_RENDER } from "./utils/chatSelectors";

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
 * Coordinates the page-scoped chat state and delegates visual rendering to smaller components.
 */
function ChatContainer({
  agentId,
  agentName,
  primaryLlmId,
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
  const [contextUsage, setContextUsage] =
    useState<ReactContextUsageSummary | null>(null);
  const [isContextUsageLoading, setIsContextUsageLoading] =
    useState<boolean>(false);
  const abortControllerRef = useRef<AbortController | null>(null);
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

  /**
   * Reloads the sidebar session list so metadata stays in sync after task completion.
   */
  const refreshSessionList = useCallback(async (): Promise<SessionListItem[]> => {
    const response = await listSessions(agentId);
    setSessions(response.sessions);
    return response.sessions;
  }, [agentId]);

  useEffect(() => {
    const initSessions = async () => {
      if (isInitialized || isLoadingSession) {
        return;
      }

      setIsLoadingSession(true);
      try {
        const existingSessions = await refreshSessionList();

        if (existingSessions.length > 0) {
          const latestSession = existingSessions[0];
          if (hasSessionExceededIdleTimeout(latestSession)) {
            const freshSession = await createSession(agentId);
            const freshSessionItem = toSessionListItem(freshSession);

            setCurrentSessionId(freshSession.session_id);
            setReplyTaskId(null);
            setActiveContextTaskId(null);
            setMessages([]);
            setSessions([
              freshSessionItem,
              ...existingSessions.filter(
                (session) => session.session_id !== freshSession.session_id,
              ),
            ]);
          } else {
            const firstSessionId = latestSession.session_id;
            setCurrentSessionId(firstSessionId);
            setActiveContextTaskId(null);

            try {
              const history = await getFullSessionHistory(firstSessionId);
              setMessages(buildMessagesFromHistory(history.tasks));
            } catch (historyError) {
              console.error(
                "Failed to load initial session history:",
                historyError,
              );
            }
          }
        } else {
          setCurrentSessionId(null);
          setActiveContextTaskId(null);
          setMessages([]);
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
  }, [agentId, isInitialized, isLoadingSession, refreshSessionList]);

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
    if (
      !replyTaskId &&
      inputMessage.trim().length === 0 &&
      readyPendingFileIdsKey === "" &&
      contextUsage !== null
    ) {
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
    contextUsage,
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
    const intervalId = window.setInterval(() => {
      runEstimate();
    }, 1000);

    return () => window.clearInterval(intervalId);
  }, [activeContextTaskId, agentId, currentSessionId, isStreaming]);

  /**
   * Creates a new explicit conversation and resets transient page-local state.
   */
  const handleNewSession = async () => {
    setIsLoadingSession(true);
    try {
      await clearPendingFiles();
      prepareForProgrammaticScroll();

      const session = await createSession(agentId);
      setCurrentSessionId(session.session_id);
      setMessages([]);
      setReplyTaskId(null);
      setActiveContextTaskId(null);
      const sessionItem = toSessionListItem(session);
      setSessions((previous) => [
        sessionItem,
        ...previous.filter(
          (existingSession) =>
            existingSession.session_id !== sessionItem.session_id,
        ),
      ]);
    } catch (createError) {
      console.error("Failed to create new session:", createError);
      setError("Failed to create new session");
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
    setIsLoadingSession(true);
    setReplyTaskId(null);
    setActiveContextTaskId(null);
    prepareForProgrammaticScroll();
    await clearPendingFiles();

    try {
      const history = await getFullSessionHistory(sessionId);
      setMessages(buildMessagesFromHistory(history.tasks));
    } catch (historyError) {
      console.error("Failed to load session history:", historyError);
      setMessages([]);
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

        if (remainingSessions.length > 0) {
          await handleSelectSession(remainingSessions[0].session_id);
        } else {
          await clearPendingFiles();
          setCurrentSessionId(null);
          setActiveContextTaskId(null);
          setMessages([]);
          setIsInitialized(false);
        }
      }
    } catch (deleteError) {
      console.error("Failed to delete session:", deleteError);
      setError("Failed to delete session");
    }
  };

  /**
   * Stops the current streaming request from the composer.
   */
  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
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
    abortControllerRef.current = new AbortController();

    try {
      let activeSessionId = currentSessionId;
      let requestTaskId = currentReplyTaskId;
      let shouldResetConversation = false;
      const activeSession = activeSessionId
        ? sessions.find((session) => session.session_id === activeSessionId) ?? null
        : null;

      if (activeSessionId && hasSessionExceededIdleTimeout(activeSession)) {
        shouldResetConversation = true;
        requestTaskId = null;
      }

      if (!activeSessionId) {
        const session = await createSession(agentId);
        activeSessionId = session.session_id;
        shouldResetConversation = true;
        const sessionItem = toSessionListItem(session);
        setCurrentSessionId(activeSessionId);
        setSessions((previous) => [
          sessionItem,
          ...previous.filter(
            (existingSession) =>
              existingSession.session_id !== sessionItem.session_id,
          ),
        ]);
      } else if (shouldResetConversation) {
        const session = await createSession(agentId);
        activeSessionId = session.session_id;
        const sessionItem = toSessionListItem(session);
        setCurrentSessionId(activeSessionId);
        setSessions((previous) => [
          sessionItem,
          ...previous.filter(
            (existingSession) =>
              existingSession.session_id !== sessionItem.session_id,
          ),
        ]);
      }

      if (currentReplyTaskId) {
        setReplyTaskId(null);
      }

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
        setMessages([userMessage, assistantMessage]);
      } else {
        setMessages((previous) => [...previous, userMessage, assistantMessage]);
      }
      setInputMessage("");
      discardReadyPendingFiles();
      setError(null);
      setIsStreaming(true);

      const apiUrl = `${API_BASE_URL}/react/chat/stream`;
      const token = getAuthToken();
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };

      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const response = await fetch(apiUrl, {
        method: "POST",
        headers,
        body: JSON.stringify({
          agent_id: agentId,
          message: userMessage.content,
          user: getStoredUser()?.username ?? "web-user",
          task_id: requestTaskId,
          session_id: activeSessionId,
          file_ids: filesToSend.map((file) => file.fileId),
        }),
        signal: abortControllerRef.current.signal,
      });

      if (response.status === 401) {
        window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
        throw new Error("Authentication expired. Please log in again.");
      }

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error("Response body is null");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentTaskId: string | null = null;
      let currentRecursion: RecursionRecord | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim() || !line.startsWith("data: ")) {
            continue;
          }

          const data = line.slice(6).trim();
          if (!data) {
            continue;
          }

          try {
            const parsedEvent = parseJson(data);
            if (!isReactStreamEvent(parsedEvent)) {
              continue;
            }

            const event: ReactStreamEvent = parsedEvent;

            if (event.type === "skill_resolution_start") {
              currentTaskId = event.task_id;
              setActiveContextTaskId(event.task_id);
              setMessages((previous) =>
                previous.map((message) =>
                  message.id === assistantMessageId
                    ? {
                        ...message,
                        task_id: currentTaskId ?? undefined,
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
            } else if (event.type === "skill_resolution_result") {
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

              setMessages((previous) =>
                previous.map((message) =>
                  message.id === assistantMessageId
                    ? {
                        ...message,
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
            } else if (event.type === "recursion_start") {
              if (currentRecursion && currentRecursion.status === "running") {
                const previousRecursionSnapshot: RecursionRecord = {
                  ...currentRecursion,
                  status: "completed",
                  endTime: event.timestamp,
                };
                currentRecursion = previousRecursionSnapshot;

                setMessages((previous) =>
                  previous.map((message) => {
                    if (message.id !== assistantMessageId) {
                      return message;
                    }

                    const updatedRecursions = (message.recursions || []).map(
                      (recursion) =>
                        recursion.uid === previousRecursionSnapshot.uid
                          ? previousRecursionSnapshot
                          : recursion,
                    );

                    return {
                      ...message,
                      recursions: updatedRecursions,
                    };
                  }),
                );
              }

              currentTaskId = event.task_id;
              setActiveContextTaskId(event.task_id);
              const newRecursionSnapshot: RecursionRecord = {
                uid: `live-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
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
              currentRecursion = newRecursionSnapshot;

              setMessages((previous) =>
                previous.map((message) =>
                  message.id === assistantMessageId
                    ? {
                        ...message,
                        status: "running",
                        skillSelection:
                          message.skillSelection?.status === "loading"
                            ? {
                                ...message.skillSelection,
                                status: "done",
                                count: 0,
                                selectedSkills: [],
                              }
                            : message.skillSelection,
                        task_id: currentTaskId ?? undefined,
                        recursions: [
                          ...(message.recursions || []),
                          newRecursionSnapshot,
                        ],
                      }
                    : message,
                ),
              );
            } else if (currentRecursion && currentTaskId) {
              const existingRecursion: RecursionRecord = currentRecursion;
              const updatedEvents: ReactStreamEvent[] = [
                ...existingRecursion.events,
                event,
              ];

              if (event.type === "token_rate") {
                const tokenRate = parseTokenRateData(event.data);
                if (tokenRate) {
                  const previousRate = existingRecursion.liveTokensPerSecond;
                  const previousHasSeenPositiveRate =
                    existingRecursion.hasSeenPositiveRate === true;
                  const previousZeroRateStreak =
                    existingRecursion.zeroRateStreak ?? 0;

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

                  currentRecursion = {
                    ...existingRecursion,
                    trace_id: event.trace_id || existingRecursion.trace_id,
                    events: updatedEvents,
                    liveTokensPerSecond: nextRate,
                    estimatedCompletionTokens:
                      tokenRate.estimatedCompletionTokens,
                    hasSeenPositiveRate: nextHasSeenPositiveRate,
                    zeroRateStreak: nextZeroRateStreak,
                  };
                } else {
                  currentRecursion = {
                    ...existingRecursion,
                    trace_id: event.trace_id || existingRecursion.trace_id,
                    events: updatedEvents,
                  };
                }
              } else if (event.type === "observe") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  observe: event.delta ?? "",
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === "reasoning") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  thinking: `${existingRecursion.thinking ?? ""}${event.delta ?? ""}`,
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === "thought") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  thought: event.delta ?? "",
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === "abstract") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  abstract: event.delta ?? "",
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === "summary") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  summary: event.delta ?? "",
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === "action") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  action: event.delta ?? "",
                  status: "completed",
                  endTime: event.timestamp,
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === "tool_call") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                };
              } else if (event.type === "error") {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  status: "error",
                  endTime: event.timestamp,
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === "answer") {
                const answerData = event.data as { answer?: string } | undefined;

                if (answerData?.answer) {
                  setMessages((previous) =>
                    previous.map((message) =>
                      message.id === assistantMessageId
                        ? {
                            ...message,
                            content: answerData.answer ?? "",
                          }
                        : message,
                    ),
                  );
                }

                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  status: "completed",
                  endTime: event.timestamp,
                };
              } else if (event.type === "clarify") {
                const clarifyData = event.data as
                  | { question?: string }
                  | undefined;

                if (clarifyData?.question) {
                  setMessages((previous) =>
                    previous.map((message) =>
                      message.id === assistantMessageId
                        ? {
                            ...message,
                            content: clarifyData.question ?? "",
                            status: "waiting_input" as const,
                          }
                        : message,
                    ),
                  );
                }

                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                  status: "completed",
                  endTime: event.timestamp,
                };
              } else if (event.type === "task_complete") {
                setActiveContextTaskId(null);
                setMessages((previous) =>
                  previous.map((message) => {
                    if (message.id !== assistantMessageId) {
                      return message;
                    }

                    const updatedRecursions = (message.recursions || []).map(
                      (recursion) =>
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
                      status: "completed",
                      skillSelection:
                        message.skillSelection?.status === "loading"
                          ? {
                              ...message.skillSelection,
                              status: "done",
                              count: 0,
                              selectedSkills: [],
                            }
                          : message.skillSelection,
                      recursions: updatedRecursions,
                      timestamp: event.timestamp,
                      totalTokens: event.total_tokens,
                    };
                  }),
                );
                currentRecursion = null;

                void refreshSessionList().catch((refreshError) => {
                  console.error(
                    "Failed to refresh session list after task completion:",
                    refreshError,
                  );
                });
              } else {
                currentRecursion = {
                  ...existingRecursion,
                  trace_id: event.trace_id || existingRecursion.trace_id,
                  events: updatedEvents,
                };
              }

              if (currentRecursion) {
                const frozenRecursion: RecursionRecord = currentRecursion;
                setMessages((previous) =>
                  previous.map((message) => {
                    if (message.id !== assistantMessageId) {
                      return message;
                    }

                    const updatedRecursions = (message.recursions || []).map(
                      (recursion) =>
                        recursion.uid === frozenRecursion.uid
                          ? { ...frozenRecursion }
                          : recursion,
                    );

                    return {
                      ...message,
                      recursions: updatedRecursions,
                    };
                  }),
                );
              }
            }
          } catch (parseError) {
            console.error("Failed to parse SSE event:", parseError);
          }
        }
      }

      setIsStreaming(false);
      setActiveContextTaskId(null);
    } catch (streamError) {
      if (streamError instanceof Error && streamError.name === "AbortError") {
        setActiveContextTaskId(null);
        const cancelTime = new Date().toISOString();
        setMessages((previous) =>
          previous.map((message) => {
            if (!assistantMessageId || message.id !== assistantMessageId) {
              return message;
            }

            const updatedRecursions = (message.recursions || []).map(
              (recursion, index, array) =>
                index === array.length - 1 && recursion.status === "running"
                  ? {
                      ...recursion,
                      status: "error" as const,
                      endTime: cancelTime,
                    }
                  : recursion,
            );

            return {
              ...message,
              status: "error",
              content: message.content || "Execution stopped by user",
              skillSelection:
                message.skillSelection?.status === "loading"
                  ? {
                      ...message.skillSelection,
                      status: "done",
                      count: 0,
                      selectedSkills: [],
                    }
                  : message.skillSelection,
              recursions: updatedRecursions,
              timestamp: cancelTime,
            };
          }),
        );
      } else {
        setActiveContextTaskId(null);
        const normalizedError =
          streamError instanceof Error
            ? streamError
            : new Error(String(streamError));
        const errorTime = new Date().toISOString();
        setError(normalizedError.message);
        setMessages((previous) =>
          previous.map((message) =>
            message.id === assistantMessageId
              ? {
                  ...message,
                  status: "error",
                  content: `Error: ${normalizedError.message}`,
                  skillSelection:
                    message.skillSelection?.status === "loading"
                      ? {
                          ...message.skillSelection,
                          status: "done",
                          count: 0,
                          selectedSkills: [],
                        }
                      : message.skillSelection,
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
          className="flex-1 overflow-y-auto"
          onScroll={handleScroll}
        >
          <div className="mx-auto max-w-3xl px-4 pb-6 pt-4">
            <ConversationView
              messages={messages}
              agentName={agentName}
              expandedRecursions={expandedRecursions}
              onToggleRecursion={toggleRecursion}
              onReplyTask={setReplyTaskId}
            />
            <div className="h-4" />
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
