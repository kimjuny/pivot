import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from './components/LoginPage'
import AgentList from './components/AgentList'
import AgentDetailPage from './components/AgentDetailPage'
import LLMList from './components/LLMList'
import Navigation from './components/Navigation'
import { AuthProvider, useAuth, isTokenValid } from './contexts/AuthContext'
import { ThemeProvider } from '@/components/ui/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import './index.css'

/**
 * Protected route wrapper.
 * Redirects to login page if user is not authenticated.
 */
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  // Show loading while checking auth state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner"></div>
          <div className="text-lg text-muted-foreground font-medium">Loading…</div>
        </div>
      </div>
    );
  }

  // Redirect to login if not authenticated
  if (!user || !isTokenValid()) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

/**
 * Layout wrapper with Navigation for authenticated pages.
 */
function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-background text-foreground">
        <Navigation />
        {children}
      </div>
    </ProtectedRoute>
  );
}

/**
 * Agent List Page with layout.
 */
function AgentListPage() {
  return (
    <AuthenticatedLayout>
      <AgentList />
    </AuthenticatedLayout>
  );
}

/**
 * LLM List Page with layout.
 */
function LLMListPage() {
  return (
    <AuthenticatedLayout>
      <LLMList />
    </AuthenticatedLayout>
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
            <Route path="/agents" element={<AgentListPage />} />
            <Route path="/agent/:agentId" element={<AgentDetailPage />} />
            <Route path="/llms" element={<LLMListPage />} />

            {/* Catch-all redirect */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <Toaster />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)
