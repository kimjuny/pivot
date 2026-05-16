import type { CompactTimelineItem } from "../types";

interface CompactTimelineSeparatorProps {
  item: CompactTimelineItem;
}

/**
 * Placeholder kept for timeline reconciliation; the visible compact indicator
 * is rendered by CompactStatusPill above the composer.
 */
export function CompactTimelineSeparator({
  item,
}: CompactTimelineSeparatorProps) {
  if (item.status !== "running") {
    return null;
  }

  return <div className="sr-only" aria-live="polite">{item.label}</div>;
}
