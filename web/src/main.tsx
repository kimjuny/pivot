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
import { getStoredUser, isTokenValid, useAuth } from './contexts/auth-core'
import { ThemeProvider } from '@/components/ui/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import ConsumerEntryPage from '@/consumer/ConsumerEntryPage'
import ConsumerAgentsPage from '@/consumer/ConsumerAgentsPage'
import ConsumerAgentPage from '@/consumer/ConsumerAgentPage'
import { CenteredLoadingIndicator } from '@/components/CenteredLoadingIndicator'
import SessionHistoryPage from '@/studio/operations/SessionHistoryPage'
import SessionDetailPage from '@/studio/operations/SessionDetailPage'
import './index.css'

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
    <ProtectedRoute>
      <Outlet />
    </ProtectedRoute>
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

            {/* Protected routes */}
            <Route path="/app" element={<ConsumerRouteLayout />}>
              <Route index element={<ConsumerEntryPage />} />
              <Route path="agents" element={<ConsumerAgentsPage />} />
              <Route path="agents/:agentId" element={<ConsumerAgentPage />} />
            </Route>

            <Route path="/studio" element={<Navigate to="/studio/dashboard" replace />} />
            <Route path="/studio/dashboard" element={<StudioDashboardRoute />} />
            <Route path="/studio/agents" element={<AgentListPage />} />
            <Route path="/studio/agents/:agentId" element={<AgentDetailPage />} />
            <Route path="/studio/assets" element={<Navigate to="/studio/assets/models" replace />} />
            <Route path="/studio/assets/models" element={<LLMListPage />} />
            <Route path="/studio/assets/tools" element={<ToolsListPage />} />
            <Route path="/studio/assets/skills" element={<SkillsListPage />} />
            <Route path="/studio/assets/extensions" element={<ExtensionsListPage />} />
            <Route path="/studio/assets/extensions/:scope/:name" element={<ExtensionDetailRoute />} />
            <Route path="/studio/connections" element={<Navigate to="/studio/connections/channels" replace />} />
            <Route path="/studio/connections/channels" element={<ChannelsListPage />} />
            <Route path="/studio/connections/media-generation" element={<MediaGenerationProvidersListPage />} />
            <Route path="/studio/connections/web-search" element={<WebSearchProvidersListPage />} />
            <Route path="/studio/operations" element={<Navigate to="/studio/operations/sessions" replace />} />
            <Route path="/studio/operations/sessions" element={<AuthenticatedLayout><SessionHistoryPage /></AuthenticatedLayout>} />
            <Route path="/studio/operations/sessions/:sessionId" element={<AuthenticatedLayout><SessionDetailPage /></AuthenticatedLayout>} />

            <Route path="/agents" element={<AgentListPage />} />
            <Route path="/agent/:agentId" element={<AgentDetailPage />} />
            <Route path="/llms" element={<LLMListPage />} />
            <Route path="/tools" element={<ToolsListPage />} />
            <Route path="/skills" element={<SkillsListPage />} />
            <Route path="/extensions" element={<ExtensionsListPage />} />
            <Route path="/extensions/:scope/:name" element={<ExtensionDetailRoute />} />
            <Route path="/channels" element={<ChannelsListPage />} />
            <Route path="/media-providers" element={<MediaGenerationProvidersListPage />} />
            <Route path="/web-search-providers" element={<WebSearchProvidersListPage />} />
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
