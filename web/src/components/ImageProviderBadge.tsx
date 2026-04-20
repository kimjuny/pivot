import { Layers } from "@/lib/lucide";

import { cn } from "@/lib/utils";

interface ImageProviderBadgeProps {
  name: string;
  logoUrl?: string | null;
  className?: string;
  iconClassName?: string;
  textClassName?: string;
}

/**
 * Renders one image-generation provider mark with a stable icon treatment.
 */
export function ImageProviderBadge({
  name,
  logoUrl = null,
  className,
  iconClassName,
  textClassName,
}: ImageProviderBadgeProps) {
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {logoUrl ? (
        <img
          src={logoUrl}
          alt={`${name} logo`}
          className={cn("h-3.5 w-3.5 shrink-0 rounded-sm", iconClassName)}
        />
      ) : (
        <Layers
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground", iconClassName)}
        />
      )}
      <span className={cn("truncate", textClassName)}>{name}</span>
    </span>
  );
}
