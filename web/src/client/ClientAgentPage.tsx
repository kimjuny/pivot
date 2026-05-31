import { useEffect, useState } from "react";
import { Bot, Clock } from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { LLMBrandAvatar } from "@/components/LLMBrandAvatar";
import ReactChatInterface from "@/components/ReactChatInterface";
import { Card, CardContent } from "@/components/ui/card";
import { getChatBootstrap } from "@/utils/api";
import type { ChatBootstrapResponse } from "@/utils/api";
import ClientUserMenu from "@/client/ClientUserMenu";

/**
 * Full-page Client chat workspace for one published agent.
 */
function ClientAgentPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [bootstrap, setBootstrap] = useState<ChatBootstrapResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const initialSessionId = searchParams.get("session");

  const parsedAgentId = Number(agentId);

  useEffect(() => {
    if (!Number.isInteger(parsedAgentId) || parsedAgentId <= 0) {
      setError("Invalid agent identifier.");
      return;
    }

    let cancelled = false;
    void (async () => {
      try {
        setError(null);
        const data = await getChatBootstrap(parsedAgentId);
        if (!cancelled) {
          setBootstrap(data);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "Failed to load the client agent.",
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [parsedAgentId]);

  if (!Number.isInteger(parsedAgentId) || parsedAgentId <= 0 || error) {
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

  const agent = bootstrap?.agent;
  const llm = bootstrap?.llm;

  return (
    <div className="h-screen bg-background">
      <ReactChatInterface
        key={`${parsedAgentId}:${initialSessionId ?? "draft"}`}
        agentId={parsedAgentId}
        initialSessionId={initialSessionId}
        agentName={agent?.name}
        agentToolIds={agent?.tool_ids}
        primaryLlmId={agent?.llm_id}
        sessionIdleTimeoutMinutes={agent?.session_idle_timeout_minutes}
        compactThresholdPercent={agent?.compact_threshold_percent}
        showCompactDebug={false}
        initialLlm={llm}
        initialSessions={bootstrap?.sessions}
        initialProjects={bootstrap?.projects}
        initialChatSurfaces={bootstrap?.chat_surfaces}
        initialWebSearchProviders={bootstrap?.web_search_providers}
        sidebarTitleIcon={
          agent ? (
            <LLMBrandAvatar
              model={agent.model_name}
              containerClassName="flex size-4 items-center justify-center"
              imageClassName="size-4"
              fallback={<Bot className="size-4" aria-hidden="true" />}
            />
          ) : undefined
        }
        sidebarTitle={agent?.name}
        sidebarNavigationItems={[
          {
            key: "agents",
            label: "Agents",
            icon: <Bot className="h-4 w-4" />,
            isActive: false,
            onSelect: () => navigate("/app/agents"),
          },
          {
            key: "automations",
            label: "Automations",
            icon: <Clock className="h-4 w-4" />,
            isActive: false,
            onSelect: () =>
              navigate("/app/automations"),
          },
        ]}
        sidebarFooter={(isCollapsed) => (
          <ClientUserMenu isCollapsed={isCollapsed} />
        )}
      />
    </div>
  );
}

export default ClientAgentPage;
