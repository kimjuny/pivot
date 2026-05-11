import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tag } from "lucide-react";

import type { AgentReleaseItem } from "@/utils/api";
import { formatTimestamp } from "@/utils/timestamp";

export type { AgentReleaseItem } from "@/utils/api";

/** Props for the release timeline. */
export interface ReleaseTimelineProps {
  /** Release entries sorted by version desc. */
  data: AgentReleaseItem[];
}

/** Vertical timeline showing release history. */
export function ReleaseTimeline({ data }: ReleaseTimelineProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Release Timeline</CardTitle>
      </CardHeader>
      <CardContent>
        {data.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No releases published yet.
          </p>
        ) : (
          <div className="relative pl-6">
            {/* Vertical line */}
            <div className="absolute left-[9px] top-2 bottom-2 w-px bg-border" />
            <ul className="space-y-4">
              {data.map((release) => (
                <li key={release.version} className="relative">
                  {/* Dot on the line */}
                  <span className="absolute -left-6 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-primary/10">
                    <Tag className="size-2.5 text-primary" />
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-sm font-semibold">v{release.version}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatTimestamp(release.created_at)}
                      </span>
                      {release.published_by && (
                        <span className="text-xs text-muted-foreground">
                          by {release.published_by}
                        </span>
                      )}
                    </div>
                    {release.release_note && (
                      <p className="mt-0.5 text-sm text-muted-foreground">
                        {release.release_note}
                      </p>
                    )}
                    {release.change_summary.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {release.change_summary.map((change, idx) => (
                          <li
                            key={idx}
                            className="text-xs text-muted-foreground before:mr-1.5 before:content-['·']"
                          >
                            {change}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
