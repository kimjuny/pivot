import React from "react";
import ReactDOM from "react-dom/client";
import { DesktopAppShell } from "@/desktop/DesktopAppShell";
import { setHttpClient } from "@/utils/api";
import "@/index.css";

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
      <DesktopAppShell />
    </React.StrictMode>
  );
}

void bootstrap();
