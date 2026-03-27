import type { ReactNode } from 'react';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';

interface ChangeSummaryHoverCardProps {
  /** Button-like trigger content. */
  children: ReactNode;
  /** Heading shown at the top of the summary card. */
  title: string;
  /** One-line explanation for the action. */
  description: string;
  /** Module-level change summary entries. */
  changes: string[];
}

/**
 * Compact hover summary for save and publish actions.
 * Why: the toolbar should explain pending work without forcing users to learn
 * internal state labels like draft or unpublished.
 */
function ChangeSummaryHoverCard({
  children,
  title,
  description,
  changes,
}: ChangeSummaryHoverCardProps) {
  return (
    <HoverCard openDelay={150} closeDelay={100}>
      <HoverCardTrigger asChild>{children}</HoverCardTrigger>
      <HoverCardContent align="end" className="w-96">
        <div className="space-y-3">
          <div className="space-y-1">
            <div className="text-sm font-semibold text-foreground">{title}</div>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>

          {changes.length > 0 ? (
            <ul className="space-y-2">
              {changes.map((change) => (
                <li key={change} className="flex items-start gap-2 text-sm text-foreground">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  <span>{change}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              No pending changes in the current draft.
            </p>
          )}
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

export default ChangeSummaryHoverCard;
