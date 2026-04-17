import { useEffect, useMemo, useRef, useState } from "react";

import { useTheme } from "@/lib/use-theme";
import {
  type DevSurfaceSessionResponse,
  type InstalledSurfaceSessionResponse,
} from "@/utils/api";

export interface InstalledChatSurfaceDescriptor {
  /** Stable installed version id selected for this agent binding. */
  installationId: number;
  /** Stable package id that owns the surface. */
  packageId: string;
  /** Stable surface key declared by the extension manifest. */
  surfaceKey: string;
  /** Human-readable surface title shown in shell chrome. */
  displayName: string;
  /** Optional package-level logo reused as the current surface badge. */
  logoUrl: string | null;
  /** Optional surface or package summary shown in the placeholder shell. */
  description: string;
  /** Optional manifest-declared minimum width in pixels for this surface. */
  minWidth: number | null;
}

interface ExtensionDockProps {
  /** Whether the dock is currently visible. */
  isOpen: boolean;
  /** Toggle callback controlled by the chat host. */
  onOpenChange: (open: boolean) => void;
  /** Active surface session currently rendered inside the dock, if any. */
  activeSurfaceSession: DevSurfaceSessionResponse | null;
  /** Installed surface selected from the chat header, if any. */
  activeInstalledSurface: InstalledChatSurfaceDescriptor | null;
  /** Installed runtime session created for the selected surface, if any. */
  activeInstalledSurfaceSession: InstalledSurfaceSessionResponse | null;
}

/**
 * Render the shared right-side surface dock used by both development and
 * installed surface sessions.
 */
export function ExtensionDock({
  isOpen,
  onOpenChange,
  activeSurfaceSession,
  activeInstalledSurface,
  activeInstalledSurfaceSession,
}: ExtensionDockProps) {
  const previewIframeRef = useRef<HTMLIFrameElement | null>(null);
  const runtimeThemeRef = useRef<{
    sessionKey: string;
    themePreference: "dark" | "light" | "system";
    resolvedTheme: "dark" | "light";
  }>({
    sessionKey: "",
    themePreference: "system",
    resolvedTheme: "dark",
  });
  const [isIframeLoaded, setIsIframeLoaded] = useState(false);
  const { theme } = useTheme();
  const resolvedTheme = useResolvedTheme(theme);
  const runtimeSessionKey = activeInstalledSurfaceSession
    ? `installed:${activeInstalledSurfaceSession.surface_session_id}`
    : activeSurfaceSession
      ? `dev:${activeSurfaceSession.surface_session_id}`
      : "";

  if (runtimeThemeRef.current.sessionKey !== runtimeSessionKey) {
    runtimeThemeRef.current = {
      sessionKey: runtimeSessionKey,
      themePreference: theme,
      resolvedTheme,
    };
  }

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      const iframeWindow = previewIframeRef.current?.contentWindow;
      if (
        event.origin !== window.location.origin ||
        event.source !== iframeWindow ||
        !event.data ||
        typeof event.data !== "object"
      ) {
        return;
      }

      const message = event.data as Record<string, unknown>;
      if (
        message.source !== "pivot-surface" ||
        typeof message.type !== "string"
      ) {
        return;
      }

      if (message.type === "pivot.surface.close") {
        onOpenChange(false);
      }
    };

    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, [onOpenChange]);

  useEffect(() => {
    setIsIframeLoaded(false);
  }, [
    activeInstalledSurfaceSession?.runtime_url,
    activeInstalledSurfaceSession?.surface_token,
    activeSurfaceSession?.surface_session_id,
    activeSurfaceSession?.surface_token,
  ]);

  const runtime = useMemo(() => {
    if (activeInstalledSurface) {
      return {
        displayName: activeInstalledSurface.displayName,
        badge: "Installed",
        badgeClassName:
          "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
        iframeTitle: "Installed surface runtime",
        src: activeInstalledSurfaceSession
          ? buildRuntimeSrc({
              runtimeUrl: activeInstalledSurfaceSession.runtime_url,
              surfaceToken: activeInstalledSurfaceSession.surface_token,
              themePreference: runtimeThemeRef.current.themePreference,
              resolvedTheme: runtimeThemeRef.current.resolvedTheme,
            })
          : null,
        isPending: activeInstalledSurfaceSession === null,
      };
    }

    if (activeSurfaceSession) {
      return {
        displayName: activeSurfaceSession.display_name,
        badge: "Dev",
        badgeClassName:
          "border-amber-400/25 bg-amber-400/10 text-amber-200",
        iframeTitle: "Surface runtime preview",
        src: buildRuntimeSrc({
          runtimeUrl: `/api/chat-surfaces/dev-sessions/${activeSurfaceSession.surface_session_id}/proxy/`,
          surfaceToken: activeSurfaceSession.surface_token,
          themePreference: runtimeThemeRef.current.themePreference,
          resolvedTheme: runtimeThemeRef.current.resolvedTheme,
        }),
        isPending: false,
      };
    }

    return null;
  }, [
    activeInstalledSurface,
    activeInstalledSurfaceSession,
    activeSurfaceSession,
  ]);

  useEffect(() => {
    if (!isOpen || !isIframeLoaded || runtime === null) {
      return;
    }

    previewIframeRef.current?.contentWindow?.postMessage(
      {
        source: "pivot-host",
        type: "pivot.host.theme_changed",
        payload: {
          preference: theme,
          resolved: resolvedTheme,
        },
      },
      window.location.origin,
    );
  }, [isIframeLoaded, isOpen, resolvedTheme, runtime, theme]);

  if (!isOpen) {
    return null;
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-background text-foreground">
      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden bg-background">
        {!runtime ? (
          <div className="flex h-full items-center justify-center px-8">
            <div className="max-w-sm rounded-2xl border border-dashed border-border bg-card px-6 py-8 text-center shadow-sm">
              <div className="text-sm font-semibold text-foreground">
                No surface attached
              </div>
              <div className="mt-3 text-sm leading-6 text-muted-foreground">
                Open one of the surface icons in the chat header, or attach a
                dev surface from the debug panel.
              </div>
            </div>
          </div>
        ) : runtime.isPending ? (
          <div className="flex h-full items-center justify-center px-8">
            <div className="max-w-sm rounded-2xl border border-border bg-card px-6 py-8 text-center shadow-sm">
              <div className="text-sm font-semibold text-foreground">
                Preparing surface runtime
              </div>
              <div className="mt-3 text-sm leading-6 text-muted-foreground">
                Pivot is creating the packaged runtime session for this surface.
              </div>
            </div>
          </div>
        ) : (
          <>
            <iframe
              ref={previewIframeRef}
              title={runtime.iframeTitle}
              src={runtime.src ?? undefined}
              onLoad={() => {
                setIsIframeLoaded(true);
              }}
              className="h-full w-full border-0 bg-background"
            />
            {!isIframeLoaded ? (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background">
                <div className="max-w-sm rounded-2xl border border-border bg-card px-6 py-5 text-center shadow-sm">
                  <div className="text-sm font-semibold text-foreground">
                    Loading surface
                  </div>
                  <div className="mt-2 text-sm leading-6 text-muted-foreground">
                    Preparing the runtime shell for this panel.
                  </div>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

function useResolvedTheme(theme: "dark" | "light" | "system"): "dark" | "light" {
  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }
  return theme;
}

function buildRuntimeSrc({
  runtimeUrl,
  surfaceToken,
  themePreference,
  resolvedTheme,
}: {
  runtimeUrl: string;
  surfaceToken: string;
  themePreference: "dark" | "light" | "system";
  resolvedTheme: "dark" | "light";
}): string {
  const nextUrl = new URL(runtimeUrl, window.location.origin);
  nextUrl.searchParams.set("surface_token", surfaceToken);
  nextUrl.searchParams.set("theme_preference", themePreference);
  nextUrl.searchParams.set("resolved_theme", resolvedTheme);
  return nextUrl.toString();
}
