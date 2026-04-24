import { useEffect, useRef, useState, type ReactNode } from "react";
import { BugPlay, Loader2 } from "@/lib/lucide";

import ChatPage from "@/pages/chat/ChatPage";
import { useChatDebugPanelSections } from "@/pages/chat/components/ChatDebugPanelContext";
import { ChatDebugPanelProvider } from "@/pages/chat/components/ChatDebugPanelProvider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  ChatRuntimeDebugState,
  ReactChatInterfaceProps,
} from "@/pages/chat/types";
import { formatTimestamp } from "@/utils/timestamp";

const EMPTY_DEBUG_STATE: ChatRuntimeDebugState = {
  currentSessionId: null,
  isCompacting: false,
  compactStatusMessage: null,
  loadState: "idle",
  runtimeDebug: null,
  error: null,
};

/**
 * Render the latest compact payload as readable JSON without hiding fields.
 */
function formatCompactPayload(
  compactResultRaw: string | null | undefined,
  compactResult: unknown,
): string {
  if (compactResultRaw) {
    try {
      return JSON.stringify(JSON.parse(compactResultRaw), null, 2);
    } catch (_error) {
      return compactResultRaw;
    }
  }

  if (compactResult === null || compactResult === undefined) {
    return "";
  }
  if (typeof compactResult === "string") {
    try {
      return JSON.stringify(JSON.parse(compactResult), null, 2);
    } catch (_error) {
      return compactResult;
    }
  }
  try {
    return JSON.stringify(compactResult, null, 2);
  } catch (_error) {
    return "[Unserializable compact result]";
  }
}

/**
 * Floating runtime-debug affordance for compact-aware session inspection.
 */
function CompactDebugButton({
  debugState,
  debugSections,
}: {
  debugState: ChatRuntimeDebugState;
  debugSections: Array<{
    key: string;
    title: string;
    description?: string;
    content: ReactNode;
  }>;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"compact" | "surface">("compact");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const compactResultText = formatCompactPayload(
    debugState.runtimeDebug?.compact_result_raw,
    debugState.runtimeDebug?.compact_result,
  );
  const hasCompactResult = Boolean(
    debugState.runtimeDebug?.has_compact_result && compactResultText,
  );
  const isLoading = debugState.loadState === "loading";
  const hasError = debugState.loadState === "error";

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (
        containerRef.current &&
        event.target instanceof Node &&
        !containerRef.current.contains(event.target)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [isOpen]);

  return (
    <>
      {debugState.compactStatusMessage && (
        <div className="pointer-events-none fixed bottom-4 left-1/2 z-30 -translate-x-1/2 px-4">
          <div
            className="flex max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full border border-border bg-background/95 px-3 py-2 text-sm text-foreground shadow-lg backdrop-blur"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            <span className="truncate">{debugState.compactStatusMessage}</span>
          </div>
        </div>
      )}

      <div className="pointer-events-none fixed bottom-4 right-4 z-40">
        <div className="pointer-events-auto relative" ref={containerRef}>
          {isOpen && (
            <div className="absolute bottom-0 right-[calc(100%+0.75rem)] w-[min(36rem,calc(100vw-1.5rem))] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-md border bg-popover p-0 text-popover-foreground shadow-md outline-none">
              <div className="border-b px-4 py-3">
                <div className="text-sm font-semibold">Debug Inspector</div>
              </div>

              <Tabs
                value={activeTab}
                onValueChange={(value) =>
                  setActiveTab(value === "surface" ? "surface" : "compact")
                }
                className="px-4 pb-4 pt-3"
              >
                <TabsList className="grid h-auto w-full grid-cols-2">
                  <TabsTrigger value="compact">Compact</TabsTrigger>
                  <TabsTrigger value="surface">Surface</TabsTrigger>
                </TabsList>

                <TabsContent value="compact" className="space-y-3 pt-4">
                    <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                      <span className="truncate font-mono">
                        {debugState.currentSessionId ?? "No active session"}
                      </span>
                      <span className="shrink-0">
                        {debugState.runtimeDebug?.updated_at
                          ? formatTimestamp(debugState.runtimeDebug.updated_at)
                          : "No snapshot"}
                      </span>
                    </div>

                    {hasError && (
                      <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                        {debugState.error ?? "Failed to load compact debug data."}
                      </div>
                    )}

                    {isLoading && (
                      <div className="flex items-center gap-2 rounded-md border border-border/70 bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        <span>Loading latest compact result…</span>
                      </div>
                    )}

                    {hasCompactResult ? (
                      <pre className="max-h-[min(70vh,36rem)] overflow-auto rounded-md border bg-muted/35 p-3 text-[11px] leading-relaxed text-foreground/90">
                        {compactResultText}
                      </pre>
                    ) : (
                      !isLoading && (
                        <div className="rounded-md border border-dashed border-border/70 bg-muted/20 px-3 py-3 text-xs text-muted-foreground">
                          No compact result has been stored for this session yet.
                        </div>
                      )
                    )}
                </TabsContent>

                <TabsContent value="surface" className="space-y-3 pt-4">
                  {debugSections.length > 0 ? (
                    debugSections.map((section) => (
                      <div key={section.key} className="space-y-2">
                        <div>
                          <div className="text-sm font-semibold">
                            {section.title}
                          </div>
                          {section.description ? (
                            <div className="mt-1 text-xs text-muted-foreground">
                              {section.description}
                            </div>
                          ) : null}
                        </div>
                        {section.content}
                      </div>
                    ))
                  ) : (
                    <div className="rounded-md border border-dashed border-border/70 bg-muted/20 px-3 py-3 text-xs text-muted-foreground">
                      No surface-specific debug tools are registered yet.
                    </div>
                  )}
                </TabsContent>
              </Tabs>
            </div>
          )}

          <button
            type="button"
            onClick={() => setIsOpen((current) => !current)}
            className={`inline-flex h-10 w-10 items-center justify-center rounded-full border bg-background/95 shadow-lg backdrop-blur transition-colors ${
              debugState.isCompacting
                ? "border-foreground/20 text-foreground"
                : hasCompactResult
                  ? "border-border text-foreground"
                  : "border-border/80 text-muted-foreground"
            }`}
            aria-label="Open debug panel"
            title="Open debug panel"
          >
            <BugPlay
              className={`h-4 w-4 ${
                debugState.isCompacting ? "animate-pulse" : ""
              }`}
            />
          </button>
        </div>
      </div>
    </>
  );
}

/**
 * Render the page shell inside the debug-panel registry so descendants can
 * contribute developer tools without coupling to the top-level host.
 */
function ReactChatInterfaceShell({
  showCompactDebug = true,
  ...props
}: ReactChatInterfaceProps) {
  const [debugState, setDebugState] =
    useState<ChatRuntimeDebugState>(EMPTY_DEBUG_STATE);
  const debugSections = useChatDebugPanelSections();

  return (
    <div className="relative h-full">
      <ChatPage {...props} onRuntimeDebugChange={setDebugState} />
      {showCompactDebug ? (
        <CompactDebugButton
          debugState={debugState}
          debugSections={debugSections}
        />
      ) : null}
    </div>
  );
}

/**
 * Backward-compatible entrypoint that now owns the floating compact debug shell.
 */
function ReactChatInterface(props: ReactChatInterfaceProps) {
  return (
    <ChatDebugPanelProvider>
      <ReactChatInterfaceShell {...props} />
    </ChatDebugPanelProvider>
  );
}

export default ReactChatInterface;
