import {
  Github,
  Inbox,
  ChevronDown,
  Bot,
  ArrowLeft,
  Layers,
  Link2,
  ListTodo,
  LogOut,
  Presentation,
  Radio,
  Server,
  User,
  Wrench,
  Zap,
  FileText,
  Globe,
} from "@/lib/lucide";
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useState, useEffect, type ComponentType, type SVGProps } from 'react';
import { getAgents } from '../utils/api';
import type { Agent } from '../types';
import { useAuth } from '../contexts/auth-core';
import { LLMBrandAvatar } from '@/components/LLMBrandAvatar';
import { Button } from '@/components/ui/button';
import { ModeToggle } from '@/components/ui/mode-toggle';
import {
  NavigationMenu,
  NavigationMenuContent,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  NavigationMenuTrigger,
} from '@/components/ui/navigation-menu';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';

interface StudioMenuLinkItem {
  title: string;
  description: string;
  to?: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  disabled?: boolean;
}

function TopLevelSeparator() {
  return (
    <li aria-hidden="true" className="px-1 text-sm text-muted-foreground/70">
      |
    </li>
  );
}

function topLevelNavigationLinkClassName(isActive: boolean) {
  return cn(
    "group inline-flex h-8 w-max items-center justify-center rounded-md bg-background px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground focus:outline-none",
    isActive && "bg-accent/50 text-accent-foreground"
  );
}

function NavigationMenuListItem({
  item,
}: {
  item: StudioMenuLinkItem;
}) {
  const Icon = item.icon;

  if (!item.to || item.disabled) {
    return (
      <div className="flex min-w-[220px] cursor-not-allowed flex-col gap-0.5 rounded-md px-2.5 py-2 text-xs opacity-55">
        <div className="flex items-center gap-1.5 font-medium text-foreground">
          <Icon className="h-3.5 w-3.5" />
          <span>{item.title}</span>
        </div>
        <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">
          {item.description}
        </p>
      </div>
    );
  }

  return (
    <NavigationMenuLink asChild>
      <Link
        to={item.to}
        className="flex min-w-[220px] flex-col gap-0.5 rounded-md px-2.5 py-2 text-xs outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground"
      >
        <div className="flex items-center gap-1.5 font-medium leading-none">
          <Icon className="h-3.5 w-3.5" />
          <span>{item.title}</span>
        </div>
        <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">
          {item.description}
        </p>
      </Link>
    </NavigationMenuLink>
  );
}

function AgentNavigationMenuItem({
  agent,
}: {
  agent: Agent;
}) {
  return (
    <NavigationMenuLink asChild>
      <Link
        to={`/studio/agents/${agent.id}`}
        className="flex min-w-[220px] items-center gap-2 rounded-md px-2.5 py-2 text-xs outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground"
      >
        <LLMBrandAvatar
          model={agent.model_name}
          containerClassName="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-primary/10"
          imageClassName="h-3 w-3"
          fallback={<Bot className="h-3 w-3 text-primary" aria-hidden="true" />}
        />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium leading-tight text-foreground">
            {agent.name}
          </div>
          <div className="truncate pt-0.5 text-[11px] leading-tight text-muted-foreground">
            {agent.model_name || 'No primary model'}
          </div>
        </div>
      </Link>
    </NavigationMenuLink>
  );
}

/**
 * Navigation bar component.
 * Displays app logo, center navigation menu, and user actions with proper accessibility support.
 * When viewing an agent detail page, shows agent selector dropdown.
 * Shows user menu with logout option when authenticated.
 */
function Navigation() {
  const navigate = useNavigate();
  const location = useLocation();
  const { agentId } = useParams<{ agentId?: string }>();
  const { user, logout } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [isAgentsButtonHovered, setIsAgentsButtonHovered] = useState(false);
  const [currentAgent, setCurrentAgent] = useState<Agent | null>(null);

  const currentPath = location.pathname;
  const isDashboardActive = currentPath === '/studio' || currentPath === '/studio/dashboard';
  const isAgentsActive = currentPath.startsWith('/studio/agents') || currentPath.startsWith('/agent/') || currentPath === '/agents';
  const isAssetsActive = currentPath.startsWith('/studio/assets') || currentPath === '/llms' || currentPath === '/tools' || currentPath === '/skills' || currentPath === '/extensions';
  const isConnectionsActive = currentPath.startsWith('/studio/connections')
    || currentPath === '/channels'
    || currentPath === '/media-providers'
    || currentPath === '/web-search-providers';
  const isOperationsActive = currentPath.startsWith('/studio/operations');

  const assetsMenuItems: StudioMenuLinkItem[] = [
    {
      title: 'Models',
      description: 'Manage model endpoints, protocols, context limits, and thinking policies.',
      to: '/studio/assets/models',
      icon: Server,
    },
    {
      title: 'Tools',
      description: 'Manage executable capabilities that agents can call during runtime.',
      to: '/studio/assets/tools',
      icon: Wrench,
    },
    {
      title: 'Skills',
      description: 'Manage reusable guidance packs that can be mounted into agents.',
      to: '/studio/assets/skills',
      icon: Zap,
    },
    {
      title: 'Extensions',
      description: 'Import package folders, inspect installed versions, and manage package lifecycle state.',
      to: '/studio/assets/extensions',
      icon: FileText,
    },
    {
      title: 'MCPs',
      description: 'Future shared connector inventory for structured external capability servers.',
      icon: Radio,
      disabled: true,
    },
    {
      title: 'Prompt Kits',
      description: 'Future shared prompt and policy bundles for consistent agent releases.',
      icon: FileText,
      disabled: true,
    },
  ];

  const connectionsMenuItems: StudioMenuLinkItem[] = [
    {
      title: 'Channels',
      description: 'Review installed delivery surfaces such as built-in and extension-backed channels.',
      to: '/studio/connections/channels',
      icon: Radio,
    },
    {
      title: 'Media Providers',
      description: 'Review installed media-generation providers before binding them to agents.',
      to: '/studio/connections/media-generation',
      icon: Layers,
    },
    {
      title: 'Web Search Providers',
      description: 'Review installed abstract search providers before binding them to agents.',
      to: '/studio/connections/web-search',
      icon: Globe,
    },
    {
      title: 'Desktop Connectors',
      description: 'Future bridge for local-device and desktop-hosted capabilities.',
      icon: Bot,
      disabled: true,
    },
    {
      title: 'Internal APIs',
      description: 'Future inventory for organization-specific APIs and auth surfaces.',
      icon: Server,
      disabled: true,
    },
  ];

  const operationsMenuItems: StudioMenuLinkItem[] = [
    {
      title: 'Session Activity',
      description: 'Inspect user sessions, execution traces, and long-running task behavior.',
      icon: Bot,
      to: '/studio/operations/sessions',
    },
    {
      title: 'Tool and Sandbox Logs',
      description: 'Review failures, timeouts, and execution health across the workspace.',
      icon: Wrench,
      disabled: true,
    },
    {
      title: 'Release Audit',
      description: 'Trace publish events, rollout changes, and rollback history over time.',
      icon: FileText,
      disabled: true,
    },
    {
      title: 'Usage and Cost',
      description: 'Track traffic, token usage, and model cost as Studio matures.',
      icon: Presentation,
      disabled: true,
    },
  ];

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
   * Navigate to the authenticated Studio home.
   * Why: the new top-level information architecture starts from Dashboard
   * instead of treating the agent list as the only home screen.
   */
  const handleNavigateToStudio = () => {
    if (user) {
      navigate('/studio/dashboard');
      return;
    }
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
    navigate(`/studio/agents/${agent.id}`);
  };

  const handleNavigateToAgents = () => {
    navigate('/studio/agents');
  };

  const handleNavigateToDashboard = () => {
    navigate('/studio/dashboard');
  };

  return (
    <nav className="sticky top-0 z-50 bg-background border-b border-border">
      <div className="flex items-center justify-between h-12 px-4 sm:px-6 lg:px-8">
        {/* Left: Logo */}
        <div className="flex items-center">
          <button
            onClick={handleNavigateToStudio}
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
        <div className="absolute left-1/2 -translate-x-1/2">
          <NavigationMenu viewport={false}>
            <NavigationMenuList className="gap-0">
              <NavigationMenuItem>
                <NavigationMenuLink asChild>
                  <Link
                    to="/studio/dashboard"
                    className={cn(topLevelNavigationLinkClassName(isDashboardActive), "gap-1.5")}
                  >
                    <Presentation className="h-3.5 w-3.5" />
                    <span>Dashboard</span>
                  </Link>
                </NavigationMenuLink>
              </NavigationMenuItem>

              <TopLevelSeparator />

              <NavigationMenuItem className="flex items-center gap-1">
                <NavigationMenuLink asChild>
                  <Link
                    to="/studio/agents"
                    className={cn(topLevelNavigationLinkClassName(isAgentsActive), "gap-1.5")}
                    onMouseEnter={() => setIsAgentsButtonHovered(true)}
                    onMouseLeave={() => setIsAgentsButtonHovered(false)}
                  >
                    <div className="relative h-3.5 w-3.5">
                      <Bot
                        className={cn(
                          "absolute inset-0 h-3.5 w-3.5 transition-all duration-150",
                          agentId && isAgentsButtonHovered
                            ? "rotate-180 opacity-0"
                            : "rotate-0 opacity-100"
                        )}
                        aria-hidden="true"
                      />
                      {agentId && (
                        <ArrowLeft
                          className={cn(
                            "absolute inset-0 h-3.5 w-3.5 transition-all duration-150",
                            isAgentsButtonHovered
                              ? "rotate-0 opacity-100"
                              : "rotate-180 opacity-0"
                          )}
                          aria-hidden="true"
                        />
                      )}
                    </div>
                    <span>Agents</span>
                  </Link>
                </NavigationMenuLink>
              </NavigationMenuItem>

              {agentId && currentAgent && (
                <>
                  <li
                    aria-hidden="true"
                    className="px-1 text-xs text-muted-foreground/70 select-none"
                  >
                    /
                  </li>
                  <NavigationMenuItem className="relative">
                  <NavigationMenuTrigger className="h-8 gap-1.5 px-2.5 py-1.5 text-xs">
                      <LLMBrandAvatar
                        model={currentAgent.model_name}
                        containerClassName="flex h-4 w-4 shrink-0 items-center justify-center rounded-sm bg-primary/10"
                        imageClassName="h-2.5 w-2.5"
                        fallback={<Bot className="h-2.5 w-2.5 text-primary" aria-hidden="true" />}
                      />
                      <span className="max-w-[140px] truncate leading-tight">
                        {currentAgent.name}
                      </span>
                    </NavigationMenuTrigger>
                    <NavigationMenuContent>
                      <ul className="flex w-[260px] flex-col gap-1 rounded-md border bg-popover p-2 text-popover-foreground shadow-md">
                        {agents.map((agent) => (
                          <li key={agent.id}>
                            <AgentNavigationMenuItem agent={agent} />
                          </li>
                        ))}
                      </ul>
                    </NavigationMenuContent>
                  </NavigationMenuItem>
                </>
              )}

              <TopLevelSeparator />

              <NavigationMenuItem className="relative">
                <NavigationMenuTrigger
                  className={cn(
                    "h-8 gap-1.5 px-3 py-1.5 text-xs",
                    isAssetsActive && "bg-accent/50 text-accent-foreground"
                  )}
                >
                  <Layers className="h-3.5 w-3.5" />
                  <span>Assets</span>
                </NavigationMenuTrigger>
                <NavigationMenuContent>
                  <ul className="flex w-[280px] flex-col gap-1 rounded-md border bg-popover p-2 text-popover-foreground shadow-md">
                    {assetsMenuItems.map((item) => (
                      <li key={item.title}>
                        <NavigationMenuListItem item={item} />
                      </li>
                    ))}
                  </ul>
                </NavigationMenuContent>
              </NavigationMenuItem>

              <TopLevelSeparator />

              <NavigationMenuItem className="relative">
                <NavigationMenuTrigger
                  className={cn(
                    "h-8 gap-1.5 px-3 py-1.5 text-xs",
                    isConnectionsActive && "bg-accent/50 text-accent-foreground"
                  )}
                >
                  <Link2 className="h-3.5 w-3.5" />
                  <span>Connections</span>
                </NavigationMenuTrigger>
                <NavigationMenuContent>
                  <ul className="flex w-[280px] flex-col gap-1 rounded-md border bg-popover p-2 text-popover-foreground shadow-md">
                    {connectionsMenuItems.map((item) => (
                      <li key={item.title}>
                        <NavigationMenuListItem item={item} />
                      </li>
                    ))}
                  </ul>
                </NavigationMenuContent>
              </NavigationMenuItem>

              <TopLevelSeparator />

              <NavigationMenuItem className="relative">
                <NavigationMenuTrigger
                  className={cn(
                    "h-8 gap-1.5 px-3 py-1.5 text-xs",
                    isOperationsActive && "bg-accent/50 text-accent-foreground"
                  )}
                >
                  <ListTodo className="h-3.5 w-3.5" />
                  <span>Operations</span>
                </NavigationMenuTrigger>
                <NavigationMenuContent>
                  <ul className="flex w-[280px] flex-col gap-1 rounded-md border bg-popover p-2 text-popover-foreground shadow-md">
                    {operationsMenuItems.map((item) => (
                      <li key={item.title}>
                        <NavigationMenuListItem item={item} />
                      </li>
                    ))}
                  </ul>
                </NavigationMenuContent>
              </NavigationMenuItem>
            </NavigationMenuList>
          </NavigationMenu>
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
