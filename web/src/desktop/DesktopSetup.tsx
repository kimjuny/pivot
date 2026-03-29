import React, { useState } from "react";
import { getApiBaseUrl, setApiBaseUrl, httpClient } from "@/utils/api";
import {
  setStoredBackendUrl,
  resolveApiBaseUrl,
} from "@/desktop/desktop-adapter";

/**
 * First-launch setup screen for the desktop application.
 *
 * Shown when no backend URL has been stored yet. Collects the server
 * address from the user, validates it with a lightweight health check,
 * and persists it to localStorage.
 */
export function DesktopSetup({ onReady }: { onReady: () => void }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  async function handleConnect(): Promise<void> {
    setError(null);
    setConnecting(true);

    const trimmed = url.trim().replace(/\/+$/, "");
    if (!trimmed) {
      setError("Please enter a server URL.");
      setConnecting(false);
      return;
    }

    const apiBase = `${trimmed}/api`;

    try {
      const response = await httpClient(`${apiBase}/models`, {
        headers: { Authorization: "" },
      });

      // Any response (even 401) means the server is reachable.
      // 401 is expected without auth — the server is there.
      if (response.status === 0) {
        throw new Error("Network error");
      }
    } catch (err) {
      setError(
        `Cannot reach server at ${trimmed}. Check the URL and try again.`
      );
      setConnecting(false);
      return;
    }

    setApiBaseUrl(apiBase);
    setStoredBackendUrl(trimmed);
    setConnecting(false);
    onReady();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <div className="w-full max-w-md space-y-6 rounded-lg border border-border bg-card p-8 shadow-lg">
        <div className="space-y-2 text-center">
          <h1 className="text-2xl font-bold tracking-tight">Pivot Desktop</h1>
          <p className="text-sm text-muted-foreground">
            Enter the address of your Pivot server to get started.
          </p>
        </div>

        <div className="space-y-2">
          <label
            htmlFor="server-url"
            className="text-sm font-medium text-foreground"
          >
            Server URL
          </label>
          <input
            id="server-url"
            type="url"
            placeholder="https://pivot.example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleConnect();
            }}
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            autoFocus
          />
          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}
        </div>

        <button
          onClick={handleConnect}
          disabled={connecting}
          className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground ring-offset-background transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
        >
          {connecting ? "Connecting..." : "Connect"}
        </button>
      </div>
    </div>
  );
}
