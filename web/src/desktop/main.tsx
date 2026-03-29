import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { ThemeProvider } from "@/components/ui/theme-provider";
import { AuthProvider } from "@/contexts/AuthContext";
import { useAuth, getStoredUser, isTokenValid } from "@/contexts/auth-core";
import { setApiBaseUrl, setHttpClient } from "@/utils/api";
import {
  isDesktop,
  getStoredBackendUrl,
  resolveApiBaseUrl,
} from "@/desktop/desktop-adapter";
import { DesktopSetup } from "@/desktop/DesktopSetup";
import LoginPage from "@/components/LoginPage";
import ConsumerEntryPage from "@/consumer/ConsumerEntryPage";
import ConsumerAgentsPage from "@/consumer/ConsumerAgentsPage";
import ConsumerAgentPage from "@/consumer/ConsumerAgentPage";
import "@/index.css";

/**
 * Protected route wrapper for the desktop shell.
 *
 * Redirects to the login page when the user is not authenticated.
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
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner" />
          <div className="text-lg text-muted-foreground font-medium">
            Loading…
          </div>
        </div>
      </div>
    );
  }

  if (!activeUser || !isTokenValid()) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

/**
 * Layout wrapper for Consumer routes in the desktop shell.
 */
function DesktopConsumerLayout() {
  return (
    <DesktopProtectedRoute>
      <Outlet />
    </DesktopProtectedRoute>
  );
}

/**
 * Application root for the desktop shell.
 *
 * - **Dev mode**: skips backend setup; `getApiBaseUrl()` returns `/api`
 *   and the Vite proxy forwards requests to the backend.
 * - **Prod mode**: shows a setup screen on first launch so the user can
 *   point the app at their Pivot server. Requests are routed through the
 *   Tauri HTTP plugin (Rust reqwest), bypassing CORS entirely.
 */
function DesktopApp() {
  const [backendReady, setBackendReady] = useState(() => {
    if (import.meta.env.DEV) return true;
    if (!isDesktop) return true;

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
      {/* Public route */}
      <Route path="/" element={<LoginPage />} />

      {/* Consumer routes */}
      <Route path="/app" element={<DesktopConsumerLayout />}>
        <Route index element={<ConsumerEntryPage />} />
        <Route path="agents" element={<ConsumerAgentsPage />} />
        <Route path="agents/:agentId" element={<ConsumerAgentPage />} />
      </Route>

      {/* Redirect unknown routes to entry */}
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}

/**
 * Bootstrap the desktop shell.
 *
 * - **Dev mode**: the Vite proxy handles `/api` requests; no Tauri plugin needed.
 * - **Prod mode**: loads the Tauri HTTP plugin so every `httpClient()` call is
 *   routed through Rust's reqwest, bypassing CORS.
 */
async function bootstrap(): Promise<void> {
  if (!import.meta.env.DEV) {
    try {
      const { fetch: tauriFetch } = await import("@tauri-apps/plugin-http");
      setHttpClient(tauriFetch as typeof fetch);
    } catch (err) {
      console.error("Failed to initialize Tauri HTTP plugin:", err);
    }
  }

  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <ThemeProvider defaultTheme="dark" storageKey="pivot-ui-theme">
        <BrowserRouter>
          <AuthProvider>
            <DesktopApp />
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </React.StrictMode>
  );
}

bootstrap();
