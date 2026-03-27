import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import type { AgentReleaseRecord } from '../utils/api';
import ReleaseSummarySections from './ReleaseSummarySections';

interface ReleaseHistoryDialogProps {
  /** Controls dialog visibility. */
  open: boolean;
  /** Handles dialog visibility changes. */
  onOpenChange: (open: boolean) => void;
  /** Immutable release records to show in audit order. */
  releaseHistory: AgentReleaseRecord[];
  /** Currently active release id for new user sessions. */
  activeReleaseId: number | null;
}

/**
 * Dedicated release-history dialog kept separate from the publish flow.
 * Why: audit browsing is a different task from confirming a new release, so it
 * should not compete for space inside the publish confirmation surface.
 */
function ReleaseHistoryDialog({
  open,
  onOpenChange,
  releaseHistory,
  activeReleaseId,
}: ReleaseHistoryDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Release history</DialogTitle>
        </DialogHeader>

        {releaseHistory.length > 0 ? (
          <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
            {releaseHistory.map((release) => (
              <div
                key={release.id}
                className="rounded-lg border border-border/80 bg-background px-4 py-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="h-6 px-2">
                    v{release.version}
                  </Badge>
                  {release.id === activeReleaseId ? (
                    <Badge className="h-6 px-2 text-[11px]">Active</Badge>
                  ) : null}
                  <span className="text-xs text-muted-foreground">
                    {new Date(release.created_at).toLocaleString()}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    by {release.published_by ?? 'Unknown'}
                  </span>
                </div>

                {release.release_note ? (
                  <p className="mt-3 text-sm text-foreground">{release.release_note}</p>
                ) : null}

                {release.change_summary.length > 0 ? (
                  <div className="mt-3 rounded-md border border-border/60 bg-muted/20 px-3 py-2">
                    <ReleaseSummarySections summary={release.change_summary} compact />
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
            No releases yet.
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default ReleaseHistoryDialog;
