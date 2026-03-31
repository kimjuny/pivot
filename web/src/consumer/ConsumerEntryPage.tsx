import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import { getConsumerSessions } from "@/consumer/api";
import { Button } from "@/components/ui/button";

/**
 * Restores the user's most recent Consumer workspace as quickly as possible.
 */
function ConsumerEntryPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    void (async () => {
      try {
        setError(null);
        const response = await getConsumerSessions(1);
        if (isCancelled) {
          return;
        }

        const latestSession = response.sessions[0];
        if (latestSession) {
          navigate(
            `/app/agents/${latestSession.agent_id}?session=${latestSession.session_id}`,
            { replace: true },
          );
          return;
        }

        navigate("/app/agents", { replace: true });
      } catch (loadError) {
        if (isCancelled) {
          return;
        }

        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to open your latest workspace.",
        );
      }
    })();

    return () => {
      isCancelled = true;
    };
  }, [navigate]);

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-background px-6">
        <div className="space-y-4 rounded-2xl border border-border bg-background px-6 py-5 shadow-sm">
          <p className="text-sm text-destructive">{error}</p>
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate("/app/agents", { replace: true })}
          >
            Open agents
          </Button>
        </div>
      </div>
    );
  }

  return (
    <CenteredLoadingIndicator
      className="h-screen"
      label="Opening your latest workspace"
    />
  );
}

export default ConsumerEntryPage;
