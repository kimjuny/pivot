import { Badge } from '@/components/ui/badge';

interface ReleaseSummarySectionsProps {
  /** Flat summary lines returned by the backend release diff. */
  summary: string[];
  /** Compact mode keeps spacing tighter for dense history cards. */
  compact?: boolean;
}

interface SummarySection {
  key: string;
  label: string;
  items: string[];
}

/**
 * Group flat release-summary lines into stable audit sections.
 * Why: publish and history views should show users which product surface
 * changed, not just a long undifferentiated list of sentences.
 */
function groupReleaseSummary(summary: string[]): SummarySection[] {
  const sections: SummarySection[] = [
    { key: 'basics', label: 'Basics', items: [] },
    { key: 'runtime', label: 'Runtime', items: [] },
    { key: 'workflow', label: 'Workflow', items: [] },
    { key: 'capabilities', label: 'Capabilities', items: [] },
    { key: 'connections', label: 'Connections', items: [] },
    { key: 'general', label: 'General', items: [] },
  ];

  const pickSection = (item: string): SummarySection => {
    if (item.startsWith('Agent basics')) {
      return sections[0];
    }
    if (item.startsWith('Runtime settings')) {
      return sections[1];
    }
    if (item.startsWith('Scenes ') || item.startsWith('Scene ')) {
      return sections[2];
    }
    if (
      item.startsWith('Tools ') ||
      item.startsWith('Tool ') ||
      item.startsWith('Skills ') ||
      item.startsWith('Skill ')
    ) {
      return sections[3];
    }
    if (
      item.startsWith('Channel bindings ') ||
      item.startsWith('Channel binding ') ||
      item.startsWith('Web search providers ') ||
      item.startsWith('Web search provider ')
    ) {
      return sections[4];
    }
    return sections[5];
  };

  for (const item of summary) {
    pickSection(item).items.push(item);
  }

  return sections.filter((section) => section.items.length > 0);
}

/**
 * Structured release-summary renderer used by publish and history dialogs.
 */
function ReleaseSummarySections({
  summary,
  compact = false,
}: ReleaseSummarySectionsProps) {
  const sections = groupReleaseSummary(summary);

  if (sections.length === 0) {
    return null;
  }

  return (
    <div className={compact ? 'space-y-2.5' : 'space-y-3'}>
      {sections.map((section) => (
        <div
          key={section.key}
          className={compact ? 'space-y-1.5' : 'space-y-2'}
        >
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="h-5 px-1.5 text-[10px] uppercase tracking-[0.14em]">
              {section.label}
            </Badge>
            <span className="text-[11px] text-muted-foreground">
              {section.items.length}
            </span>
          </div>

          <ul className={compact ? 'space-y-1' : 'space-y-1.5'}>
            {section.items.map((item) => (
              <li
                key={`${section.key}-${item}`}
                className={compact ? 'text-xs text-muted-foreground' : 'text-sm text-foreground'}
              >
                {item}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export default ReleaseSummarySections;
