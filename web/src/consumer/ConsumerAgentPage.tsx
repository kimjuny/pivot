import { useEffect, useState } from "react";
import { Bot, Loader2 } from "@/lib/lucide";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { LLMBrandAvatar } from "@/components/LLMBrandAvatar";
import ReactChatInterface from "@/components/ReactChatInterface";
import { Card, CardContent } from "@/components/ui/card";
import { getConsumerAgentById } from "@/consumer/api";
import ConsumerUserMenu from "@/consumer/ConsumerUserMenu";
import type { Agent } from "@/types";

/**
 * Full-page Consumer chat workspace for one published agent.
 */
function ConsumerAgentPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [agent, setAgent] = useState<Agent | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const initialSessionId = searchParams.get("session");

  useEffect(() => {
    const parsedAgentId = Number(agentId);
    if (!Number.isInteger(parsedAgentId) || parsedAgentId <= 0) {
      setError("Invalid agent identifier.");
      setIsLoading(false);
      return;
    }

    void (async () => {
      try {
        setIsLoading(true);
        setError(null);
        setAgent(await getConsumerAgentById(parsedAgentId));
      } catch (loadError) {
        setError(
          loadError instanceof Error
            ? loadError.message
            : "Failed to load the consumer agent.",
        );
      } finally {
        setIsLoading(false);
      }
    })();
  }, [agentId]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2
          className="h-6 w-6 animate-spin text-muted-foreground"
          aria-label="Loading agent workspace"
        />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <Card className="m-6">
        <CardContent className="space-y-4 pt-6">
          <p className="text-sm text-destructive">
            {error || "Agent not found."}
          </p>
          <button
            type="button"
            className="inline-flex h-9 items-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium shadow-sm transition-colors hover:bg-accent hover:text-accent-foreground"
            onClick={() => navigate("/app/agents")}
          >
            Back to agents
          </button>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="h-screen bg-background">
      <ReactChatInterface
        key={`${agent.id}:${initialSessionId ?? "draft"}`}
        agentId={agent.id}
        initialSessionId={initialSessionId}
        agentName={agent.name}
        agentToolIds={agent.tool_ids}
        primaryLlmId={agent.llm_id}
        sessionIdleTimeoutMinutes={agent.session_idle_timeout_minutes}
        showCompactDebug={false}
        sidebarTitleIcon={
          <LLMBrandAvatar
            model={agent.model_name}
            containerClassName="flex size-4 items-center justify-center"
            imageClassName="size-4"
            fallback={<Bot className="size-4" aria-hidden="true" />}
          />
        }
        sidebarTitle={agent.name}
        sidebarNavigationItems={[
          {
            key: "agents",
            label: "Agents",
            icon: <Bot className="h-4 w-4" />,
            isActive: false,
            onSelect: () => navigate("/app/agents"),
          },
        ]}
        sidebarFooter={(isCollapsed) => (
          <ConsumerUserMenu isCollapsed={isCollapsed} />
        )}
      />
    </div>
  );
}

export default ConsumerAgentPage;
