import { useState, useRef, useEffect, FormEvent, KeyboardEvent } from 'react';
import { ArrowUp, Plus, Paperclip, Loader2, CheckCircle2, XCircle, AlertCircle, Wrench, Brain, MessageSquare, Square, MessageCircle, Trash2, PlusCircle, PanelLeftClose, PanelLeft } from 'lucide-react';
import { formatTimestamp } from '../utils/timestamp';
import { getAuthToken, isTokenValid, AUTH_EXPIRED_EVENT } from '../contexts/AuthContext';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { createSession, listSessions, deleteSession, getFullSessionHistory, SessionListItem, TaskMessage, RecursionDetail, API_BASE_URL } from '../utils/api';

/**
 * Props for ReactChatInterface component.
 */
interface ReactChatInterfaceProps {
  /** Unique identifier of the agent */
  agentId: number;
}

/**
 * Stream event type from ReAct backend.
 */
type ReactStreamEventType =
  | 'recursion_start'
  | 'observe'
  | 'thought'
  | 'abstract'
  | 'action'
  | 'tool_call'
  | 'plan_update'
  | 'reflect'
  | 'answer'
  | 'clarify'
  | 'task_complete'
  | 'error';

/**
 * Token usage information.
 */
interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/**
 * Stream event from ReAct backend.
 */
interface ReactStreamEvent {
  type: ReactStreamEventType;
  task_id: string;
  trace_id: string | null;
  iteration: number;
  delta?: string | null;
  data?: unknown;
  timestamp: string;
  created_at?: string;
  updated_at?: string;
  tokens?: TokenUsage;
  total_tokens?: TokenUsage;
}

/**
 * Recursion record in chat history.
 */
interface RecursionRecord {
  iteration: number;
  trace_id: string | null;
  observe?: string;
  thought?: string;
  abstract?: string;
  action?: string;
  events: ReactStreamEvent[];
  status: 'running' | 'completed' | 'error';
  errorLog?: string;
  startTime: string;
  endTime?: string;
  tokens?: TokenUsage;
}

/**
 * Message in chat history.
 */
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  task_id?: string;
  recursions?: RecursionRecord[];
  status?: 'running' | 'completed' | 'error' | 'waiting_input';
  totalTokens?: TokenUsage;
}

/**
 * Component to fetch and display recursion state in a tooltip.
 */
function RecursionStateViewer({ taskId, iteration }: { taskId: string; iteration: number }) {
  const [state, setState] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Function to fetch state
  const fetchState = async () => {
    if (state) return;
    setLoading(true);
    try {
      const apiUrl = `${API_BASE_URL}/react/tasks/${taskId}/states/${iteration}`;

      const token = getAuthToken();
      const headers: Record<string, string> = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(apiUrl, { headers });
      if (!response.ok) throw new Error('Failed to fetch state');

      const data = await response.json() as { current_state: string };
      // current_state is a JSON string in the response
      const parsedState = JSON.parse(data.current_state) as unknown;
      setState(JSON.stringify(parsedState, null, 2));
    } catch (err) {
      setError('Failed to load state');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip onOpenChange={(open) => {
        if (open) void fetchState();
      }}>
        <TooltipTrigger asChild>
          <button className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-full hover:bg-muted focus:outline-none focus:ring-1 focus:ring-ring" title="View state">
            <AlertCircle className="w-3.5 h-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-[500px] max-h-[400px] overflow-auto p-4 font-mono text-xs z-50 shadow-lg border border-border">
          {loading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="w-3 h-3 animate-spin" />
              Loading state...
            </div>
          ) : error ? (
            <span className="text-destructive">{error}</span>
          ) : (
            <pre className="whitespace-pre-wrap break-all">
              {state}
            </pre>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * ReAct Chat interface component for agent interaction.
 * Displays streaming conversation with ReAct agent and shows execution details.
 */
function ReactChatInterface({ agentId }: ReactChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRecursions, setExpandedRecursions] = useState<Record<string, boolean>>({});
  const [replyTaskId, setReplyTaskId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Session state
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isLoadingSession, setIsLoadingSession] = useState<boolean>(false);
  const [isInitialized, setIsInitialized] = useState<boolean>(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);

  /**
   * Initialize sessions on mount.
   * Loads existing sessions and creates a new one only if none exist.
   * This prevents duplicate session creation.
   */
  useEffect(() => {
    const initSessions = async () => {
      if (isInitialized || isLoadingSession) return;

      setIsLoadingSession(true);
      try {
        // First, load existing sessions
        const response = await listSessions(agentId);
        setSessions(response.sessions);

        // If there are existing sessions, select the most recent one and load its history
        // Otherwise, create a new session
        if (response.sessions.length > 0) {
          const firstSessionId = response.sessions[0].session_id;
          setCurrentSessionId(firstSessionId);

          // Load history for the first session
          try {
            const history = await getFullSessionHistory(firstSessionId);
            const loadedMessages: ChatMessage[] = [];

            for (const task of history.tasks) {
              // Add user message
              loadedMessages.push({
                id: `user-${task.task_id}`,
                role: 'user',
                content: task.user_message,
                timestamp: task.created_at,
              });

              // Convert recursions to RecursionRecord format
              const recursions: RecursionRecord[] = task.recursions.map((r: RecursionDetail) => {
                // Parse events from recursion data for historical sessions
                let events: ReactStreamEvent[] = [];

                // For CALL_TOOL: parse action_output for tool_calls and tool_call_results for tool_results
                if (r.action_type === 'CALL_TOOL') {
                  let toolCalls: unknown[] = [];
                  let toolResults: unknown[] = [];

                  // Parse tool_calls from action_output
                  if (r.action_output) {
                    try {
                      const actionData = JSON.parse(r.action_output);
                      toolCalls = actionData.tool_calls || [];
                    } catch {
                      // If parsing fails, continue without tool_calls
                    }
                  }

                  // Parse tool_results from tool_call_results
                  if (r.tool_call_results) {
                    try {
                      toolResults = JSON.parse(r.tool_call_results);
                    } catch {
                      // If parsing fails, continue without tool_results
                    }
                  }

                  // Add tool_call event if we have any data
                  if (toolCalls.length > 0 || toolResults.length > 0) {
                    events.push({
                      type: 'tool_call',
                      task_id: task.task_id,
                      trace_id: r.trace_id,
                      iteration: r.iteration,
                      data: {
                        tool_calls: toolCalls,
                        tool_results: toolResults,
                      },
                      timestamp: r.updated_at,
                    });
                  }
                }

                // For RE_PLAN: parse action_output for plan data
                if (r.action_type === 'RE_PLAN' && r.action_output) {
                  try {
                    const planData = JSON.parse(r.action_output);
                    events.push({
                      type: 'plan_update',
                      task_id: task.task_id,
                      trace_id: r.trace_id,
                      iteration: r.iteration,
                      data: planData,
                      timestamp: r.updated_at,
                    });
                  } catch {
                    // If parsing fails, skip adding the event
                  }
                }

                return {
                  iteration: r.iteration,
                  trace_id: r.trace_id,
                  observe: r.observe || undefined,
                  thought: r.thought || undefined,
                  abstract: r.abstract || undefined,
                  // Only show action_type, not the full action_output
                  // Tool calls are rendered separately in TOOL EXECUTION section
                  action: r.action_type || undefined,
                  events: events,
                  status: r.status === 'done' ? 'completed' : r.status === 'error' ? 'error' : 'completed',
                  errorLog: r.error_log || undefined,
                  startTime: r.created_at,
                  endTime: r.updated_at,
                  tokens: {
                    prompt_tokens: r.prompt_tokens,
                    completion_tokens: r.completion_tokens,
                    total_tokens: r.total_tokens,
                  },
                };
              });

              // Add assistant message with recursions
              loadedMessages.push({
                id: `assistant-${task.task_id}`,
                role: 'assistant',
                content: task.agent_answer || '',
                timestamp: task.updated_at,
                task_id: task.task_id,
                recursions: recursions,
                status: task.status === 'completed' ? 'completed' : task.status === 'failed' ? 'error' : 'completed',
                totalTokens: {
                  prompt_tokens: 0,
                  completion_tokens: 0,
                  total_tokens: task.total_tokens,
                },
              });
            }

            setMessages(loadedMessages);
          } catch (historyErr) {
            console.error('Failed to load initial session history:', historyErr);
          }
        } else {
          // Only create a new session if no sessions exist
          const session = await createSession(agentId);
          setCurrentSessionId(session.session_id);
          setSessions([{
            session_id: session.session_id,
            agent_id: session.agent_id,
            status: session.status,
            subject: session.subject?.content || null,
            created_at: session.created_at,
            updated_at: session.updated_at,
            message_count: 0,
          }]);
        }

        setIsInitialized(true);
      } catch (err) {
        console.error('Failed to initialize sessions:', err);
        setError('Failed to initialize session');
      } finally {
        setIsLoadingSession(false);
      }
    };
    void initSessions();
  }, [agentId, isInitialized, isLoadingSession]);

  /**
   * Create a new session and switch to it.
   */
  const handleNewSession = async () => {
    setIsLoadingSession(true);
    try {
      const session = await createSession(agentId);
      setCurrentSessionId(session.session_id);
      setMessages([]); // Clear messages for new session
      setSessions((prev) => [{
        session_id: session.session_id,
        agent_id: session.agent_id,
        status: session.status,
        subject: session.subject?.content || null,
        created_at: session.created_at,
        updated_at: session.updated_at,
        message_count: 0,
      }, ...prev]);
    } catch (err) {
      console.error('Failed to create new session:', err);
      setError('Failed to create new session');
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * Switch to an existing session and load its history.
   */
  const handleSelectSession = async (sessionId: string) => {
    if (sessionId === currentSessionId || isLoadingSession) return;

    setCurrentSessionId(sessionId);
    setIsLoadingSession(true);

    try {
      // Load full session history with recursion details
      const history = await getFullSessionHistory(sessionId);

      // Convert tasks to ChatMessage format with recursion details
      const loadedMessages: ChatMessage[] = [];

      for (const task of history.tasks) {
        // Add user message
        loadedMessages.push({
          id: `user-${task.task_id}`,
          role: 'user',
          content: task.user_message,
          timestamp: task.created_at,
        });

        // Convert recursions to RecursionRecord format
        const recursions: RecursionRecord[] = task.recursions.map((r: RecursionDetail) => {
          // Parse events from recursion data for historical sessions
          let events: ReactStreamEvent[] = [];

          // For CALL_TOOL: parse action_output for tool_calls and tool_call_results for tool_results
          if (r.action_type === 'CALL_TOOL') {
            let toolCalls: unknown[] = [];
            let toolResults: unknown[] = [];

            // Parse tool_calls from action_output
            if (r.action_output) {
              try {
                const actionData = JSON.parse(r.action_output);
                toolCalls = actionData.tool_calls || [];
              } catch {
                // If parsing fails, continue without tool_calls
              }
            }

            // Parse tool_results from tool_call_results
            if (r.tool_call_results) {
              try {
                toolResults = JSON.parse(r.tool_call_results);
              } catch {
                // If parsing fails, continue without tool_results
              }
            }

            // Add tool_call event if we have any data
            if (toolCalls.length > 0 || toolResults.length > 0) {
              events.push({
                type: 'tool_call',
                task_id: task.task_id,
                trace_id: r.trace_id,
                iteration: r.iteration,
                data: {
                  tool_calls: toolCalls,
                  tool_results: toolResults,
                },
                timestamp: r.updated_at,
              });
            }
          }

          // For RE_PLAN: parse action_output for plan data
          if (r.action_type === 'RE_PLAN' && r.action_output) {
            try {
              const planData = JSON.parse(r.action_output);
              events.push({
                type: 'plan_update',
                task_id: task.task_id,
                trace_id: r.trace_id,
                iteration: r.iteration,
                data: planData,
                timestamp: r.updated_at,
              });
            } catch {
              // If parsing fails, skip adding the event
            }
          }

          return {
            iteration: r.iteration,
            trace_id: r.trace_id,
            observe: r.observe || undefined,
            thought: r.thought || undefined,
            abstract: r.abstract || undefined,
            // Only show action_type, not the full action_output
            // Tool calls are rendered separately in TOOL EXECUTION section
            action: r.action_type || undefined,
            events: events,
            status: r.status === 'done' ? 'completed' : r.status === 'error' ? 'error' : 'completed',
            errorLog: r.error_log || undefined,
            startTime: r.created_at,
            endTime: r.updated_at,
            tokens: {
              prompt_tokens: r.prompt_tokens,
              completion_tokens: r.completion_tokens,
              total_tokens: r.total_tokens,
            },
          };
        });

        // Add assistant message with recursions
        loadedMessages.push({
          id: `assistant-${task.task_id}`,
          role: 'assistant',
          content: task.agent_answer || '',
          timestamp: task.updated_at,
          task_id: task.task_id,
          recursions: recursions,
          status: task.status === 'completed' ? 'completed' : task.status === 'failed' ? 'error' : 'completed',
          totalTokens: {
            prompt_tokens: 0,
            completion_tokens: 0,
            total_tokens: task.total_tokens,
          },
        });
      }

      setMessages(loadedMessages);
    } catch (err) {
      console.error('Failed to load session history:', err);
      setMessages([]); // Clear messages on error
    } finally {
      setIsLoadingSession(false);
    }
  };

  /**
   * Delete a session.
   */
  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (sessionId === currentSessionId) {
        // Switch to another session or clear if no sessions left
        const remainingSessions = sessions.filter((s) => s.session_id !== sessionId);
        if (remainingSessions.length > 0) {
          void handleSelectSession(remainingSessions[0].session_id);
        } else {
          // Create a new session if all are deleted
          setCurrentSessionId(null);
          setMessages([]);
          setIsInitialized(false); // Allow re-initialization to create new session
        }
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
      setError('Failed to delete session');
    }
  };

  /**
   * Scroll chat view to bottom.
   */
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  /**
   * Auto-scroll to bottom when messages update.
   */
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  /**
   * Handle form submission to send message.
   */
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (inputMessage.trim() && !isStreaming) {
        void sendMessage();
      }
    }
  };

  /**
   * Handle form submission to send message.
   */
  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!inputMessage.trim() || isStreaming) return;

    void sendMessage();
  };

  /**
   * Stop the current streaming execution.
   * Aborts the fetch request and cancels LLM execution.
   */
  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  /**
   * Send message to ReAct agent.
   */
  const sendMessage = async () => {
    // If replying, use the replyTaskId. Otherwise undefined.
    const currentReplyTaskId = replyTaskId;

    // Reset reply state if we are sending
    if (currentReplyTaskId) {
      setReplyTaskId(null);
    }

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: inputMessage,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputMessage('');
    setError(null);
    setIsStreaming(true);

    // Create assistant message placeholder
    const assistantMessageId = `assistant-${Date.now()}`;
    const assistantMessage: ChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      recursions: [],
      status: 'running',
    };

    setMessages((prev) => [...prev, assistantMessage]);

    // Start SSE stream
    abortControllerRef.current = new AbortController();

    try {
      // Check token validity before making request
      if (!isTokenValid()) {
        window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
        throw new Error('Token expired or invalid. Please log in again.');
      }

      // Use direct backend URL to bypass Vite proxy for SSE streaming
      // This prevents potential data loss in proxy layer
      const apiUrl = `${API_BASE_URL}/react/chat/stream`;

      const token = getAuthToken();
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };

      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const response = await fetch(apiUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          agent_id: agentId,
          message: userMessage.content,
          user: 'web-user',
          task_id: currentReplyTaskId,
          session_id: currentSessionId,
        }),
        signal: abortControllerRef.current.signal,
      });

      // Handle 401 Unauthorized
      if (response.status === 401) {
        window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
        throw new Error('Authentication expired. Please log in again.');
      }

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('Response body is null');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let currentTaskId: string | null = null;
      let currentRecursion: RecursionRecord | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.trim() || !line.startsWith('data: ')) continue;

          const data = line.slice(6).trim();
          if (!data) continue;

          try {
            const event = JSON.parse(data) as ReactStreamEvent;

            if (event.type === 'recursion_start') {
              // Mark previous recursion as completed if it's still running.
              // Capture a snapshot before setMessages — the callback is enqueued
              // and executed later; by then currentRecursion may point elsewhere.
              if (currentRecursion && currentRecursion.status === 'running') {
                const prevRecursionSnapshot: RecursionRecord = {
                  ...currentRecursion,
                  status: 'completed',
                  endTime: event.timestamp,
                };
                // Also update the local variable so subsequent code sees the right state
                currentRecursion = prevRecursionSnapshot;
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      // Filter out nulls and update matching recursion
                      const filtered = (msg.recursions || []).filter((r): r is RecursionRecord => r !== null);
                      const updatedRecursions = filtered.map((r) =>
                        r.iteration === prevRecursionSnapshot.iteration ? prevRecursionSnapshot : r
                      );
                      return { ...msg, recursions: updatedRecursions };
                    }
                    return msg;
                  })
                );
              }

              // Start new recursion
              currentTaskId = event.task_id;
              currentRecursion = {
                iteration: event.iteration,
                trace_id: event.trace_id,
                events: [event],
                status: 'running',
                startTime: event.timestamp,
              };

              // Capture snapshot here for the same stale-closure reason
              const newRecursionSnapshot = currentRecursion;
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                      ...msg,
                      task_id: currentTaskId ?? undefined,
                      // Filter out any nulls from previous state before adding new recursion
                      recursions: [...(msg.recursions?.filter((r): r is RecursionRecord => r !== null) || []), newRecursionSnapshot],
                    }
                    : msg
                )
              );
            } else if (currentRecursion && currentTaskId) {
              // Create new events array to ensure React detects state changes
              const existingRecursion = currentRecursion as RecursionRecord;
              const updatedEvents: ReactStreamEvent[] = [...existingRecursion.events, event];

              if (event.type === 'observe') {
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                  observe: event.delta ?? '',
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'thought') {
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                  thought: event.delta ?? '',
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'abstract') {
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                  abstract: event.delta ?? '',
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'action') {
                // Mark recursion as completed after action event
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                  action: event.delta ?? '',
                  status: 'completed' as const,
                  endTime: event.timestamp,
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'tool_call') {
                // Tool call event - just add to events, no special field update needed
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                };
              } else if (event.type === 'error') {
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                  status: 'error' as const,
                  endTime: event.timestamp,
                  // Preserve tokens if available in error event
                  tokens: event.tokens ?? existingRecursion.tokens,
                };
              } else if (event.type === 'answer') {
                // Answer event - update message content and mark recursion completed
                const answerData = event.data as { answer?: string } | undefined;
                if (answerData?.answer) {
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantMessageId
                        ? {
                          ...msg,
                          content: answerData.answer ?? '',
                        }
                        : msg
                    )
                  );
                }
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                  status: 'completed' as const,
                  endTime: event.timestamp,
                };
              } else if (event.type === 'clarify') {
                // For CLARIFY, we set content similar to ANSWER so it shows in the main box
                const clarifyData = event.data as { question?: string } | undefined;
                if (clarifyData?.question) {
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === assistantMessageId
                        ? {
                          ...msg,
                          content: clarifyData.question ?? '',
                          status: 'waiting_input' as const,
                        }
                        : msg
                    )
                  );
                }
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                  status: 'completed' as const,
                  endTime: event.timestamp,
                };
              } else if (event.type === 'task_complete') {
                // Task complete - update message status and all running recursions
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      // Filter out nulls and mark all running recursions as completed
                      const filtered = (msg.recursions || []).filter((r): r is RecursionRecord => r !== null);
                      const updatedRecursions = filtered.map((r) =>
                        r.status === 'running'
                          ? { ...r, status: 'completed' as const, endTime: event.timestamp }
                          : r
                      );
                      return {
                        ...msg,
                        status: 'completed',
                        recursions: updatedRecursions,
                        timestamp: event.timestamp,  // Update to task completion time
                        totalTokens: event.total_tokens,  // Save total token usage
                      };
                    }
                    return msg;
                  })
                );
                // Don't update currentRecursion for task_complete - it's handled above
                // Skip the general setMessages call below
                currentRecursion = null;
              } else {
                // Handle other events (plan_update, reflect, etc.) - just add to events
                currentRecursion = {
                  ...existingRecursion,
                  events: updatedEvents,
                };
              }

              // Update recursion events - preserve all currentRecursion data.
              // Skip if currentRecursion was set to null (e.g., for task_complete).
              // IMPORTANT: Capture currentRecursion into an immutable const snapshot
              // BEFORE calling setMessages. React state updater functions are enqueued
              // and executed asynchronously during reconciliation. The `currentRecursion`
              // let-variable may be mutated (or nulled) by a later SSE event before
              // React runs this callback, causing a null-dereference crash at runtime.
              if (currentRecursion) {
                const frozenRecursion = currentRecursion;
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      // Filter out nulls and update matching recursion
                      const filtered = (msg.recursions || []).filter((r): r is RecursionRecord => r !== null);
                      const updatedRecursions = filtered.map((r) =>
                        r.iteration === frozenRecursion.iteration
                          ? { ...frozenRecursion }
                          : r
                      );
                      return { ...msg, recursions: updatedRecursions };
                    }
                    return msg;
                  })
                );
              }
            }
          } catch (err) {
            console.error('Failed to parse SSE event:', err);
          }
        }
      }

      setIsStreaming(false);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // User cancelled - mark current recursion as cancelled
        const cancelTime = new Date().toISOString();
        setMessages((prev) =>
          prev.map((msg) => {
            if (msg.id === assistantMessageId) {
              // Filter out nulls first, then mark the last running recursion as cancelled
              const filteredRecursions = msg.recursions?.filter((r): r is RecursionRecord => r !== null) || [];
              const updatedRecursions = filteredRecursions.map((r, idx, arr) =>
                idx === arr.length - 1 && r.status === 'running'
                  ? { ...r, status: 'error' as const, endTime: cancelTime }
                  : r
              );
              return {
                ...msg,
                status: 'error',
                content: msg.content || 'Execution stopped by user',
                recursions: updatedRecursions,
                timestamp: cancelTime,  // Update to cancellation time
              };
            }
            return msg;
          })
        );
      } else {
        const error = err instanceof Error ? err : new Error(String(err));
        const errorTime = new Date().toISOString();
        setError(error.message);
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId
              ? {
                ...msg,
                status: 'error',
                content: `Error: ${error.message}`,
                timestamp: errorTime,  // Update to error time
              }
              : msg
          )
        );
      }
      setIsStreaming(false);
    }
  };

  /**
   * Toggle recursion expansion.
   */
  const toggleRecursion = (messageId: string, iteration: number) => {
    const key = `${messageId}-${iteration}`;
    setExpandedRecursions((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  /**
   * Format answer content with basic markdown support.
   * Handles: ### and #### headings, **bold**, line breaks, and paragraphs.
   */
  const formatAnswerContent = (content: string) => {
    if (!content) return null;

    // First, normalize paragraph breaks
    // Split content into blocks by analyzing heading patterns
    const lines = content.split('\n');
    const blocks: string[] = [];
    let currentBlock: string[] = [];

    for (const line of lines) {
      // Check if line is a heading
      if (line.match(/^#{3,4}\s+/)) {
        // Save current block if it has content
        if (currentBlock.length > 0) {
          blocks.push(currentBlock.join('\n'));
          currentBlock = [];
        }
        // Start new block with heading
        currentBlock.push(line);
      } else if (line.trim() === '' && currentBlock.length > 0) {
        // Empty line - might be paragraph break
        currentBlock.push(line);
      } else {
        // Regular content line
        currentBlock.push(line);
      }
    }

    // Add final block
    if (currentBlock.length > 0) {
      blocks.push(currentBlock.join('\n'));
    }

    // Render blocks
    return blocks.map((block, bIdx) => {
      const trimmedBlock = block.trim();
      if (!trimmedBlock) return null;

      // Check for headings (must use #### before ### to avoid false matches)
      const h4Match = trimmedBlock.match(/^####\s+(.+?)(\n|$)/);
      const h3Match = trimmedBlock.match(/^###\s+(.+?)(\n|$)/);

      if (h4Match) {
        const headingText = h4Match[1];
        const remainingText = trimmedBlock.substring(h4Match[0].length).trim();

        return (
          <div key={bIdx} className="mb-2.5">
            <h4 className="text-sm font-semibold text-foreground mb-1.5">{headingText}</h4>
            {remainingText && (
              <div className="text-sm text-foreground leading-relaxed">
                {formatInlineMarkdown(remainingText)}
              </div>
            )}
          </div>
        );
      }

      if (h3Match) {
        const headingText = h3Match[1];
        const remainingText = trimmedBlock.substring(h3Match[0].length).trim();

        return (
          <div key={bIdx} className="mb-3">
            <h3 className="text-base font-bold text-foreground mb-2">{headingText}</h3>
            {remainingText && (
              <div className="text-sm text-foreground leading-relaxed">
                {formatInlineMarkdown(remainingText)}
              </div>
            )}
          </div>
        );
      }

      // Regular paragraph
      return (
        <p key={bIdx} className="text-sm text-foreground leading-relaxed mb-2">
          {formatInlineMarkdown(trimmedBlock)}
        </p>
      );
    }).filter(Boolean);
  };

  /**
   * Format inline markdown (bold, line breaks).
   */
  const formatInlineMarkdown = (text: string) => {
    const parts: (string | JSX.Element)[] = [];
    let lastIndex = 0;

    // Match **bold** patterns
    const boldPattern = /\*\*(.+?)\*\*/g;
    let match;

    while ((match = boldPattern.exec(text)) !== null) {
      // Add text before match
      if (match.index > lastIndex) {
        const beforeText = text.substring(lastIndex, match.index);
        parts.push(...formatLineBreaks(beforeText, parts.length));
      }

      // Add bold text
      parts.push(
        <strong key={`bold-${match.index}`} className="font-semibold">
          {match[1]}
        </strong>
      );

      lastIndex = match.index + match[0].length;
    }

    // Add remaining text
    if (lastIndex < text.length) {
      parts.push(...formatLineBreaks(text.substring(lastIndex), parts.length));
    }

    return parts;
  };

  /**
   * Convert line breaks to <br /> tags.
   */
  const formatLineBreaks = (text: string, startKey: number) => {
    const lines = text.split('\n');
    const result: (string | JSX.Element)[] = [];

    lines.forEach((line, idx) => {
      if (idx > 0) {
        result.push(<br key={`br-${startKey}-${idx}`} />);
      }
      if (line) {
        result.push(line);
      }
    });

    return result;
  };

  /**
   * Calculate duration in seconds between two ISO timestamps.
   */
  const calculateDuration = (startTime: string, endTime?: string): number => {
    if (!endTime) return 0;
    const start = new Date(startTime).getTime();
    const end = new Date(endTime).getTime();
    return Math.round((end - start) / 1000 * 10) / 10; // Round to 1 decimal place
  };

  /**
   * Format token count with thousands separator.
   */
  const formatTokenCount = (count: number): string => {
    return count.toLocaleString();
  };

  /**
   * Check if recursion has any failed tool calls.
   */
  const hasFailedTools = (recursion: RecursionRecord): boolean => {
    const toolCallEvents = recursion.events.filter((e) => e.type === 'tool_call');

    for (const event of toolCallEvents) {
      const toolData = event.data as {
        tool_results?: Array<{ success: boolean }>;
      } | undefined;

      if (toolData?.tool_results?.some((result) => !result.success)) {
        return true;
      }
    }

    return false;
  };

  /**
   * Get effective recursion status considering tool execution results.
   */
  const getRecursionStatus = (recursion: RecursionRecord): 'running' | 'completed' | 'warning' | 'error' => {
    if (recursion.status === 'running') return 'running';
    if (recursion.status === 'error') return 'error';

    // If status is 'completed', check if there are failed tools
    if (hasFailedTools(recursion)) {
      return 'warning';
    }

    return 'completed';
  };

  /**
   * Render a recursion record.
   */
  const renderRecursion = (messageId: string, recursion: RecursionRecord, taskId?: string) => {
    const key = `${messageId}-${recursion.iteration}`;
    const isExpanded = expandedRecursions[key];
    const effectiveStatus = getRecursionStatus(recursion);

    const toolCallEvents = recursion.events.filter((e) => e.type === 'tool_call');

    return (
      <div key={key} className="border border-border rounded-md mb-3 overflow-hidden bg-muted/20">
        {/* Header */}
        <button
          onClick={() => toggleRecursion(messageId, recursion.iteration)}
          className="w-full flex items-center justify-between px-3 py-2 hover:bg-muted/30 transition-colors"
        >
          <div className="flex items-center gap-2 flex-1 min-w-0">
            {effectiveStatus === 'running' && (
              <Loader2
                key={`${key}-running`}
                className="w-3.5 h-3.5 text-primary animate-spin flex-shrink-0"
              />
            )}
            {effectiveStatus === 'completed' && (
              <CheckCircle2
                key={`${key}-completed`}
                className="w-3.5 h-3.5 text-success flex-shrink-0 status-icon-enter"
              />
            )}
            {effectiveStatus === 'warning' && (
              <AlertCircle
                key={`${key}-warning`}
                className="w-3.5 h-3.5 text-warning flex-shrink-0 status-icon-enter"
              />
            )}
            {effectiveStatus === 'error' && (
              <XCircle
                key={`${key}-error`}
                className="w-3.5 h-3.5 text-danger flex-shrink-0 status-icon-enter"
              />
            )}
            {effectiveStatus === 'running' && !recursion.abstract ? (
              <span
                className="text-xs font-semibold truncate animate-thinking-wave"
                style={{
                  background: 'linear-gradient(90deg, #9ca3af 0%, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%, #9ca3af 100%)',
                  backgroundSize: '400% 100%',
                  WebkitBackgroundClip: 'text',
                  backgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                }}
              >
                Thinking...
              </span>
            ) : (
              <span
                className="text-xs font-semibold text-foreground truncate"
                title={recursion.abstract || `Iteration ${recursion.iteration + 1}`}
              >
                {recursion.abstract || `Iteration ${recursion.iteration + 1}`}
              </span>
            )}
            {toolCallEvents.length > 0 && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">
                {toolCallEvents.length} tool{toolCallEvents.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2.5 flex-shrink-0">
            {recursion.endTime && (
              <span className="text-xs text-muted-foreground tabular-nums">
                {calculateDuration(recursion.startTime, recursion.endTime)}s
              </span>
            )}
            {recursion.tokens && (
              <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                {formatTokenCount(recursion.tokens.total_tokens)} tokens
              </span>
            )}
          </div>
        </button>

        {isExpanded && (
          <div className="px-3 pb-3 space-y-2">
            {/* Observe */}
            {recursion.observe && (
              <div className="bg-background/50 rounded border border-border p-2">
                <div className="flex items-center gap-1.5 mb-1">
                  <div className="w-3.5 h-3.5 flex items-center justify-center">
                    <div className="w-1 h-4 bg-blue-500 rounded-full" />
                  </div>
                  <span className="text-xs font-semibold text-foreground">OBSERVE</span>
                </div>
                <p className="text-xs text-muted-foreground pl-5 leading-relaxed">
                  {recursion.observe}
                </p>
              </div>
            )}

            {/* Thought */}
            {recursion.thought && (
              <div className="bg-background/50 rounded border border-border p-2">
                <div className="flex items-center gap-1.5 mb-1">
                  <Brain className="w-3.5 h-3.5 text-purple-500" />
                  <span className="text-xs font-semibold text-foreground">THOUGHT</span>
                </div>
                <p className="text-xs text-muted-foreground pl-5 leading-relaxed">
                  {recursion.thought}
                </p>
              </div>
            )}

            {/* Action */}
            {recursion.action && (
              <div className="bg-background/50 rounded border border-border p-2">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <div className="w-3.5 h-3.5 flex items-center justify-center">
                      <div className="w-1 h-4 bg-green-500 rounded-full" />
                    </div>
                    <span className="text-xs font-semibold text-foreground">ACTION</span>
                  </div>
                  {taskId && (
                    <RecursionStateViewer taskId={taskId} iteration={recursion.iteration} />
                  )}
                </div>
                <p className="text-xs font-mono text-primary pl-5">
                  {recursion.action}
                </p>
              </div>
            )}

            {/* Tool Details */}
            {recursion.events.map((event, idx) => {
              if (event.type === 'tool_call') {
                const toolData = event.data as {
                  tool_calls?: Array<{ id: string; name: string; arguments: Record<string, unknown> | string }>;
                  tool_results?: Array<{ tool_call_id: string; name: string; result?: unknown; error?: string; success: boolean }>;
                } | undefined;

                return (
                  <div key={idx} className="bg-background/50 border border-border rounded p-2">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Wrench className="w-3.5 h-3.5 text-orange-500" />
                      <span className="text-xs font-semibold text-foreground">TOOL EXECUTION</span>
                    </div>
                    <div className="space-y-3 pl-5">
                      {/* Tool Calls (Input Parameters) */}
                      {toolData?.tool_calls?.map((call, cidx) => (
                        <div key={`call-${cidx}`} className="space-y-1">
                          <div className="text-xs font-semibold text-foreground">
                            📥 Call: {call.name}
                          </div>
                          <div className="text-xs p-2 bg-muted/30 rounded font-mono text-muted-foreground border border-border/50">
                            <div className="text-[10px] text-muted-foreground/70 mb-1">Arguments:</div>
                            {typeof call.arguments === 'string'
                              ? call.arguments
                              : JSON.stringify(call.arguments, null, 2)}
                          </div>
                        </div>
                      ))}

                      {/* Tool Results (Output) */}
                      {toolData?.tool_results?.map((result, ridx) => (
                        <div key={`result-${ridx}`} className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-foreground">
                              📤 Result: {result.name}
                            </span>
                            {result.success ? (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-success/10 text-success">
                                ✓
                              </span>
                            ) : (
                              <span className="text-xs px-1.5 py-0.5 rounded bg-danger/10 text-danger">
                                ✗
                              </span>
                            )}
                          </div>
                          {result.result !== undefined && result.result !== null && (
                            <div className="text-xs p-2 bg-muted/30 rounded font-mono text-muted-foreground border border-border/50 break-all">
                              {typeof result.result === 'string'
                                ? result.result
                                : JSON.stringify(result.result, null, 2)}
                            </div>
                          )}
                          {result.error && (
                            <div className="text-xs p-2 bg-danger/10 rounded text-danger border border-danger/30">
                              {result.error}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              }

              if (event.type === 'plan_update') {
                const planData = event.data as {
                  plan?: Array<{
                    step_id: string;
                    description: string;
                    status: string
                  }>
                } | undefined;

                return (
                  <div key={idx} className="bg-background/50 border border-border rounded p-2">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Brain className="w-3.5 h-3.5 text-purple-500" />
                      <span className="text-xs font-semibold text-foreground">PLAN UPDATE</span>
                    </div>
                    {planData?.plan && planData.plan.length > 0 ? (
                      <div className="space-y-1 pl-5">
                        {planData.plan.map((step, sidx) => (
                          <div key={sidx} className="text-xs text-muted-foreground">
                            {sidx + 1}. {step.description}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-muted-foreground/50 pl-5 italic">
                        No plan data available
                      </div>
                    )}
                  </div>
                );
              }

              if (event.type === 'reflect') {
                const reflectData = event.data as { summary?: string } | undefined;

                return (
                  <div key={idx} className="bg-background/50 border border-border rounded p-2">
                    <div className="flex items-center gap-1.5 mb-2">
                      <Brain className="w-3.5 h-3.5 text-indigo-500" />
                      <span className="text-xs font-semibold text-foreground">REFLECT</span>
                    </div>
                    <div className="text-xs text-muted-foreground pl-5 leading-relaxed">
                      {reflectData?.summary || 'Reflecting on current state...'}
                    </div>
                  </div>
                );
              }

              if (event.type === 'error') {
                const errorData = event.data as { error?: string } | undefined;
                return (
                  <div key={idx} className="bg-danger/5 border border-danger/30 rounded p-2">
                    <div className="flex items-center gap-1.5 mb-1">
                      <XCircle className="w-3.5 h-3.5 text-danger" />
                      <span className="text-xs font-semibold text-danger">ERROR</span>
                    </div>
                    <div className="text-xs pl-5 text-danger/90">
                      {errorData?.error || 'Unknown error'}
                    </div>
                  </div>
                );
              }

              return null;
            })}

            {/* Error Log - Display if recursion has error_log */}
            {recursion.errorLog && (
              <div className="bg-danger/5 border border-danger/30 rounded p-2">
                <div className="flex items-center gap-1.5 mb-1">
                  <XCircle className="w-3.5 h-3.5 text-danger" />
                  <span className="text-xs font-semibold text-danger">ERROR LOG</span>
                </div>
                <div className="text-xs pl-5 text-danger/90 leading-relaxed">
                  {recursion.errorLog}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex h-full bg-background text-foreground overflow-hidden">
      {/* Sidebar - Session List */}
      <div
        className={`flex-shrink-0 border-r border-border flex flex-col bg-muted/30 transition-all duration-300 ease-in-out ${isSidebarCollapsed ? 'w-12' : 'w-64'
          }`}
      >
        {/* Sidebar Header */}
        <div className={`p-3 border-b border-border flex items-center ${isSidebarCollapsed ? 'justify-center' : 'justify-between'}`}>
          {!isSidebarCollapsed && (
            <Button
              onClick={handleNewSession}
              variant="outline"
              className="flex-1 justify-start gap-2"
              disabled={isLoadingSession || isStreaming}
            >
              <PlusCircle className="w-4 h-4" />
              New Session
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className={`h-8 w-8 ${isSidebarCollapsed ? '' : 'ml-2'}`}
            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            title={isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isSidebarCollapsed ? (
              <PanelLeft className="w-4 h-4" />
            ) : (
              <PanelLeftClose className="w-4 h-4" />
            )}
          </Button>
        </div>

        {/* Session List */}
        {!isSidebarCollapsed && (
          <div className="flex-1 overflow-y-auto">
            <div className="p-2 space-y-1">
              {sessions.length === 0 ? (
                <div className="text-center text-muted-foreground text-sm py-4">
                  {isLoadingSession ? (
                    <div className="flex items-center justify-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Creating session...</span>
                    </div>
                  ) : (
                    <span>No sessions yet</span>
                  )}
                </div>
              ) : (
                sessions.map((session) => (
                  <div
                    key={session.session_id}
                    onClick={() => void handleSelectSession(session.session_id)}
                    className={`w-full text-left p-2 rounded-lg transition-colors group cursor-pointer ${session.session_id === currentSessionId
                      ? 'bg-primary/10 border border-primary/30'
                      : 'hover:bg-muted border border-transparent'
                      }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <MessageCircle className="w-3.5 h-3.5 flex-shrink-0 text-muted-foreground" />
                          <span className="text-sm font-medium truncate">
                            {session.subject || 'New conversation'}
                          </span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1 pl-5">
                          {formatTimestamp(session.updated_at)}
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5 pl-5">
                          {session.message_count} messages
                        </div>
                      </div>
                      <button
                        type="button"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 flex items-center justify-center rounded hover:bg-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDeleteSession(session.session_id);
                        }}
                        title="Delete session"
                      >
                        <Trash2 className="w-3.5 h-3.5 text-muted-foreground hover:text-destructive" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Collapsed state - show icon buttons */}
        {isSidebarCollapsed && (
          <div className="flex-1 flex flex-col items-center py-2 space-y-2">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={handleNewSession}
              disabled={isLoadingSession || isStreaming}
              title="New Session"
            >
              <PlusCircle className="w-4 h-4" />
            </Button>
          </div>
        )}
      </div>

      {/* Main Chat Area - single scrollable container for both messages and input */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto">
          {/* Centered content container */}
          <div className="max-w-3xl mx-auto p-4 pb-4">
            {messages.length === 0 ? (
              <div className="text-center text-muted-foreground mt-12 animate-fade-in">
                <div className="mb-4">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-muted flex items-center justify-center">
                    <MessageSquare className="w-8 h-8 text-muted-foreground" />
                  </div>
                  <p className="text-base font-medium text-foreground mb-2">
                    Chat with ReAct Agent
                  </p>
                  <p className="text-sm opacity-70">
                    Ask questions or give tasks. I'll show you my reasoning process.
                  </p>
                </div >
              </div >
            ) : (
              messages.map((message) => (
                <div key={message.id} className="space-y-2 mb-6 last:mb-0">
                  {message.role === 'user' ? (
                    <div className="flex justify-end">
                      <div className="max-w-[85%] px-4 py-2.5 rounded-2xl shadow-sm bg-primary text-primary-foreground rounded-br-none">
                        <div className="font-semibold text-xs mb-1 opacity-90 tracking-wide uppercase">
                          YOU
                        </div>
                        <div className="text-[10px] mb-1 opacity-70 font-mono">
                          {formatTimestamp(message.timestamp)}
                        </div>
                        <div className="text-sm leading-relaxed whitespace-pre-wrap break-words">
                          {message.content}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {/* Recursions */}
                      {message.recursions && message.recursions.length > 0 && (
                        <div className="space-y-2">
                          {message.recursions.filter((r) => r !== null).map((recursion) =>
                            renderRecursion(message.id, recursion, message.task_id)
                          )}
                        </div>
                      )}

                      {/* Final Answer / Question */}
                      {message.content && (
                        <div className="bg-background/50 border border-border rounded-lg p-3">
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-1.5">
                              {message.status === 'waiting_input' || (message.recursions?.length && message.recursions.filter((r) => r !== null)[message.recursions.filter((r) => r !== null).length - 1]?.action === 'CLARIFY') ? (
                                <>
                                  <MessageSquare className="w-3.5 h-3.5 text-info" />
                                  <span className="text-xs font-semibold text-foreground">QUESTION</span>
                                </>
                              ) : (
                                <>
                                  <MessageSquare className="w-3.5 h-3.5 text-success" />
                                  <span className="text-xs font-semibold text-foreground">FINAL ANSWER</span>
                                </>
                              )}
                            </div>
                            {/* REPLY button for QUESTION */}
                            {(message.status === 'waiting_input' || (message.recursions?.length && message.recursions.filter((r) => r !== null)[message.recursions.filter((r) => r !== null).length - 1]?.action === 'CLARIFY')) && message.task_id && (
                              <button
                                onClick={() => setReplyTaskId(message.task_id || null)}
                                className="text-xs text-muted-foreground hover:text-info transition-colors"
                              >
                                REPLY
                              </button>
                            )}
                          </div>
                          <div className="text-sm text-foreground pl-5 leading-relaxed">
                            {formatAnswerContent(message.content)}
                          </div>
                        </div>
                      )}

                      {/* Status */}
                      <div className="flex items-center gap-2 px-3">
                        {message.status === 'running' && (
                          <>
                            <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
                            <span className="text-xs text-muted-foreground">Processing...</span>
                          </>
                        )}
                        {message.status === 'completed' && (
                          <>
                            <CheckCircle2 className="w-3.5 h-3.5 text-success" />
                            <span className="text-xs text-muted-foreground">Completed</span>
                            {message.totalTokens && (
                              <span className="text-xs text-muted-foreground ml-2">
                                • Total: {formatTokenCount(message.totalTokens.total_tokens)} tokens
                              </span>
                            )}
                          </>
                        )}
                        {message.status === 'error' && (
                          <>
                            <XCircle className="w-3.5 h-3.5 text-danger" />
                            <span className="text-xs text-danger">Error</span>
                          </>
                        )}
                        <span className="text-xs text-muted-foreground ml-auto">
                          {formatTimestamp(message.timestamp)}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              ))
            )
            }
            <div ref={messagesEndRef} />

            {/* Input Area - sticky at bottom with negative margins to extend to container edges */}
            <div className="sticky bottom-0 -mx-4 -mb-4 px-4 pb-4 pt-6 mt-4 bg-gradient-to-t from-background via-background to-transparent">
              {/* Error Banner */}
              {error && (
                <div className="px-4 py-2 mb-2 bg-danger/10 border border-danger/30 rounded-lg text-danger text-sm">
                  {error}
                </div>
              )}

              {replyTaskId && (
                <div className="flex items-center justify-between text-xs mb-2 px-3 py-1.5 rounded-lg bg-muted/50 border border-border/50">
                  <span className="text-foreground/70">↳ Replying to question</span>
                  <button
                    onClick={() => setReplyTaskId(null)}
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    title="Cancel reply"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              <form onSubmit={handleSubmit} className="relative overflow-hidden rounded-2xl border bg-background shadow-lg focus-within:border-ring transition-all">
                <Textarea
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={replyTaskId ? "Reply to question..." : "Ask anything"}
                  className="min-h-[60px] w-full resize-none border-0 p-4 shadow-none focus-visible:ring-0 focus-visible:shadow-none focus:shadow-none focus:outline-none"
                  disabled={isStreaming}
                />
                <div className="flex items-center px-4 pb-3 justify-between">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full">
                        <Plus className="h-4 h-4" />
                        <span className="sr-only">Attach</span>
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                      <DropdownMenuItem>
                        <Paperclip className="mr-2 h-4 w-4" />
                        <span>Add images & files</span>
                      </DropdownMenuItem>
                      <DropdownMenuItem>
                        <Brain className="mr-2 h-4 w-4" />
                        <span>Thinking</span>
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <div className="flex items-center gap-2">
                    {isStreaming ? (
                      <Button
                        type="button"
                        onClick={handleStop}
                        size="icon"
                        className="h-8 w-8 rounded-full bg-destructive/90 hover:bg-destructive text-destructive-foreground"
                        title="Stop execution"
                      >
                        <Square className="h-4 w-4" fill="currentColor" />
                      </Button>
                    ) : (
                      <Button
                        type="submit"
                        disabled={!inputMessage.trim()}
                        size="icon"
                        className="h-8 w-8 rounded-full"
                        title="Send message"
                      >
                        <ArrowUp className="h-4 w-4" />
                        <span className="sr-only">Send</span>
                      </Button>
                    )}
                  </div>
                </div>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div >
  );
}

export default ReactChatInterface;
