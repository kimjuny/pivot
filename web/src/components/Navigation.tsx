import { Github, Inbox, ChevronDown, Bot, ArrowLeft, LogOut, User } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { getAgents } from '../utils/api';
import type { Agent } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { ModeToggle } from '@/components/ui/mode-toggle';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';

/**
 * Navigation bar component.
 * Displays app logo, center navigation menu, and user actions with proper accessibility support.
 * When viewing an agent detail page, shows agent selector dropdown.
 * Shows user menu with logout option when authenticated.
 */
function Navigation() {
  const navigate = useNavigate();
  const { agentId } = useParams<{ agentId?: string }>();
  const { user, logout } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isAgentsButtonHovered, setIsAgentsButtonHovered] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<Agent | null>(null);

  /**
   * Handle logout click.
   * Logs out the user and redirects to login page.
   */
  const handleLogout = () => {
    logout();
    toast.success('Signed out successfully');
    navigate('/', { replace: true });
  };

  /**
   * Handle sign in click.
   * Navigates to login page.
   */
  const handleSignIn = () => {
    navigate('/');
  };

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

  const handleAgentSelect = (agent: Agent) => {
    navigate(`/agent/${agent.id}`);
  };

  const handleNavigateToAgents = () => {
    navigate('/agents');
  };

  return (
    <nav className="sticky top-0 z-50 bg-background border-b border-border">
      <div className="flex items-center justify-between h-12 px-4 sm:px-6 lg:px-8">
        {/* Left: Logo */}
        <div className="flex items-center">
          <button
            onClick={handleNavigateToAgents}
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background rounded"
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
          <div className="relative flex items-center gap-1">
            {/* Icon + Agents: Always navigates to agents list */}
            <Button
              variant="ghost"
              size="sm"
              onClick={handleNavigateToAgents}
              onMouseEnter={() => setIsAgentsButtonHovered(true)}
              onMouseLeave={() => setIsAgentsButtonHovered(false)}
              className="flex items-center gap-1.5"
              aria-label="Go to Agents list"
            >
              {/* Overlapping icons with fade + rotation transition */}
              <div className="relative w-4 h-4">
                {/* Bot icon - fades out and rotates on hover */}
                <Bot
                  className={`absolute inset-0 w-4 h-4 transition-all duration-150 ${agentId && isAgentsButtonHovered
                    ? 'opacity-0 rotate-180'
                    : 'opacity-100 rotate-0'
                    }`}
                  aria-hidden="true"
                />
                {/* ArrowLeft icon - fades in from opposite rotation on hover */}
                {agentId && (
                  <ArrowLeft
                    className={`absolute inset-0 w-4 h-4 transition-all duration-150 ${isAgentsButtonHovered
                      ? 'opacity-100 rotate-0'
                      : 'opacity-0 rotate-180'
                      }`}
                    aria-hidden="true"
                  />
                )}
              </div>
              <span>Agents</span>
            </Button>

            {/* Separator and agent name dropdown when on agent detail page */}
            {agentId && currentAgent && (
              <>
                <span className="text-muted-foreground text-sm select-none" aria-hidden="true">/</span>

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="flex items-center gap-1.5"
                      aria-label={`Current agent: ${currentAgent.name}. Click to switch agent`}
                    >
                      <span>{currentAgent.name}</span>
                      <ChevronDown className="w-4 h-4" aria-hidden="true" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-48 max-h-96 overflow-y-auto p-0.5">
                    {agents.map((agent) => (
                      <DropdownMenuItem
                        key={agent.id}
                        onClick={() => handleAgentSelect(agent)}
                        className={`flex items-center gap-2 py-1.5 my-0.5 min-h-[44px] ${agent.id === parseInt(agentId) ? 'bg-accent' : ''}`}
                      >
                        <div className="w-6 h-6 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                          <Bot className="w-3.5 h-3.5 text-primary" aria-hidden="true" />
                        </div>
                        <div className="flex-1 min-w-0 flex flex-col justify-center">
                          <div className="text-xs font-medium truncate">
                            {agent.name}
                          </div>
                          {agent.description && (
                            <div className="text-[11px] text-muted-foreground truncate leading-tight">
                              {agent.description}
                            </div>
                          )}
                        </div>
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            )}
          </div>

          <Separator orientation="vertical" className="h-4 mx-2" />

          {/* Future navigation items - disabled for now */}
          <Button
            variant="ghost"
            size="sm"
            disabled
            className="opacity-50"
            aria-label="Skills (coming soon)"
          >
            Skills
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled
            className="opacity-50"
            aria-label="MCP (coming soon)"
          >
            MCP
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/tools')}
            aria-label="Tools"
          >
            Tools
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate('/llms')}
            aria-label="LLMs"
          >
            LLMs
          </Button>
        </div>

        {/* Right: User Actions */}
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            asChild
          >
            <a
              href="https://github.com/kimjuny/pivot"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5"
              aria-label="View on GitHub"
            >
              <Github className="w-4 h-4" aria-hidden="true" />
            </a>
          </Button>

          <Button
            variant="ghost"
            size="icon"
            aria-label="View notifications"
          >
            <Inbox className="w-4 h-4" aria-hidden="true" />
          </Button>

          <ModeToggle />

          {user ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="rounded-full"
                  aria-label={`User menu: ${user.username}`}
                >
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-primary">
                    <span className="text-sm font-medium">
                      {user.username.charAt(0).toUpperCase()}
                    </span>
                  </div>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <div className="px-2 py-1.5 text-sm font-medium">
                  {user.username}
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onClick={handleLogout}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <LogOut className="w-4 h-4" />
                  <span>Sign out</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleSignIn}
              className="flex items-center gap-1.5"
              aria-label="Sign in"
            >
              <User className="w-4 h-4" aria-hidden="true" />
              <span>Sign in</span>
            </Button>
          )}
        </div>
      </div>
    </nav>
  );
}

export default Navigation;
