import { Github, Inbox, ChevronDown, Bot } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useState, useEffect, useRef } from 'react';
import { getAgents } from '../utils/api';
import type { Agent } from '../types';

/**
 * Navigation bar component.
 * Displays app logo, center navigation menu, and user actions with proper accessibility support.
 * When viewing an agent detail page, shows agent selector dropdown.
 */
function Navigation() {
  const navigate = useNavigate();
  const { agentId } = useParams<{ agentId?: string }>();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [currentAgent, setCurrentAgent] = useState<Agent | null>(null);
  const [isAgentDropdownOpen, setIsAgentDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  /**
   * Fetch all agents for the dropdown selector.
   * Only runs when viewing an agent detail page.
   */
  useEffect(() => {
    if (agentId) {
      const fetchAgents = async () => {
        try {
          const allAgents = await getAgents();
          setAgents(allAgents);
          const current = allAgents.find(a => a.id === parseInt(agentId));
          setCurrentAgent(current || null);
        } catch (error) {
          console.error('Failed to fetch agents:', error);
        }
      };
      void fetchAgents();
    } else {
      setCurrentAgent(null);
      setAgents([]);
    }
  }, [agentId]);

  /**
   * Close dropdown when clicking outside.
   */
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsAgentDropdownOpen(false);
      }
    };

    if (isAgentDropdownOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [isAgentDropdownOpen]);

  /**
   * Handle keyboard navigation for interactive elements.
   * Ensures buttons respond to Enter and Space keys.
   */
  const handleKeyDown = (e: React.KeyboardEvent, action: () => void) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      action();
    }
  };

  const handleInboxClick = () => {
    // TODO: Implement inbox functionality
  };

  const handleUserMenuClick = () => {
    // TODO: Implement user menu functionality
  };

  const handleAgentSelect = (agent: Agent) => {
    navigate(`/agent/${agent.id}`);
    setIsAgentDropdownOpen(false);
  };

  const handleNavigateToAgents = () => {
    navigate('/');
  };

  return (
    <nav className="sticky top-0 z-50 bg-dark-bg border-b border-dark-border">
      <div className="flex items-center justify-between h-12 px-4 sm:px-6 lg:px-8">
        {/* Left: Logo */}
        <div className="flex items-center">
          <button
            onClick={handleNavigateToAgents}
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg rounded"
            aria-label="Go to home"
          >
            <img
              src="/pivot.svg"
              alt="Pivot"
              className="h-6 w-6"
            />
          </button>
        </div>

        {/* Center: Navigation Items */}
        <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-1">
          {/* Agents navigation with optional agent selector dropdown */}
          <div className="relative flex items-center" ref={dropdownRef}>
            {/* Icon + Agents: Always navigates to agents list */}
            <button
              onClick={handleNavigateToAgents}
              onKeyDown={(e) => handleKeyDown(e, handleNavigateToAgents)}
              className="nav-hover-effect flex items-center gap-1.5 px-2 py-1 text-sm font-medium text-dark-text-primary rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg"
              aria-label="Go to Agents list"
            >
              <Bot className="w-4 h-4" aria-hidden="true" />
              <span>Agents</span>
            </button>

            {/* Separator: Independent visual divider, not interactive */}
            {agentId && currentAgent && (
              <span className="text-dark-text-secondary text-sm select-none" aria-hidden="true">/</span>
            )}

            {/* Agent name with dropdown trigger: Only shows on agent detail page */}
            {agentId && currentAgent && (
              <div className="relative">
                <button
                  onClick={() => setIsAgentDropdownOpen(!isAgentDropdownOpen)}
                  onKeyDown={(e) => handleKeyDown(e, () => setIsAgentDropdownOpen(!isAgentDropdownOpen))}
                  className="nav-hover-effect flex items-center gap-1.5 px-2 py-1 text-sm font-medium text-dark-text-primary rounded transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg"
                  aria-label={`Current agent: ${currentAgent.name}. Click to switch agent`}
                  aria-expanded={isAgentDropdownOpen}
                  aria-haspopup="listbox"
                >
                  <span>{currentAgent.name}</span>
                  <ChevronDown className={`w-4 h-4 transition-transform ${isAgentDropdownOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
                </button>

                {/* Agent Dropdown: Positioned relative to agent name button */}
                {isAgentDropdownOpen && agents.length > 0 && (
                  <div className="absolute top-full mt-2 left-0 w-64 bg-dark-bg border border-dark-border rounded-lg shadow-lg overflow-hidden">
                    <div className="max-h-96 overflow-y-auto">
                      {agents.map((agent) => (
                        <button
                          key={agent.id}
                          onClick={() => handleAgentSelect(agent)}
                          className={`w-full flex items-center space-x-3 px-4 py-3 text-left hover:bg-dark-border-light transition-colors ${agent.id === parseInt(agentId) ? 'bg-dark-border-light' : ''}`}
                          aria-label={`Switch to agent: ${agent.name}`}
                        >
                          <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                            <Bot className="w-4 h-4 text-primary" aria-hidden="true" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium text-dark-text-primary truncate">
                              {agent.name}
                            </div>
                            {agent.description && (
                              <div className="text-xs text-dark-text-secondary truncate">
                                {agent.description}
                              </div>
                            )}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Future navigation items - disabled for now */}
          <button
            disabled
            className="px-2 py-1 text-sm font-medium text-dark-text-secondary cursor-not-allowed opacity-50 rounded"
            aria-label="Skills (coming soon)"
          >
            Skills
          </button>
          <button
            disabled
            className="px-2 py-1 text-sm font-medium text-dark-text-secondary cursor-not-allowed opacity-50 rounded"
            aria-label="MCP (coming soon)"
          >
            MCP
          </button>
          <button
            disabled
            className="px-2 py-1 text-sm font-medium text-dark-text-secondary cursor-not-allowed opacity-50 rounded"
            aria-label="Tools (coming soon)"
          >
            Tools
          </button>
          <button
            disabled
            className="px-2 py-1 text-sm font-medium text-dark-text-secondary cursor-not-allowed opacity-50 rounded"
            aria-label="Knowledge (coming soon)"
          >
            Knowledge
          </button>
        </div>

        {/* Right: User Actions */}
        <div className="flex items-center gap-2">
          <a
            href="https://github.com"
            target="_blank"
            rel="noopener noreferrer"
            className="nav-hover-effect flex items-center gap-1.5 text-dark-text-secondary hover:text-dark-text-primary transition-colors px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg"
            aria-label="View on GitHub, 23.4K stars"
          >
            <Github className="w-4 h-4" aria-hidden="true" />
            <span className="text-sm font-medium">23.4K</span>
          </a>

          <button
            onClick={handleInboxClick}
            onKeyDown={(e) => handleKeyDown(e, handleInboxClick)}
            className="nav-hover-effect flex items-center text-dark-text-secondary hover:text-dark-text-primary transition-colors px-2 py-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg"
            aria-label="View notifications"
          >
            <Inbox className="w-4 h-4" aria-hidden="true" />
          </button>

          <button
            onClick={handleUserMenuClick}
            onKeyDown={(e) => handleKeyDown(e, handleUserMenuClick)}
            className="flex items-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg rounded-full"
            aria-label="User menu"
          >
            <div className="w-8 h-8 rounded-full bg-dark-border-light flex items-center justify-center text-dark-text-secondary hover:bg-dark-border transition-colors">
              <span className="text-sm font-medium">U</span>
            </div>
          </button>
        </div>
      </div>
    </nav>
  );
}

export default Navigation;

