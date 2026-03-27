import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { ArrowRight, Info } from '@/lib/lucide';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { AgentReleaseRecord } from '../utils/api';
import ReleaseSummarySections from './ReleaseSummarySections';

interface PublishReleaseDrawerProps {
  /** Controls drawer visibility. */
  open: boolean;
  /** Handles drawer visibility changes. */
  onOpenChange: (open: boolean) => void;
  /** Whether the draft still has local edits that must be saved first. */
  hasUnsavedChanges: boolean;
  /** Summary of the current draft changes that would be published. */
  changeSummary: string[];
  /** Most recent published release, if one exists. */
  latestRelease: AgentReleaseRecord | null;
  /** Release note draft shown in the drawer. */
  releaseNote: string;
  /** Update callback for the release note input. */
  onReleaseNoteChange: (value: string) => void;
  /** Whether a publish request is currently in flight. */
  isPublishing: boolean;
  /** Whether the current draft can produce a new release. */
  canPublish: boolean;
  /** Confirm publishing the current saved draft. */
  onPublish: () => void | Promise<void>;
}

/**
 * Lightweight publish dialog scaffold.
 * Why: the Studio needs a visible release entry point now, even before the
 * release backend and history model are fully implemented.
 */
function PublishReleaseDrawer({
  open,
  onOpenChange,
  hasUnsavedChanges,
  changeSummary,
  latestRelease,
  releaseNote,
  onReleaseNoteChange,
  isPublishing,
  canPublish,
  onPublish,
}: PublishReleaseDrawerProps) {
  const nextVersion = latestRelease ? latestRelease.version + 1 : 1;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span>Publish current draft</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground"
                >
                  <Info className="h-3.5 w-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-xs text-sm leading-relaxed">
                Studio compares the current saved draft against the latest
                release snapshot so you can review what will ship before you
                publish.
              </TooltipContent>
            </Tooltip>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          <div className="rounded-lg border border-border bg-muted/20 p-4">
            <div className="flex flex-wrap items-center gap-2">
              {latestRelease ? (
                <>
                  <Badge variant="outline" className="h-6 px-2 text-[11px]">
                    v{latestRelease.version}
                  </Badge>
                  <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                </>
              ) : (
                <Badge variant="outline" className="h-6 px-2 text-[11px]">
                  No release
                </Badge>
              )}
              <Badge className="h-6 px-2 text-[11px]">v{nextVersion}</Badge>
              {hasUnsavedChanges ? (
                <Badge variant="secondary" className="h-6 px-2 text-[11px]">
                  Includes local edits
                </Badge>
              ) : null}
              {changeSummary.length === 0 ? (
                <Badge variant="secondary" className="h-6 px-2 text-[11px]">
                  No changes
                </Badge>
              ) : null}
            </div>

            {changeSummary.length > 0 ? (
              <div className="mt-4">
                <ReleaseSummarySections summary={changeSummary} />
              </div>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <label htmlFor="release-note" className="text-sm font-medium text-foreground">
                Release note
              </label>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <Info className="h-3 w-3" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-xs text-sm leading-relaxed">
                  Stored on the immutable release record for future review.
                </TooltipContent>
              </Tooltip>
            </div>
            <Textarea
              id="release-note"
              value={releaseNote}
              onChange={(event) => onReleaseNoteChange(event.target.value)}
              placeholder="Summarize what changed in this release."
              className="min-h-28"
            />
          </div>
        </div>

        <DialogFooter>
          <DialogClose asChild>
            <Button type="button" variant="outline">
              Close
            </Button>
          </DialogClose>
          <Button
            type="button"
            disabled={!canPublish || isPublishing}
            onClick={() => void onPublish()}
          >
            {isPublishing
              ? 'Publishing…'
              : hasUnsavedChanges
                ? 'Save & publish'
                : 'Publish'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default PublishReleaseDrawer;
