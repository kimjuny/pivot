import { MessageSquare } from "@/lib/lucide";

import { cn } from "@/lib/utils";

const CHANNEL_ICON_PATHS: Record<string, string> = {
  work_wechat: '/work-wechat.svg',
  feishu: '/feishu.svg',
  telegram: '/telegram.svg',
  dingtalk: '/dingtalk.svg',
};

interface ChannelProviderBadgeProps {
  channelKey: string;
  name: string;
  className?: string;
  iconClassName?: string;
  textClassName?: string;
}

/**
 * Renders one channel provider mark with the matching built-in brand icon when available.
 */
export function ChannelProviderBadge({
  channelKey,
  name,
  className,
  iconClassName,
  textClassName,
}: ChannelProviderBadgeProps) {
  const iconPath = CHANNEL_ICON_PATHS[channelKey] ?? null;

  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {iconPath ? (
        <img
          src={iconPath}
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
