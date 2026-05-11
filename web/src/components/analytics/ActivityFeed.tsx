import { useNavigate } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import type { RecentActivityItem } from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

export type { RecentActivityItem } from "@/utils/api";

/** Props for the recent activity feed list. */
export interface ActivityFeedProps {
  /** Recent session events from the backend. */
  data: RecentActivityItem[];
}

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500",
  waiting_input: "bg-yellow-500",
  closed: "bg-gray-400",
};

/** Feed list showing recent session events with agent name, user, and time. */
export function ActivityFeed({ data }: ActivityFeedProps) {
  const navigate = useNavigate();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium">Recent Activity</CardTitle>
        <Button
          variant="ghost"
          size="sm"
          className="h-auto px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => navigate("/studio/operations/sessions")}
        >
          See more
        </Button>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No recent activity.
          </p>
        ) : (
          <ul className="space-y-3">
            {data.map((item, idx) => (
              <li
                key={idx}
                className="flex cursor-pointer items-start gap-3 rounded-md px-1 py-1 transition-colors hover:bg-muted/50"
                onClick={() => navigate(`/studio/operations/sessions/${item.session_id}`)}
              >
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${STATUS_COLORS[item.status] ?? "bg-blue-500"}`}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">
                    <span className="font-medium">{item.agent_name}</span>
                    <span className="text-muted-foreground"> — {item.username}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {item.session_type === "consumer" ? "Client" : "Studio"} · {item.status} · {formatTimestamp(item.created_at)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
