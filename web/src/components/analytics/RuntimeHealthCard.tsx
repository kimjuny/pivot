import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import type { RuntimeHealth } from "@/utils/api";

/** Props for the runtime health status card. */
export interface RuntimeHealthCardProps {
  /** Runtime health data from the backend. */
  data: RuntimeHealth;
}

/** Status card showing runtime infrastructure health summary. */
export function RuntimeHealthCard({ data }: RuntimeHealthCardProps) {
  const sandboxLabel =
    data.active_sandboxes >= 0
      ? String(data.active_sandboxes)
      : "Unreachable";

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Runtime Health</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">Active Sandboxes</span>
          <span className="text-sm font-medium">{sandboxLabel}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">Storage Backend</span>
          <span className="text-sm font-medium">{data.storage_status}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">Failed Tasks (24h)</span>
          <span className={`text-sm font-medium ${data.failed_tasks_24h > 0 ? "text-destructive" : ""}`}>
            {data.failed_tasks_24h}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}
