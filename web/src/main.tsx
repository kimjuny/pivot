import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom'
import LoginPage from './components/LoginPage'
import AgentList from './components/AgentList'
import AgentDetailPage from './components/AgentDetailPage'
import LLMList from './components/LLMList'
import ToolsPage from './components/ToolsPage'
import SkillsPage from './components/SkillsPage'
import ChannelsPage from './components/ChannelsPage'
import MediaGenerationProvidersPage from './components/MediaGenerationProvidersPage'
import WebSearchProvidersPage from './components/WebSearchProvidersPage'
import ExtensionsPage from './components/ExtensionsPage'
import ExtensionDetailPage from './components/ExtensionDetailPage'
import ChannelLinkPage from './components/ChannelLinkPage'
import StudioDashboardPage from './components/StudioDashboardPage'
import Navigation from './components/Navigation'
import { StorageStatusBanner } from './components/StorageStatusBanner'
import { AuthProvider } from './contexts/AuthContext'
import { getStoredUser, hasPermission, isTokenValid, useAuth } from './contexts/auth-core'
import { ThemeProvider } from '@/components/ui/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import ConsumerEntryPage from '@/consumer/ConsumerEntryPage'
import ConsumerAgentsPage from '@/consumer/ConsumerAgentsPage'
import ConsumerAgentPage from '@/consumer/ConsumerAgentPage'
import { CenteredLoadingIndicator } from '@/components/CenteredLoadingIndicator'
import SessionHistoryPage from '@/studio/operations/SessionHistoryPage'
import SessionDetailPage from '@/studio/operations/SessionDetailPage'
import UsersPage from '@/studio/operations/UsersPage'
import RolesPage from '@/studio/operations/RolesPage'
import GroupsPage from '@/studio/operations/GroupsPage'
import './index.css'

interface PermissionTarget {
  permission: string;
  to: string;
}

const studioTargets: PermissionTarget[] = [
  { permission: 'studio.access', to: '/studio/dashboard' },
  { permission: 'agents.manage', to: '/studio/agents' },
  { permission: 'llms.manage', to: '/studio/assets/models' },
  { permission: 'tools.manage', to: '/studio/assets/tools' },
  { permission: 'skills.manage', to: '/studio/assets/skills' },
  { permission: 'extensions.manage', to: '/studio/assets/extensions' },
  { permission: 'channels.manage', to: '/studio/connections/channels' },
  { permission: 'media_generation.manage', to: '/studio/connections/media-generation' },
  { permission: 'web_search.manage', to: '/studio/connections/web-search' },
  { permission: 'operations.view', to: '/studio/operations/sessions' },
  { permission: 'users.manage', to: '/studio/operations/users' },
  { permission: 'groups.manage', to: '/studio/operations/groups' },
  { permission: 'roles.manage', to: '/studio/operations/roles' },
];

const assetTargets: PermissionTarget[] = [
  { permission: 'llms.manage', to: '/studio/assets/models' },
  { permission: 'tools.manage', to: '/studio/assets/tools' },
  { permission: 'skills.manage', to: '/studio/assets/skills' },
  { permission: 'extensions.manage', to: '/studio/assets/extensions' },
];

const connectionTargets: PermissionTarget[] = [
  { permission: 'channels.manage', to: '/studio/connections/channels' },
  { permission: 'media_generation.manage', to: '/studio/connections/media-generation' },
  { permission: 'web_search.manage', to: '/studio/connections/web-search' },
];

const operationTargets: PermissionTarget[] = [
  { permission: 'operations.view', to: '/studio/operations/sessions' },
  { permission: 'users.manage', to: '/studio/operations/users' },
  { permission: 'groups.manage', to: '/studio/operations/groups' },
  { permission: 'roles.manage', to: '/studio/operations/roles' },
];

function firstAllowedTarget(
  user: ReturnType<typeof getStoredUser>,
  targets: PermissionTarget[],
): string | null {
  return targets.find((target) => hasPermission(user, target.permission))?.to ?? null;
}

/**
 * Protected route wrapper.
 * Redirects to login page if user is not authenticated.
 */
export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  const persistedUser = getStoredUser();
  const activeUser = user ?? persistedUser;

  // Show loading while checking auth state
  if (isLoading) {
    return <CenteredLoadingIndicator className="h-screen" label="Loading" />;
  }

  // Redirect to login if not authenticated
  if (!activeUser || !isTokenValid()) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

export function PermissionRoute({
  permission,
  fallback = '/access-denied',
  children,
}: {
  permission: string;
  fallback?: string;
  children: React.ReactNode;
}) {
  const { user, isLoading } = useAuth();
  const activeUser = user ?? getStoredUser();

  if (isLoading) {
    return <CenteredLoadingIndicator className="h-screen" label="Loading" />;
  }

  if (!activeUser || !isTokenValid()) {
    return <Navigate to="/" replace />;
  }

  if (!hasPermission(activeUser, permission)) {
    return <Navigate to={fallback} replace />;
  }

  return <>{children}</>;
}

export function PermissionRedirect({
  targets,
  fallback = '/access-denied',
}: {
  targets: PermissionTarget[];
  fallback?: string;
}) {
  const { user, isLoading } = useAuth();
  const activeUser = user ?? getStoredUser();

  if (isLoading) {
    return <CenteredLoadingIndicator className="h-screen" label="Loading" />;
  }

  if (!activeUser || !isTokenValid()) {
    return <Navigate to="/" replace />;
  }

  return <Navigate to={firstAllowedTarget(activeUser, targets) ?? fallback} replace />;
}

export function AccessDeniedPage() {
  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-background text-foreground">
        <Navigation />
        <main className="mx-auto flex min-h-[calc(100vh-48px)] max-w-xl flex-col items-center justify-center px-6 text-center">
          <h1 className="text-2xl font-semibold">Access unavailable</h1>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            Your account is active, but this role does not include an available Pivot surface yet.
          </p>
        </main>
      </div>
    </ProtectedRoute>
  );
}

/**
 * Layout wrapper with Navigation for authenticated pages.
 */
export function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-background text-foreground">
        <Navigation />
        <StorageStatusBanner />
        {children}
      </div>
    </ProtectedRoute>
  );
}

/**
 * Agent List Page with layout.
 */
export function AgentListPage() {
  return (
    <AuthenticatedLayout>
      <AgentList />
    </AuthenticatedLayout>
  );
}

/**
 * LLM List Page with layout.
 */
export function LLMListPage() {
  return (
    <AuthenticatedLayout>
      <LLMList />
    </AuthenticatedLayout>
  );
}

/**
 * Tools Page with layout.
 */
export function ToolsListPage() {
  return (
    <AuthenticatedLayout>
      <ToolsPage />
    </AuthenticatedLayout>
  );
}

/**
 * Skills Page with layout.
 */
export function SkillsListPage() {
  return (
    <AuthenticatedLayout>
      <SkillsPage />
    </AuthenticatedLayout>
  );
}

/**
 * Extensions Page with layout.
 */
export function ExtensionsListPage() {
  return (
    <AuthenticatedLayout>
      <ExtensionsPage />
    </AuthenticatedLayout>
  );
}

/**
 * Image-generation providers page with layout.
 */
export function MediaGenerationProvidersListPage() {
  return (
    <AuthenticatedLayout>
      <MediaGenerationProvidersPage />
    </AuthenticatedLayout>
  );
}

/**
 * Extension detail page with layout.
 */
export function ExtensionDetailRoute() {
  return (
    <AuthenticatedLayout>
      <ExtensionDetailPage />
    </AuthenticatedLayout>
  );
}

/**
 * Channels Page with layout.
 */
export function ChannelsListPage() {
  return (
    <AuthenticatedLayout>
      <ChannelsPage />
    </AuthenticatedLayout>
  );
}

/**
 * Web-search providers page with layout.
 */
export function WebSearchProvidersListPage() {
  return (
    <AuthenticatedLayout>
      <WebSearchProvidersPage />
    </AuthenticatedLayout>
  );
}

/**
 * Studio dashboard page with layout.
 */
export function StudioDashboardRoute() {
  return (
    <AuthenticatedLayout>
      <StudioDashboardPage />
    </AuthenticatedLayout>
  );
}

/**
 * Consumer layout wrapper for end-user-facing routes.
 */
export function ConsumerRouteLayout() {
  return (
    <PermissionRoute permission="client.access" fallback="/studio">
      <Outlet />
    </PermissionRoute>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider defaultTheme="dark" storageKey="pivot-ui-theme">
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Public route - Login page */}
            <Route path="/" element={<LoginPage />} />
            <Route path="/access-denied" element={<AccessDeniedPage />} />

            {/* Protected routes */}
            <Route path="/app" element={<ConsumerRouteLayout />}>
              <Route index element={<ConsumerEntryPage />} />
              <Route path="agents" element={<ConsumerAgentsPage />} />
              <Route path="agents/:agentId" element={<ConsumerAgentPage />} />
            </Route>

            <Route path="/studio" element={<PermissionRedirect targets={studioTargets} />} />
            <Route path="/studio/dashboard" element={<PermissionRoute permission="studio.access"><StudioDashboardRoute /></PermissionRoute>} />
            <Route path="/studio/agents" element={<PermissionRoute permission="agents.manage"><AgentListPage /></PermissionRoute>} />
            <Route path="/studio/agents/:agentId" element={<PermissionRoute permission="agents.manage"><AgentDetailPage /></PermissionRoute>} />
            <Route path="/studio/assets" element={<PermissionRedirect targets={assetTargets} />} />
            <Route path="/studio/assets/models" element={<PermissionRoute permission="llms.manage"><LLMListPage /></PermissionRoute>} />
            <Route path="/studio/assets/tools" element={<PermissionRoute permission="tools.manage"><ToolsListPage /></PermissionRoute>} />
            <Route path="/studio/assets/skills" element={<PermissionRoute permission="skills.manage"><SkillsListPage /></PermissionRoute>} />
            <Route path="/studio/assets/extensions" element={<PermissionRoute permission="extensions.manage"><ExtensionsListPage /></PermissionRoute>} />
            <Route path="/studio/assets/extensions/:scope/:name" element={<PermissionRoute permission="extensions.manage"><ExtensionDetailRoute /></PermissionRoute>} />
            <Route path="/studio/connections" element={<PermissionRedirect targets={connectionTargets} />} />
            <Route path="/studio/connections/channels" element={<PermissionRoute permission="channels.manage"><ChannelsListPage /></PermissionRoute>} />
            <Route path="/studio/connections/media-generation" element={<PermissionRoute permission="media_generation.manage"><MediaGenerationProvidersListPage /></PermissionRoute>} />
            <Route path="/studio/connections/web-search" element={<PermissionRoute permission="web_search.manage"><WebSearchProvidersListPage /></PermissionRoute>} />
            <Route path="/studio/operations" element={<PermissionRedirect targets={operationTargets} />} />
            <Route path="/studio/operations/sessions" element={<PermissionRoute permission="operations.view"><AuthenticatedLayout><SessionHistoryPage /></AuthenticatedLayout></PermissionRoute>} />
            <Route path="/studio/operations/sessions/:sessionId" element={<PermissionRoute permission="operations.view"><AuthenticatedLayout><SessionDetailPage /></AuthenticatedLayout></PermissionRoute>} />
            <Route path="/studio/operations/users" element={<PermissionRoute permission="users.manage"><AuthenticatedLayout><UsersPage /></AuthenticatedLayout></PermissionRoute>} />
            <Route path="/studio/operations/groups" element={<PermissionRoute permission="groups.manage"><AuthenticatedLayout><GroupsPage /></AuthenticatedLayout></PermissionRoute>} />
            <Route path="/studio/operations/roles" element={<PermissionRoute permission="roles.manage"><AuthenticatedLayout><RolesPage /></AuthenticatedLayout></PermissionRoute>} />

            <Route path="/agents" element={<PermissionRoute permission="agents.manage"><AgentListPage /></PermissionRoute>} />
            <Route path="/agent/:agentId" element={<PermissionRoute permission="agents.manage"><AgentDetailPage /></PermissionRoute>} />
            <Route path="/llms" element={<PermissionRoute permission="llms.manage"><LLMListPage /></PermissionRoute>} />
            <Route path="/tools" element={<PermissionRoute permission="tools.manage"><ToolsListPage /></PermissionRoute>} />
            <Route path="/skills" element={<PermissionRoute permission="skills.manage"><SkillsListPage /></PermissionRoute>} />
            <Route path="/extensions" element={<PermissionRoute permission="extensions.manage"><ExtensionsListPage /></PermissionRoute>} />
            <Route path="/extensions/:scope/:name" element={<PermissionRoute permission="extensions.manage"><ExtensionDetailRoute /></PermissionRoute>} />
            <Route path="/channels" element={<PermissionRoute permission="channels.manage"><ChannelsListPage /></PermissionRoute>} />
            <Route path="/media-providers" element={<PermissionRoute permission="media_generation.manage"><MediaGenerationProvidersListPage /></PermissionRoute>} />
            <Route path="/web-search-providers" element={<PermissionRoute permission="web_search.manage"><WebSearchProvidersListPage /></PermissionRoute>} />
            <Route path="/channel-link/:token" element={<ChannelLinkPage />} />

            {/* Catch-all redirect */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)
