import { MessageSquare } from "@/lib/lucide";

import { cn } from "@/lib/utils";

interface ChannelProviderBadgeProps {
  channelKey: string;
  name: string;
  logoUrl?: string | null;
  className?: string;
  iconClassName?: string;
  textClassName?: string;
}

/**
 * Renders one channel provider mark with the extension logo or a fallback icon.
 */
export function ChannelProviderBadge({
  channelKey,
  name,
  logoUrl,
  className,
  iconClassName,
  textClassName,
}: ChannelProviderBadgeProps) {
  const resolvedLogoUrl = logoUrl ?? null;

  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {resolvedLogoUrl ? (
        <img
          src={resolvedLogoUrl}
          alt={`${name} logo`}
          className={cn("h-3.5 w-3.5 shrink-0 rounded-sm", iconClassName)}
          loading="lazy"
        />
      ) : (
        <MessageSquare
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground", iconClassName)}
        />
      )}
      <span className={cn("truncate", textClassName)}>{name}</span>
    </span>
  );
}
