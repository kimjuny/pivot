import { Button } from "@/components/ui/button";

/** Props for the date-range toggle selector. */
export interface DateRangeSelectorProps {
  /** Currently selected range key ("7d" | "30d" | "90d"). */
  value: string;
  /** Callback fired when the user picks a different range. */
  onChange: (range: string) => void;
}

const RANGES = ["7d", "30d"] as const;

/**
 * Three-button toggle group for selecting the analytics time range.
 *
 * Button state flips synchronously with the click so the user gets an
 * immediate "I heard you" cue (frame 1 of the dashboard cross-fade spec).
 * The spring easing tween on background/color keeps the swap from feeling
 * abrupt without slowing perceived responsiveness.
 */
export function DateRangeSelector({ value, onChange }: DateRangeSelectorProps) {
  return (
    <div className="flex items-center gap-1 rounded-lg border bg-muted/50 p-1">
      {RANGES.map((range) => (
        <Button
          key={range}
          variant={value === range ? "default" : "ghost"}
          size="sm"
          className="h-7 px-3 text-xs transition-[background-color,color] duration-200 [transition-timing-function:var(--ease-spring)]"
          onClick={() => onChange(range)}
        >
          {range}
        </Button>
      ))}
    </div>
  );
}
