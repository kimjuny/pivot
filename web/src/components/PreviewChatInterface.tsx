import { useState, useRef, useEffect, FormEvent } from 'react';
import { usePreviewChatStore } from '../store/previewChatStore';
import { useAgentWorkStore } from '../store/agentWorkStore';
import { formatTimestamp } from '../utils/timestamp';
import type { ChatHistory } from '../types';

/**
 * Streaming indicator component that shows a spinning circle
 * while the agent is generating a response.
 */
function StreamingIndicator() {
  return (
    <svg
      className="animate-spin h-3.5 w-3.5 text-primary"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      ></circle>
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      ></path>
    </svg>
  );
}

/**
 * Props for PreviewChatInterface component.
 */
interface PreviewChatInterfaceProps {
  /** Unique identifier of the agent */
  agentId: number;
}

/**
 * Preview Chat interface component for testing agent conversations.
 * Displays chat history and allows sending new messages.
 * Uses ephemeral PreviewChatStore and works with PreviewAgentDetail.
 */
function PreviewChatInterface({ agentId }: PreviewChatInterfaceProps) {
  const { chatHistory, sendMessage, isChatting, error, clearError, clearHistory } = usePreviewChatStore();
  const { previewAgent } = useAgentWorkStore();

  const [inputMessage, setInputMessage] = useState<string>('');
  const [expandedThinking, setExpandedThinking] = useState<Record<number, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const thinkingRefs = useRef<Record<number, HTMLDivElement | null>>({});

  /**
   * Scroll chat view to bottom.
   */
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  /**
   * Initialize chat when entering preview mode.
   * Clears history on mount (or when agentId changes).
   */
  useEffect(() => {
    clearHistory();
  }, [agentId, clearHistory]);

  /**
   * Auto-scroll to bottom when chat history updates.
   */
  useEffect(() => {
    scrollToBottom();
  }, [chatHistory]);

  /**
   * Auto-scroll thinking sections to bottom when content updates during streaming.
   * This ensures the latest thinking content is always visible.
   */
  useEffect(() => {
    if (isChatting && chatHistory.length > 0) {
      const lastMessageIndex = chatHistory.length - 1;
      const lastMessage = chatHistory[lastMessageIndex];

      // Auto-expand thinking section for the last agent message during streaming
      if (lastMessage?.role === 'agent' && lastMessage.reason && !expandedThinking[lastMessageIndex]) {
        setExpandedThinking(prev => ({
          ...prev,
          [lastMessageIndex]: true
        }));
      }

      // If the last message is from agent and has thinking content, scroll it to bottom
      if (lastMessage?.role === 'agent' && lastMessage.reason && expandedThinking[lastMessageIndex]) {
        const thinkingContainer = thinkingRefs.current[lastMessageIndex];
        if (thinkingContainer) {
          thinkingContainer.scrollTop = thinkingContainer.scrollHeight;
        }
      }
    }
  }, [chatHistory, isChatting, expandedThinking]);

  /**
   * Handle form submission to send message.
   */
  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!inputMessage.trim() || isChatting) return;

    try {
      await sendMessage(inputMessage);
      setInputMessage('');
    } catch (err) {
      void err;
    }
  };

  /**
   * Toggle visibility of agent reasoning for a message.
   */
  const toggleThinking = (index: number) => {
    setExpandedThinking(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  if (!previewAgent) {
    return (
      <div className="flex items-center justify-center h-full text-dark-text-muted">
        Preview not available.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-dark-bg text-dark-text-primary overflow-hidden">
      <div className="px-5 py-4 border-b border-dark-border bg-dark-bg flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white flex items-center tracking-tight">
          <span className="w-2 h-2 bg-primary rounded-full mr-2.5 animate-pulse"></span>
          Preview Chat
        </h2>
        <button
          onClick={() => clearHistory()}
          className="text-xs font-medium text-dark-text-secondary hover:text-primary transition-colors px-3 py-1.5 rounded-lg hover:bg-dark-bg-lighter border border-transparent hover:border-dark-border"
        >
          Reset
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-4 bg-dark-bg">
        {chatHistory.length === 0 ? (
          <div className="text-center text-dark-text-muted mt-12 animate-fade-in">
            <div className="mb-4">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-dark-border-light flex items-center justify-center">
                <svg className="w-8 h-8 text-dark-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
              <p className="text-base font-medium text-dark-text-secondary mb-2">Start previewing your agent</p>
              <p className="text-sm opacity-70">Changes in Workspace are reflected here.</p>
            </div>
          </div>
        ) : (
          chatHistory.map((message: ChatHistory, index: number) => (
            <div
              key={index}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'} animate-slide-up`}
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <div
                className={`max-w-[85%] lg:max-w-[75%] px-4 py-3 rounded-xl shadow-md ${message.role === 'user'
                  ? 'bg-primary text-white rounded-br-none'
                  : 'bg-dark-bg-lighter text-dark-text-primary border border-dark-border rounded-bl-none'}`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div>
                    <div className="font-semibold text-xs opacity-90 tracking-wide uppercase">
                      {message.role === 'user' ? 'You' : 'Preview Agent'}
                    </div>
                    <div className="text-[10px] opacity-70 font-mono">
                      {formatTimestamp(message.create_time)}
                    </div>
                  </div>
                  {/* Show streaming indicator next to title when agent is generating */}
                  {message.role === 'agent' && isChatting && index === chatHistory.length - 1 && (
                    <StreamingIndicator />
                  )}
                </div>
                {message.role === 'agent' && message.reason && (
                  <div
                    className="cursor-pointer"
                    onClick={() => toggleThinking(index)}
                  >
                    <div className="text-xs text-primary mb-1.5 italic opacity-90 border-l-2 border-primary pl-2 flex items-center justify-between">
                      <span className="font-medium">Thinking:</span>
                      <svg
                        className={`w-3 h-3 transition-transform duration-200 ${expandedThinking[index] ? 'rotate-90' : ''}`}
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                    <div
                      className={`overflow-hidden transition-all duration-300 ease-in-out ${expandedThinking[index] ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'}`}
                    >
                      <div
                        ref={(el) => { thinkingRefs.current[index] = el; }}
                        className="max-h-64 overflow-y-auto text-xs text-primary mb-1.5 italic opacity-90 border-l-2 border-primary pl-2 pr-1 scrollbar-thin scrollbar-thumb-primary/30 scrollbar-track-transparent hover:scrollbar-thumb-primary/50"
                      >
                        {message.reason}
                      </div>
                    </div>
                  </div>
                )}
                <div className="text-sm leading-relaxed">
                  {message.message}
                </div>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>

      {error && (
        <div className="mx-5 mb-3 p-3 bg-red-900/20 border border-red-800/50 text-red-300 text-sm rounded-lg animate-fade-in">
          <div className="flex justify-between items-center">
            <span className="flex items-center">
              <svg className="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293 1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
              {error}
            </span>
            <button onClick={clearError} className="font-bold hover:text-red-200 transition-colors ml-2">&times;</button>
          </div>
        </div>
      )}

      <form onSubmit={(e) => { void handleSubmit(e); }} className="p-5 border-t border-dark-border bg-dark-bg">
        <div className="flex space-x-3">
          <input
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            placeholder="Type your message..."
            disabled={isChatting}
            className="flex-1 px-4 py-3 border border-dark-border rounded-xl bg-dark-bg-lighter text-dark-text-primary input-dark placeholder:text-dark-text-muted transition-all"
          />
          <button
            type="submit"
            disabled={!inputMessage.trim() || isChatting}
            className="px-6 py-3 btn-accent rounded-xl disabled:opacity-50 disabled:cursor-not-allowed font-medium"
          >
            Send
          </button>
        </div>
        <div className="mt-3 text-xs text-dark-text-muted text-center opacity-70">
          Stateless preview mode - changes here are not saved to chat history.
        </div>
      </form>
    </div>
  );
}

export default PreviewChatInterface;
