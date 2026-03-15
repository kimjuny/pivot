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
}

const RING_RADIUS = 12;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

/**
 * Shows the current prompt-window occupancy beside the composer send button.
 */
export function ContextUsageRing({
  usage,
  isLoading,
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
            aria-label="Context usage"
          >
            <span className="relative flex h-7 w-7 items-center justify-center">
              <svg
                viewBox="0 0 32 32"
                className={`h-7 w-7 -rotate-90 ${isLoading ? "animate-pulse" : ""}`}
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
        <TooltipContent side="top" className="text-xs leading-relaxed">
          {usage ? (
            <>
              <div>
                {usage.used_percent}%已用（剩余{usage.remaining_percent}%）
              </div>
              <div>
                已用{formatCompactTokenCount(usage.used_tokens)}标记，共
                {formatCompactTokenCount(usage.max_context_tokens)}
              </div>
            </>
          ) : (
            <div>正在统计上下文占用</div>
          )}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function formatCompactTokenCount(value: number): string {
  return new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: value >= 100_000 ? 0 : 1,
  }).format(value);
}
