import { useState, useRef, useEffect, FormEvent } from 'react';
import { Send, Loader2, CheckCircle2, XCircle, AlertCircle, Wrench, Brain, MessageSquare, Square } from 'lucide-react';
import { formatTimestamp } from '../utils/timestamp';

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
  | 'task_complete'
  | 'error';

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
  startTime: string;
  endTime?: string;
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
  status?: 'running' | 'completed' | 'error';
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
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

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
      const response = await fetch('/api/react/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          agent_id: agentId,
          message: userMessage.content,
          user: 'web-user',
        }),
        signal: abortControllerRef.current.signal,
      });

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
              // Mark previous recursion as completed if it's still running
              if (currentRecursion && currentRecursion.status === 'running') {
                currentRecursion.status = 'completed';
                currentRecursion.endTime = event.timestamp;
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      const updatedRecursions = msg.recursions?.map((r) =>
                        r.iteration === currentRecursion!.iteration ? currentRecursion! : r
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

              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        task_id: currentTaskId ?? undefined,
                        recursions: [...(msg.recursions || []), currentRecursion!],
                      }
                    : msg
                )
              );
            } else if (currentRecursion && currentTaskId) {
              // Add event to current recursion
              currentRecursion.events.push(event);

              if (event.type === 'observe') {
                currentRecursion.observe = event.delta ?? '';
              } else if (event.type === 'thought') {
                currentRecursion.thought = event.delta ?? '';
              } else if (event.type === 'abstract') {
                currentRecursion.abstract = event.delta ?? '';
              } else if (event.type === 'action') {
                currentRecursion.action = event.delta ?? '';
              } else if (event.type === 'tool_call') {
                // Tool call event is already in events array, no special handling needed
                // No special handling needed - data is rendered in renderRecursion
              } else if (event.type === 'error') {
                currentRecursion.status = 'error';
                currentRecursion.endTime = event.timestamp;
              } else if (event.type === 'answer') {
                // Extract answer content
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
                // Mark current recursion as completed
                if (currentRecursion) {
                  currentRecursion.status = 'completed';
                  currentRecursion.endTime = event.timestamp;
                }
              } else if (event.type === 'task_complete') {
                setMessages((prev) =>
                  prev.map((msg) => {
                    if (msg.id === assistantMessageId) {
                      // Mark all running recursions as completed
                      const updatedRecursions = msg.recursions?.map((r) =>
                        r.status === 'running'
                          ? { ...r, status: 'completed' as const, endTime: event.timestamp }
                          : r
                      );
                      return {
                        ...msg,
                        status: 'completed',
                        recursions: updatedRecursions,
                        timestamp: event.timestamp,  // Update to task completion time
                      };
                    }
                    return msg;
                  })
                );
              }

              // Update recursion events
              setMessages((prev) =>
                prev.map((msg) =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        recursions: msg.recursions?.map((r) =>
                          r.iteration === currentRecursion!.iteration ? currentRecursion! : r
                        ),
                      }
                    : msg
                )
              );
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
              // Mark the last recursion as cancelled if it exists
              const updatedRecursions = msg.recursions?.map((r, idx, arr) =>
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
  const renderRecursion = (messageId: string, recursion: RecursionRecord) => {
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
              <Loader2 className="w-3.5 h-3.5 text-primary animate-spin flex-shrink-0" />
            )}
            {effectiveStatus === 'completed' && (
              <CheckCircle2 className="w-3.5 h-3.5 text-success flex-shrink-0" />
            )}
            {effectiveStatus === 'warning' && (
              <AlertCircle className="w-3.5 h-3.5 text-warning flex-shrink-0" />
            )}
            {effectiveStatus === 'error' && <XCircle className="w-3.5 h-3.5 text-danger flex-shrink-0" />}
            {effectiveStatus === 'running' ? (
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
          <span className="text-xs text-muted-foreground">
            {formatTimestamp(recursion.startTime)}
          </span>
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
                <div className="flex items-center gap-1.5 mb-1">
                  <div className="w-3.5 h-3.5 flex items-center justify-center">
                    <div className="w-1 h-4 bg-green-500 rounded-full" />
                  </div>
                  <span className="text-xs font-semibold text-foreground">ACTION</span>
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
                  tool_calls?: Array<{ id: string; type: string; function: { name: string; arguments: string } }>;
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
                            📥 Call: {call.function.name}
                          </div>
                          <div className="text-xs p-2 bg-muted/30 rounded font-mono text-muted-foreground border border-border/50">
                            <div className="text-[10px] text-muted-foreground/70 mb-1">Arguments:</div>
                            {call.function.arguments}
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
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full bg-background text-foreground overflow-hidden">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div key={message.id} className="space-y-2">
              {message.role === 'user' ? (
                <div className="flex justify-end">
                  <div className="max-w-[85%] lg:max-w-[75%] px-3 py-2 rounded-xl shadow-sm bg-primary text-primary-foreground rounded-br-none">
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
                      {message.recursions.map((recursion) =>
                        renderRecursion(message.id, recursion)
                      )}
                    </div>
                  )}

                  {/* Final Answer */}
                  {message.content && (
                    <div className="bg-background border border-border rounded-lg px-3 py-2.5">
                      <div className="flex items-center gap-1.5 mb-2">
                        <MessageSquare className="w-3.5 h-3.5 text-success" />
                        <span className="text-xs font-semibold text-foreground">FINAL ANSWER</span>
                      </div>
                      <div className="pl-5">
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
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Error Banner */}
      {error && (
        <div className="px-4 py-2 bg-danger/10 border-t border-danger text-danger text-sm">
          {error}
        </div>
      )}

      {/* Input Area */}
      <div className="border-t border-border p-4 bg-background">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder="Type your message…"
            disabled={isStreaming}
            className="flex-1 px-3 py-2 text-sm bg-background border border-input rounded-lg focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 disabled:cursor-not-allowed"
          />
          {isStreaming ? (
            <button
              type="button"
              onClick={handleStop}
              className="px-4 py-2 bg-destructive text-destructive-foreground rounded-lg hover:bg-destructive/90 transition-colors flex items-center gap-2"
              title="Stop execution"
            >
              <Square className="w-4 h-4" fill="currentColor" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!inputMessage.trim()}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            >
              <Send className="w-4 h-4" />
            </button>
          )}
        </form>
      </div>
    </div>
  );
}

export default ReactChatInterface;
