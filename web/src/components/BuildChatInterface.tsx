import { useState, useRef, useEffect, FormEvent } from 'react';
import { useBuildChatStore } from '../store/buildChatStore';
import { formatTimestamp } from '../utils/timestamp';
import type { BuildHistory } from '../types';

/**
 * Props for BuildChatInterface component.
 */
interface BuildChatInterfaceProps {
  /** Unique identifier of the agent */
  agentId: number;
}

/**
 * Build Chat interface component for agent editing assistance.
 * Displays conversation with Build Agent and allows applying/discard suggested changes.
 */
function BuildChatInterface({ agentId }: BuildChatInterfaceProps) {
  const { buildChatHistory, chatWithBuildAgent, isChatting, error, clearError, applyBuildChanges, discardBuildChanges, pendingBuildChanges } = useBuildChatStore();
  const [inputMessage, setInputMessage] = useState<string>('');
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
   * Auto-scroll to bottom when chat history updates.
   * Ensures user sees latest messages.
   */
  useEffect(() => {
    scrollToBottom();
  }, [buildChatHistory]);

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
      await chatWithBuildAgent(agentId, inputMessage);
      setInputMessage('');
    } catch (err) {
      void err;
    }
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
          Build Assistant
        </h2>
        <button
          onClick={() => { void discardBuildChanges(); }}
          className="text-xs font-medium text-dark-text-secondary hover:text-primary transition-colors px-3 py-1.5 rounded-lg hover:bg-dark-bg-lighter border border-transparent hover:border-dark-border"
        >
          Clear Changes
        </button>
      </div>
      
      <div className="flex-1 overflow-y-auto p-5 space-y-4 bg-dark-bg">
        {buildChatHistory.length === 0 ? (
          <div className="text-center text-dark-text-muted mt-12 animate-fade-in">
            <div className="mb-4">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-dark-border-light flex items-center justify-center">
                <svg className="w-8 h-8 text-dark-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                </svg>
              </div>
              <p className="text-base font-medium text-dark-text-secondary mb-2">Describe your agent changes</p>
              <p className="text-sm opacity-70">Try saying: &quot;Add a sleep scene with 3 steps&quot; or &quot;Add a decision node after greeting&quot;</p>
            </div>
          </div>
        ) : (
          buildChatHistory.map((message: BuildHistory, index: number) => (
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
                  {message.role === 'user' ? 'You' : 'Build Assistant'}
                </div>
                <div className="text-[10px] mb-1.5 opacity-70 font-mono">
                  {formatTimestamp(message.created_at)}
                </div>
                {message.role === 'assistant' && message.agent_snapshot && (
                  <div 
                    className="cursor-pointer mb-2"
                    onClick={() => toggleThinking(index)}
                  >
                    <div className="text-xs text-primary mb-1.5 italic opacity-90 border-l-2 border-primary pl-2 flex items-center justify-between">
                      <span className="font-medium">Proposed Changes:</span>
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
                        Graph structure updated based on your request
                      </div>
                    </div>
                  </div>
                )}
                <div className="text-sm leading-relaxed">{message.content}</div>
              </div>
            </div>
          ))
        )}
        {isChatting && (
          <div className="flex justify-start animate-fade-in">
            <div className="bg-dark-bg-lighter border border-dark-border px-4 py-3 rounded-xl shadow-md rounded-bl-none">
              <div className="font-semibold text-xs mb-1.5 opacity-90 tracking-wide uppercase">Build Assistant</div>
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

      {pendingBuildChanges && (
        <div className="mx-5 mb-3 p-3 bg-primary/10 border border-primary/30 text-primary text-sm rounded-lg animate-fade-in">
          <div className="flex justify-between items-center mb-2">
            <span className="font-medium">Build Agent has suggested changes</span>
            <button onClick={discardBuildChanges} className="text-xs hover:text-primary/80">&times;</button>
          </div>
          <div className="flex space-x-2">
            <button
              onClick={() => { void applyBuildChanges(); }}
              className="flex-1 px-3 py-1.5 bg-primary text-white rounded-lg hover:bg-primary/90 text-xs font-medium"
            >
              Apply
            </button>
            <button
              onClick={discardBuildChanges}
              className="flex-1 px-3 py-1.5 bg-dark-bg-lighter border border-dark-border text-dark-text-secondary rounded-lg hover:bg-dark-bg-lighter hover:border-dark-border text-xs font-medium"
            >
              Discard
            </button>
          </div>
        </div>
      )}
      
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
            placeholder="Describe your changes..."
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
          Try: &quot;Add a sleep scene&quot; / &quot;Add a decision node&quot; / &quot;Modify the greeting flow&quot;
        </div>
      </form>
    </div>
  );
}

export default BuildChatInterface;
