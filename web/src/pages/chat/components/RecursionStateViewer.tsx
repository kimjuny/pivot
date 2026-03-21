import { useState } from "react";
import { AlertCircle, Loader2 } from "@/lib/lucide";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { API_BASE_URL } from "@/utils/api";
import { getAuthToken } from "@/contexts/auth-core";

interface RecursionStateViewerProps {
  taskId: string;
  iteration: number;
}

/**
 * Lazily fetches recursion state snapshots so the timeline stays light until users ask for detail.
 */
export function RecursionStateViewer({
  taskId,
  iteration,
}: RecursionStateViewerProps) {
  const [state, setState] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Defers the extra request until the tooltip opens because most recursions are never inspected.
   */
  const fetchState = async () => {
    if (state) {
      return;
    }

    setLoading(true);
    try {
      const apiUrl = `${API_BASE_URL}/react/tasks/${taskId}/states/${iteration}`;
      const token = getAuthToken();
      const headers: Record<string, string> = {};

      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const response = await fetch(apiUrl, { headers });
      if (!response.ok) {
        throw new Error("Failed to fetch state");
      }

      const data = (await response.json()) as { current_state: string };
      const parsedState = JSON.parse(data.current_state) as unknown;
      setState(JSON.stringify(parsedState, null, 2));
    } catch (fetchError) {
      setError("Failed to load state");
      console.error(fetchError);
    } finally {
      setLoading(false);
    }
  };

  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip
        onOpenChange={(open) => {
          if (open) {
            void fetchState();
          }
        }}
      >
        <TooltipTrigger asChild>
          <button
            className="rounded-full p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            title="View state"
          >
            <AlertCircle className="h-3.5 w-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-h-[400px] max-w-[500px] overflow-auto border border-border p-4 font-mono text-xs shadow-lg">
          {loading ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Loading state...
            </div>
          ) : error ? (
            <span className="text-destructive">{error}</span>
          ) : (
            <pre className="whitespace-pre-wrap break-all">{state}</pre>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
