import React, { useState } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";

import LoginPage from "@/components/LoginPage";
import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import { ThemeProvider } from "@/components/ui/theme-provider";
import ConsumerAgentPage from "@/consumer/ConsumerAgentPage";
import ConsumerAgentsPage from "@/consumer/ConsumerAgentsPage";
import ConsumerEntryPage from "@/consumer/ConsumerEntryPage";
import { DesktopSetup } from "@/desktop/DesktopSetup";
import {
  isDesktop,
  resolveApiBaseUrl,
} from "@/desktop/desktop-adapter";
import { AuthProvider } from "@/contexts/AuthContext";
import { getStoredUser, isTokenValid, useAuth } from "@/contexts/auth-core";
import { setApiBaseUrl } from "@/utils/api";

/**
 * Redirects unauthenticated desktop users back to the login entrypoint.
 */
function DesktopProtectedRoute({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, isLoading } = useAuth();
  const persistedUser = getStoredUser();
  const activeUser = user ?? persistedUser;

  if (isLoading) {
    return <CenteredLoadingIndicator className="h-screen" label="Loading" />;
  }

  if (!activeUser || !isTokenValid()) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

/**
 * Wraps consumer routes with the desktop authentication gate.
 */
function DesktopConsumerLayout() {
  return (
    <DesktopProtectedRoute>
      <Outlet />
    </DesktopProtectedRoute>
  );
}

/**
 * Renders the desktop router and first-launch backend setup flow.
 */
function DesktopAppRoutes() {
  const [backendReady, setBackendReady] = useState(() => {
    if (import.meta.env.DEV || !isDesktop) {
      return true;
    }

    const resolved = resolveApiBaseUrl();
    if (resolved) {
      setApiBaseUrl(resolved);
      return true;
    }
    return false;
  });

  function handleSetupComplete(): void {
    const resolved = resolveApiBaseUrl();
    if (resolved) {
      setApiBaseUrl(resolved);
    }
    setBackendReady(true);
  }

  if (!backendReady) {
    return <DesktopSetup onReady={handleSetupComplete} />;
  }

  return (
    <Routes>
      <Route path="/" element={<LoginPage />} />
      <Route path="/app" element={<DesktopConsumerLayout />}>
        <Route index element={<ConsumerEntryPage />} />
        <Route path="agents" element={<ConsumerAgentsPage />} />
        <Route path="agents/:agentId" element={<ConsumerAgentPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}

/**
 * Composes the full desktop shell providers and route tree.
 */
export function DesktopAppShell() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="pivot-ui-theme">
      <BrowserRouter>
        <AuthProvider>
          <DesktopAppRoutes />
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
