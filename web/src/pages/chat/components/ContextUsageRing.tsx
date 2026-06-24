import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import type { ReactContextUsageSummary } from "@/utils/api";

interface ContextUsageRingProps {
  usage: ReactContextUsageSummary | null;
  isLoading: boolean;
  isCompacting?: boolean;
}

const RING_RADIUS = 12;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

interface UsageBreakdownRow {
  label: string;
  tokens: number;
}

/**
 * Shows the current session-context occupancy beside the composer send button,
 * with a hover card that breaks the usage down by category.
 */
export function ContextUsageRing({
  usage,
  isLoading,
  isCompacting = false,
}: ContextUsageRingProps) {
  const usedPercent = usage?.used_percent ?? 0;
  const progressOffset =
    RING_CIRCUMFERENCE - (Math.min(usedPercent, 100) / 100) * RING_CIRCUMFERENCE;
  const progressClassName =
    usedPercent >= 90
      ? "text-foreground/70"
      : usedPercent >= 70
        ? "text-foreground/55"
        : "text-muted-foreground/70";

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className="inline-flex h-7 w-7 items-center justify-center rounded-full transition-colors hover:bg-accent/70"
            aria-label="Session context usage"
            data-compacting={isCompacting ? "true" : "false"}
          >
            <span className="relative flex h-7 w-7 items-center justify-center">
              {isCompacting ? (
                <svg
                  viewBox="0 0 32 32"
                  className="pointer-events-none absolute h-7 w-7 animate-[spin_2.6s_linear_infinite] text-foreground/35"
                  aria-hidden="true"
                >
                  <circle
                    cx="16"
                    cy="16"
                    r="14"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeDasharray="18 70"
                  />
                </svg>
              ) : null}
              <svg
                viewBox="0 0 32 32"
                className={`h-7 w-7 -rotate-90 transition-opacity ${
                  isLoading ? "animate-pulse" : ""
                } ${isCompacting ? "opacity-95" : ""}`}
                aria-hidden="true"
              >
                <circle
                  cx="16"
                  cy="16"
                  r={RING_RADIUS}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  className="text-border"
                />
                <circle
                  cx="16"
                  cy="16"
                  r={RING_RADIUS}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  strokeDasharray={RING_CIRCUMFERENCE}
                  strokeDashoffset={progressOffset}
                  className={usage ? progressClassName : "text-muted-foreground/50"}
                />
              </svg>
              <span className="pointer-events-none absolute text-[8px] font-semibold tabular-nums text-muted-foreground">
                {usage ? `${usedPercent}` : "…"}
              </span>
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="w-64 p-0">
          {usage ? (
            <UsageBreakdownCard usage={usage} isCompacting={isCompacting} />
          ) : (
            <div className="px-3 py-2 text-xs">Calculating context usage</div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function UsageBreakdownCard({
  usage,
  isCompacting,
}: {
  usage: ReactContextUsageSummary;
  isCompacting?: boolean;
}) {
  // Skills + unsent draft/attachments. Mandatory-skills bootstrap lands in
  // bootstrap_tokens; the live composer draft lands in draft_tokens.
  const skillsDraftTokens = (usage.bootstrap_tokens ?? 0) + (usage.draft_tokens ?? 0);
  // Conversation = everything that isn't system prompt, tool defs, or the
  // skills/draft preview (backend conversation_tokens already excludes system
  // and tools; subtract the preview skills/draft portion to avoid overlap).
  const conversationTokens = Math.max(
    usage.conversation_tokens - skillsDraftTokens,
    0,
  );

  const maxTokens = usage.max_context_tokens || 1;
  const rows: UsageBreakdownRow[] = [
    { label: "Conversation", tokens: conversationTokens },
    { label: "Tool definitions", tokens: usage.tools_tokens ?? 0 },
    { label: "System prompt", tokens: usage.system_tokens },
    ...(skillsDraftTokens > 0
      ? [{ label: "Skills / draft", tokens: skillsDraftTokens }]
      : []),
  ].filter((row) => row.tokens > 0);

  return (
    <div className="space-y-2 px-3 py-2.5 text-xs">
      {/* Header: total used / max + compacting note */}
      <div className="space-y-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-semibold text-foreground">Context window</span>
          <span className="tabular-nums text-muted-foreground">
            {formatCompactTokenCount(usage.used_tokens)} /{" "}
            {formatCompactTokenCount(usage.max_context_tokens)}
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
          <div
            className="h-full rounded-full bg-foreground/60 transition-[width] duration-300"
            style={{ width: `${Math.min(usage.used_percent, 100)}%` }}
          />
        </div>
        {isCompacting && (
          <div className="text-muted-foreground">Compacting session context…</div>
        )}
      </div>

      {/* Category breakdown */}
      {rows.length > 0 && (
        <div className="space-y-1 border-t border-border/60 pt-2">
          {rows.map((row) => (
            <div
              key={row.label}
              className="flex items-center justify-between gap-2"
            >
              <span className="text-muted-foreground">{row.label}</span>
              <span className="tabular-nums text-muted-foreground">
                {pct(row.tokens, maxTokens)}% · {formatCompactTokenCount(row.tokens)}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Optional preview footer */}
      {usage.preview_tokens > 0 && (
        <div className="text-muted-foreground">
          +{formatCompactTokenCount(usage.preview_tokens)} tokens if sent now
        </div>
      )}

      {/* Cache hit rate — only once the task has recorded usage */}
      {usage.cache_hit_rate != null && (
        <div className="flex items-center justify-between gap-2 border-t border-border/60 pt-2">
          <span className="text-muted-foreground">Avg cache hit rate</span>
          <span className="tabular-nums text-muted-foreground">
            {usage.cache_hit_rate}%
          </span>
        </div>
      )}
    </div>
  );
}

function pct(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((part / whole) * 100)));
}

function formatCompactTokenCount(value: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: value >= 100_000 ? 0 : 1,
  }).format(value);
}
