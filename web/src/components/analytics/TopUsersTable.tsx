import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { AgentUserStats } from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

export type { AgentUserStats } from "@/utils/api";

/** Props for the top users table. */
export interface TopUsersTableProps {
  /** User usage stats sorted by session count desc. */
  data: AgentUserStats[];
}

function formatTokenCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
  return count.toLocaleString();
}

/** Table of top users for a specific agent. */
export function TopUsersTable({ data }: TopUsersTableProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Top Users</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No user data in this period.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="pb-2 font-medium">User</th>
                  <th className="pb-2 font-medium text-right">Sessions</th>
                  <th className="pb-2 font-medium text-right">Tasks</th>
                  <th className="pb-2 font-medium text-right">Tokens</th>
                  <th className="pb-2 font-medium text-right">Last Active</th>
                </tr>
              </thead>
              <tbody>
                {data.map((user) => (
                  <tr key={user.user_id} className="border-b last:border-0">
                    <td className="py-2 font-medium">{user.username}</td>
                    <td className="py-2 text-right tabular-nums">{user.sessions.toLocaleString()}</td>
                    <td className="py-2 text-right tabular-nums">{user.tasks.toLocaleString()}</td>
                    <td className="py-2 text-right tabular-nums">{formatTokenCount(user.total_tokens)}</td>
                    <td className="py-2 text-right text-muted-foreground">
                      {user.last_active ? formatTimestamp(user.last_active) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
