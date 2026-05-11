import { Card, CardContent } from "@/components/ui/card";
import { ArrowDown, ArrowUp } from "lucide-react";

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
}

/** Stat card with value, label, subtitle, and optional trend arrow. */
export function KpiCard({ title, value, subtitle, trend }: KpiCardProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium text-muted-foreground">{title}</p>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-bold">{value}</span>
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
        </div>
        {subtitle && (
          <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p>
        )}
      </CardContent>
    </Card>
  );
}
