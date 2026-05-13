import { useMemo } from "react";
import { ArrowDown, ArrowUp, Info } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCountUp } from "@/hooks/use-count-up";

/** Trend direction shown beside the KPI value. */
export interface KpiTrend {
  /** Signed percentage change vs previous period. */
  value: number;
  /** Semantic direction derived from the sign of *value*. */
  direction: "up" | "down";
}

/** Props for a single dashboard KPI stat card. */
export interface KpiCardProps {
  /** Short label rendered above the value. */
  title: string;
  /** Primary metric displayed large. */
  value: string | number;
  /** Secondary text below the value. */
  subtitle?: string;
  /** Optional trend indicator showing period-over-period change. */
  trend?: KpiTrend;
  /** Hover explanation shown beside the title. */
  tooltip?: string;
}

/** Decomposed numeric formatting parsed from a `string | number` KPI value. */
interface ParsedValue {
  numeric: number;
  decimals: number;
  format: (current: number) => string;
}

/**
 * Parse a KPI value into a numeric target plus a formatter that re-applies
 * any thousands separators, suffixes, or non-numeric framing to the animated
 * intermediate values. Strings without a recognizable number fall back to
 * NaN so the caller can render them statically.
 */
function parseKpiValue(value: string | number): ParsedValue {
  if (typeof value === "number") {
    const decimals =
      Number.isFinite(value) && !Number.isInteger(value)
        ? Math.min(2, (value.toString().split(".")[1] ?? "").length)
        : 0;
    return {
      numeric: value,
      decimals,
      format: (current) => current.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }),
    };
  }

  const match = value.match(/^([^\d-]*)(-?[\d,]*\.?\d+)([^\d]*)$/);
  if (!match) {
    return { numeric: NaN, decimals: 0, format: () => value };
  }

  const [, prefix, rawNumber, suffix] = match;
  const numeric = parseFloat(rawNumber.replace(/,/g, ""));
  const decimalPart = rawNumber.split(".")[1];
  const decimals = decimalPart ? decimalPart.length : 0;
  const useGrouping = rawNumber.includes(",");

  return {
    numeric,
    decimals,
    format: (current) =>
      `${prefix}${current.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
        useGrouping,
      })}${suffix}`,
  };
}

/** Stat card with value, label, subtitle, and optional trend arrow. */
export function KpiCard({
  title,
  value,
  subtitle,
  trend,
  tooltip,
}: KpiCardProps) {
  const parsed = useMemo(() => parseKpiValue(value), [value]);
  const animatable = !Number.isNaN(parsed.numeric);
  const { value: animatedNumeric } = useCountUp(
    animatable ? parsed.numeric : 0,
    { duration: 800, decimals: parsed.decimals },
  );
  const display = animatable ? parsed.format(animatedNumeric) : String(value);

  return (
    <Card>
      <CardContent className="p-4 text-center">
        <p className="text-xs font-medium text-muted-foreground">
          <span className="relative inline">
            {title}
            {tooltip ? (
              <span className="absolute top-1/2 -translate-y-1/2" style={{ left: "100%", paddingLeft: 2 }}>
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3 w-3 cursor-help text-muted-foreground/60" />
                    </TooltipTrigger>
                    <TooltipContent
                      side="top"
                      className="max-w-56 text-xs leading-relaxed"
                    >
                      {tooltip}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </span>
            ) : null}
          </span>
        </p>
        <span className="mt-1 block text-2xl font-bold tabular-nums">
          {display}
        </span>
        {(trend || subtitle) && (
          <div className="mt-1 flex items-center justify-center gap-1">
            {trend && (
              <span
                className={`flex items-center text-xs font-medium ${
                  trend.direction === "up"
                    ? "text-emerald-600"
                    : "text-red-500"
                }`}
              >
                {trend.direction === "up" ? (
                  <ArrowUp className="h-3 w-3" />
                ) : (
                  <ArrowDown className="h-3 w-3" />
                )}
                {Math.abs(trend.value)}%
              </span>
            )}
            {subtitle && (
              <span className="text-xs text-muted-foreground">{subtitle}</span>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
