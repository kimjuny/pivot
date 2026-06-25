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
  /**
   * Whether a task is currently streaming. The speedometer arc stays resident
   * for the whole task lifetime (it does not pop in/out between iterations);
   * the fill level animates smoothly between rate samples.
   */
  isStreaming?: boolean;
  /**
   * Current token generation rate (tokens/sec) while a task is streaming.
   * Drives the fill level of the outer speedometer arc.
   */
  tokensPerSecond?: number | null;
}

const RING_RADIUS = 10.5;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/** Full-scale token rate for the speedometer arc (tok/s at 100% sweep). */
const MAX_TOKEN_RATE = 300;

/**
 * Both rings are full circles that start growing from 6 o'clock (bottom) and
 * sweep clockwise, giving them a single shared visual language. A stroke
 * begins at 3 o'clock by default, so a `rotate(90deg)` moves the start to
 * 6 o'clock. The outer rate ring sits just outside the context ring with a
 * small gap between them.
 */
const GAUGE_RADIUS = 13.5;
const GAUGE_STROKE_WIDTH = 1.25;
const GAUGE_CIRCUMFERENCE = 2 * Math.PI * GAUGE_RADIUS;

interface UsageBreakdownRow {
  label: string;
  tokens: number;
}

/**
 * Shows the current session-context occupancy beside the composer send button,
 * with a hover card that breaks the usage down by category. While a task is
 * streaming, an outer speedometer arc renders the live token generation rate.
 */
export function ContextUsageRing({
  usage,
  isLoading,
  isCompacting = false,
  isStreaming = false,
  tokensPerSecond = null,
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

  const safeTokensPerSecond =
    typeof tokensPerSecond === "number" && tokensPerSecond > 0
      ? tokensPerSecond
      : 0;
  // The arc stays resident for the whole task, so it only depends on whether a
  // task is running — not on whether the current iteration happens to have a
  // positive rate sample. This avoids the ring popping in/out between iters.
  const showGauge = isStreaming;
  // Fill fraction of the circle, clamped to [0, 1].
  const gaugeFraction = Math.min(safeTokensPerSecond / MAX_TOKEN_RATE, 1);
  // Color shifts from muted blue (idle) toward vivid blue as the rate climbs.
  const gaugeColorClassName =
    gaugeFraction >= 0.66
      ? "text-blue-500"
      : gaugeFraction >= 0.33
        ? "text-sky-500"
        : "text-sky-400/80";

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className="inline-flex h-6 w-6 items-center justify-center rounded-full transition-colors hover:bg-accent/70"
            aria-label="Session context usage"
            data-compacting={isCompacting ? "true" : "false"}
          >
            <span className="relative flex h-6 w-6 items-center justify-center">
              {isCompacting ? (
                <svg
                  viewBox="0 0 32 32"
                  className="pointer-events-none absolute h-6 w-6 animate-[spin_2.6s_linear_infinite] text-foreground/35"
                  aria-hidden="true"
                >
                  <circle
                    cx="16"
                    cy="16"
                    r="13"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeDasharray="18 70"
                  />
                </svg>
              ) : null}
              {showGauge ? (
                <SpeedometerGauge
                  fraction={gaugeFraction}
                  filledClassName={gaugeColorClassName}
                />
              ) : null}
              <svg
                viewBox="0 0 32 32"
                className={`h-6 w-6 rotate-90 transition-opacity ${
                  isLoading && !usage ? "animate-pulse" : ""
                } ${isCompacting ? "opacity-95" : ""}`}
                aria-hidden="true"
              >
                <circle
                  cx="16"
                  cy="16"
                  r={RING_RADIUS}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="text-border"
                />
                <circle
                  cx="16"
                  cy="16"
                  r={RING_RADIUS}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeDasharray={RING_CIRCUMFERENCE}
                  strokeDashoffset={progressOffset}
                  className={usage ? progressClassName : "text-muted-foreground/50"}
                />
              </svg>
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="w-64 p-0">
          {usage ? (
            <UsageBreakdownCard
              usage={usage}
              isCompacting={isCompacting}
              tokensPerSecond={isStreaming ? safeTokensPerSecond : null}
            />
          ) : (
            <div className="px-3 py-2 text-xs">Calculating context usage</div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * Renders the outer token-rate ring as a full circle that starts filling
 * from 6 o'clock and sweeps clockwise — matching the inner context ring so
 * the two share one visual language. Only the colored fill is drawn: there
 * is no background track, so an idle (zero) rate renders nothing at all.
 * The fill level is driven by `stroke-dashoffset` with a CSS transition, so
 * rate samples that jump (e.g. 128 → 0 between iterations) animate smoothly
 * instead of snapping.
 */
function SpeedometerGauge({
  fraction,
  filledClassName,
}: {
  fraction: number;
  filledClassName: string;
}) {
  // Fixed dasharray = full circumference; the visible fill is controlled purely
  // by dashoffset, which CSS interpolates. offset 0 shows the full ring;
  // offset = CIRC hides it entirely. fillLength = CIRC * fraction.
  const fillLength = GAUGE_CIRCUMFERENCE * fraction;
  const dashOffset = GAUGE_CIRCUMFERENCE - fillLength;

  return (
    <svg
      viewBox="0 0 32 32"
      className="pointer-events-none absolute h-6 w-6 rotate-90"
      aria-hidden="true"
    >
      <circle
        cx="16"
        cy="16"
        r={GAUGE_RADIUS}
        fill="none"
        stroke="currentColor"
        strokeWidth={GAUGE_STROKE_WIDTH}
        strokeLinecap="round"
        strokeDasharray={GAUGE_CIRCUMFERENCE}
        strokeDashoffset={dashOffset}
        className={filledClassName}
        style={{
          transition: "stroke-dashoffset 600ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      />
    </svg>
  );
}

function UsageBreakdownCard({
  usage,
  isCompacting,
  tokensPerSecond = null,
}: {
  usage: ReactContextUsageSummary;
  isCompacting?: boolean;
  tokensPerSecond?: number | null;
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

      {/* Live token generation rate while streaming */}
      {tokensPerSecond != null && (
        <div className="flex items-center justify-between gap-2 border-t border-border/60 pt-2">
          <span className="text-muted-foreground">Token rate</span>
          <span className="tabular-nums text-muted-foreground">
            {tokensPerSecond.toFixed(1)} tok/s
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
