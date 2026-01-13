import { useState, useRef, useEffect, FormEvent } from 'react';
import { useChatStore } from '../store/chatStore';
import { formatTimestamp } from '../utils/timestamp';
import type { ChatHistory } from '../types';

/**
 * Props for ChatInterface component.
 */
interface ChatInterfaceProps {
  /** Unique identifier of the agent */
  agentId: number;
}

/**
 * Chat interface component for interacting with an agent.
 * Displays chat history and allows sending new messages.
 * Shows agent reasoning in expandable sections.
 */
function ChatInterface({ agentId }: ChatInterfaceProps) {
  const { chatHistory, chatWithAgentById, isChatting, error, clearError, loadChatHistory, clearChatHistory } = useChatStore();
  const [inputMessage, setInputMessage] = useState<string>('');
  const [hasLoadedHistory, setHasLoadedHistory] = useState<boolean>(false);
  const [expandedThinking, setExpandedThinking] = useState<Record<number, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  /**
   * Scroll chat view to bottom.
   * Ensures latest messages are visible.
   */
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  /**
   * Load chat history when agentId changes.
   * Prevents duplicate loading with hasLoadedHistory flag.
   */
  useEffect(() => {
    if (agentId && !hasLoadedHistory) {
      void loadChatHistory(agentId, 'preview-user');
      setHasLoadedHistory(true);
    }
  }, [agentId, hasLoadedHistory, loadChatHistory]);

  /**
   * Auto-scroll to bottom when chat history updates.
   * Ensures user sees latest messages.
   */
  useEffect(() => {
    scrollToBottom();
  }, [chatHistory]);

  /**
   * Clear chat history and reload.
   * Resets expanded thinking states and fetches fresh history.
   */
  const handleClearHistory = async () => {
    try {
      await clearChatHistory(agentId, 'preview-user');
      setExpandedThinking({});
      await loadChatHistory(agentId, 'preview-user');
    } catch (err) {
      void err;
    }
  };

  useEffect(() => {
  }, [agentId]);

  /**
   * Handle form submission to send message.
   * Validates input and prevents duplicate submissions.
   * 
   * @param e - Form event from submit
   */
  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!inputMessage.trim() || isChatting) return;

    try {
      await chatWithAgentById(agentId, inputMessage, 'preview-user');
      setInputMessage('');
    } catch (err) {
      void err;
    }
  };

  /**
   * Handle reset agent button click.
   * TODO: Implement agent reset functionality.
   */
  const handleReset = () => {
    window.confirm('Are you sure you want to reset the agent?');
  };

  /**
   * Toggle visibility of agent reasoning for a message.
   * 
   * @param index - Index of message in chat history
   */
  const toggleThinking = (index: number) => {
    setExpandedThinking(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
  };

  return (
    <div className="flex flex-col h-full bg-dark-bg text-dark-text-primary overflow-hidden">
      <div className="px-5 py-4 border-b border-dark-border bg-dark-bg flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white flex items-center tracking-tight">
          <span className="w-2 h-2 bg-primary rounded-full mr-2.5 animate-pulse"></span>
          Chat with Agent
        </h2>
        <button
          onClick={() => void handleClearHistory()}
          className="text-xs font-medium text-dark-text-secondary hover:text-primary transition-colors px-3 py-1.5 rounded-lg hover:bg-dark-bg-lighter border border-transparent hover:border-dark-border"
        >
          Clear
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
              <p className="text-base font-medium text-dark-text-secondary mb-2">Start a conversation with agent</p>
              <p className="text-sm opacity-70">Try saying: &quot;I want to sleep&quot; or &quot;Tell me a story&quot;</p>
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
                <div className="font-semibold text-xs mb-1.5 opacity-90 tracking-wide uppercase">
                  {message.role === 'user' ? 'You' : 'Agent'}
                </div>
                <div className="text-[10px] mb-1.5 opacity-70 font-mono">
                  {formatTimestamp(message.create_time)}
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
                      <div className="text-xs text-primary mb-1.5 italic opacity-90 border-l-2 border-primary pl-2">
                        {message.reason}
                      </div>
                    </div>
                  </div>
                )}
                <div className="text-sm leading-relaxed">{message.message}</div>
              </div>
            </div>
          ))
        )}
        {isChatting && (
          <div className="flex justify-start animate-fade-in">
            <div className="bg-dark-bg-lighter border border-dark-border px-4 py-3 rounded-xl shadow-md rounded-bl-none">
              <div className="font-semibold text-xs mb-1.5 opacity-90 tracking-wide uppercase">Agent</div>
              <div className="flex items-center space-x-1.5">
                <div className="w-2 h-2 bg-primary rounded-full animate-bounce"></div>
                <div className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0.15s' }}></div>
                <div className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0.3s' }}></div>
              </div>
            </div>
          </div>
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
          Try: &quot;I want to sleep&quot; / &quot;I&apos;m tired today&quot; / &quot;Tell me a story&quot;
        </div>
      </form>
    </div>
  );
}

export default ChatInterface;
