import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Radio } from "lucide-react";

import type { ChannelActivityItem } from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

export type { ChannelActivityItem } from "@/utils/api";

/** Props for the channel activity stats cards. */
export interface ChannelActivityCardProps {
  /** Per-channel activity stats for an agent. */
  data: ChannelActivityItem[];
}

/** Per-channel stats cards showing inbound events, sessions, and last event. */
export function ChannelActivityCard({ data }: ChannelActivityCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Channel Activity</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No channel bindings configured.
          </p>
        ) : (
          <div className="space-y-3">
            {data.map((channel) => (
              <div
                key={channel.channel_key}
                className="flex items-center gap-3 rounded-md border px-3 py-2"
              >
                <div className="flex size-8 items-center justify-center rounded-md bg-primary/10">
                  <Radio className="size-4 text-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{channel.channel_name}</p>
                  <p className="text-xs text-muted-foreground">{channel.channel_key}</p>
                </div>
                <div className="flex gap-4 text-right">
                  <div>
                    <p className="text-sm font-medium tabular-nums">{channel.inbound_events.toLocaleString()}</p>
                    <p className="text-[10px] text-muted-foreground">Events</p>
                  </div>
                  <div>
                    <p className="text-sm font-medium tabular-nums">{channel.active_sessions.toLocaleString()}</p>
                    <p className="text-[10px] text-muted-foreground">Sessions</p>
                  </div>
                  <div className="min-w-[60px]">
                    <p className="text-xs text-muted-foreground">
                      {channel.last_event_at ? formatTimestamp(channel.last_event_at) : "—"}
                    </p>
                    <p className="text-[10px] text-muted-foreground">Last event</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
