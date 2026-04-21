import { Server } from "@/lib/lucide";

import { cn } from "@/lib/utils";

interface ExtensionPackageBadgeProps {
  name: string;
  logoUrl?: string | null;
  className?: string;
  iconClassName?: string;
  textClassName?: string;
}

/**
 * Renders one extension package mark with the package logo when available.
 */
export function ExtensionPackageBadge({
  name,
  logoUrl = null,
  className,
  iconClassName,
  textClassName,
}: ExtensionPackageBadgeProps) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)}>
      {logoUrl ? (
        <img
          src={logoUrl}
          alt={`${name} logo`}
          className={cn("h-4 w-4 shrink-0 rounded-sm object-cover", iconClassName)}
          loading="lazy"
        />
      ) : (
        <Server
          className={cn("h-4 w-4 shrink-0 text-muted-foreground", iconClassName)}
        />
      )}
      <span className={cn("truncate", textClassName)}>{name}</span>
    </span>
  );
}
