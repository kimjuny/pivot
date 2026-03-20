import { Globe } from "lucide-react";

import { cn } from "@/lib/utils";

interface WebSearchProviderBadgeProps {
  name: string;
  logoUrl?: string | null;
  className?: string;
  iconClassName?: string;
  textClassName?: string;
}

/**
 * Renders one web-search provider mark with an optional provider-supplied logo.
 */
export function WebSearchProviderBadge({
  name,
  logoUrl = null,
  className,
  iconClassName,
  textClassName,
}: WebSearchProviderBadgeProps) {
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {logoUrl ? (
        <img
          src={logoUrl}
          alt={`${name} logo`}
          className={cn("h-3.5 w-3.5 shrink-0 rounded-sm", iconClassName)}
        />
      ) : (
        <Globe
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground", iconClassName)}
        />
      )}
      <span className={cn("truncate", textClassName)}>{name}</span>
    </span>
  );
}
