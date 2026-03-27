import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { History } from '@/lib/lucide';
import { cn } from '@/lib/utils';
import ChangeSummaryHoverCard from './ChangeSummaryHoverCard';

interface AgentWorkspaceToolbarProps {
  /** Currently active release version used for new end-user sessions. */
  activeReleaseVersion: number | null;
  /** Whether the current working copy differs from the saved draft baseline. */
  hasUnsavedChanges: boolean;
  /** Whether the publish action should surface pending work. */
  hasPublishableChanges: boolean;
  /** Whether a save operation is in flight. */
  isSavingDraft: boolean;
  /** Summary entries for the next save action. */
  saveSummary: string[];
  /** Summary entries for the next publish action. */
  publishSummary: string[];
  /** Trigger draft save for the current working copy. */
  onSaveDraft: () => void | Promise<void>;
  /** Revert the working copy to the last saved draft. */
  onDiscardChanges: () => void;
  /** Open the draft test surface. */
  onOpenTest: () => void;
  /** Open the publish entry point. */
  onOpenPublish: () => void;
  /** Open the immutable release history dialog. */
  onOpenReleaseHistory: () => void;
}

/**
 * Thin workspace status bar for the agent editor.
 * Why: status and global actions should stay visible without duplicating the
 * sidebar identity block or forcing users into a separate overview page.
 */
function AgentWorkspaceToolbar({
  activeReleaseVersion,
  hasUnsavedChanges,
  hasPublishableChanges,
  isSavingDraft,
  saveSummary,
  publishSummary,
  onSaveDraft,
  onDiscardChanges,
  onOpenTest,
  onOpenPublish,
  onOpenReleaseHistory,
}: AgentWorkspaceToolbarProps) {
  const renderActionButton = (
    label: string,
    options: {
      showDot: boolean;
      disabled?: boolean;
      variant?: 'default' | 'outline' | 'secondary' | 'ghost';
      onClick: () => void;
      summaryTitle?: string;
      summaryDescription?: string;
      summaryItems?: string[];
    }
  ) => {
    const button = (
      <Button
        type="button"
        variant={options.variant}
        size="sm"
        disabled={options.disabled}
        onClick={options.onClick}
        className={cn(
          "relative transition-[box-shadow,border-color,background-color]",
          options.showDot &&
            options.variant === 'outline' &&
            "border-primary/60 shadow-[0_0_0_1px_rgba(59,130,246,0.45),0_0_18px_rgba(59,130,246,0.16)]",
          options.showDot &&
            options.variant !== 'outline' &&
            "shadow-[0_0_0_1px_rgba(255,255,255,0.32),0_0_20px_rgba(59,130,246,0.28)]"
        )}
      >
        {label}
      </Button>
    );

    if (!options.showDot || !options.summaryTitle || !options.summaryDescription) {
      return button;
    }

    return (
      <ChangeSummaryHoverCard
        title={options.summaryTitle}
        description={options.summaryDescription}
        changes={options.summaryItems ?? []}
      >
        {button}
      </ChangeSummaryHoverCard>
    );
  };

  return (
    <div className="pointer-events-auto w-fit rounded-2xl border border-border/80 bg-background/85 p-2 shadow-[0_16px_40px_rgba(15,23,42,0.16)] backdrop-blur supports-[backdrop-filter]:bg-background/72">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div className="flex flex-wrap items-center gap-1.5 pr-1">
          {activeReleaseVersion !== null ? (
            <Badge variant="default" className="h-6 px-2 text-[11px]">
              {`Active v${activeReleaseVersion}`}
            </Badge>
          ) : null}
        </div>
        {hasUnsavedChanges ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={isSavingDraft}
            onClick={onDiscardChanges}
          >
            Discard
          </Button>
        ) : null}
        {renderActionButton(isSavingDraft ? 'Saving…' : 'Save', {
          showDot: hasUnsavedChanges,
          disabled: !hasUnsavedChanges || isSavingDraft,
          variant: 'outline',
          onClick: () => void onSaveDraft(),
          summaryTitle: 'Ready to save',
          summaryDescription: 'These local edits will be written into the current draft.',
          summaryItems: saveSummary,
        })}
        <Button type="button" variant="secondary" size="sm" onClick={onOpenTest}>
          Test
        </Button>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button type="button" variant="ghost" size="icon" onClick={onOpenReleaseHistory}>
              <History className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">Release history</TooltipContent>
        </Tooltip>
        {renderActionButton('Publish', {
          showDot: hasPublishableChanges,
          onClick: onOpenPublish,
          summaryTitle: 'Ready to publish',
          summaryDescription: hasUnsavedChanges
            ? 'Publishing will include your current local edits and save them first.'
            : 'Publishing will use the current saved draft.',
          summaryItems: publishSummary,
        })}
      </div>
    </div>
  );
}

export default AgentWorkspaceToolbar;
