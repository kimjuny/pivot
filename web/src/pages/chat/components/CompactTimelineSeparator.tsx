import { AlertCircle, Sparkles } from "lucide-react";

import { Separator } from "@/components/ui/separator";

import type { CompactTimelineItem } from "../types";

interface CompactTimelineSeparatorProps {
  item: CompactTimelineItem;
}

/**
 * Renders a low-noise timeline marker for one compact pass.
 */
export function CompactTimelineSeparator({
  item,
}: CompactTimelineSeparatorProps) {
  const durationLabel =
    item.status === "completed" && item.finishedAt
      ? formatCompactDuration(item.timestamp, item.finishedAt)
      : null;
  const bodyLabel =
    item.status === "completed" && durationLabel
      ? `${item.label} ${durationLabel}`
      : item.label;
  const toneClassName =
    item.status === "failed"
      ? "text-destructive/80"
      : "text-muted-foreground/85";

  return (
    <div className="my-8 flex items-center gap-3 px-1" aria-live="polite">
      <Separator className="flex-1 bg-border/70" />
      <div
        className={`group relative inline-flex min-w-0 items-center gap-2 rounded-full border border-border/70 bg-background/85 px-3 py-1 text-[11px] font-medium tracking-[0.18em] uppercase shadow-sm backdrop-blur-sm ${toneClassName}`}
      >
        {item.status === "failed" ? (
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
        ) : (
          <Sparkles
            className={`h-3.5 w-3.5 shrink-0 ${
              item.status === "running" ? "text-foreground/75" : "text-muted-foreground"
            }`}
          />
        )}
        <span className={item.status === "running" ? "thinking-silver-shimmer" : ""}>
          {bodyLabel}
        </span>
        {item.status === "running" ? (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-[1px] rounded-full bg-[linear-gradient(110deg,transparent_0%,transparent_22%,rgb(255_255_255_/_0.06)_42%,rgb(255_255_255_/_0.48)_50%,rgb(255_255_255_/_0.08)_58%,transparent_78%,transparent_100%)] bg-[length:190%_100%] animate-[compactSeparatorSweep_2.8s_linear_infinite]"
          />
        ) : null}
      </div>
      <Separator className="flex-1 bg-border/70" />
    </div>
  );
}

function formatCompactDuration(startedAt: string, finishedAt: string): string {
  const elapsedMs = Math.max(
    0,
    Date.parse(finishedAt || startedAt) - Date.parse(startedAt),
  );
  const totalSeconds = Math.max(1, Math.round(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes <= 0) {
    return `${seconds}s`;
  }
  return `${minutes}m${seconds.toString().padStart(2, "0")}s`;
}
