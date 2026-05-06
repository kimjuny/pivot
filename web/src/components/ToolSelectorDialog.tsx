import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Loader2, Inbox, Plus } from "@/lib/lucide";
import { toast } from 'sonner';
import {
  getUsableTools,
  type UsableTool,
} from '../utils/api';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { ButtonGroup } from '@/components/ui/button-group';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import DraggableDialog from './DraggableDialog';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Unified entry shown in the tool table. */
interface ToolEntry {
  name: string;
  /** First non-blank line of the description, for compact display. */
  summary: string;
}

/**
 * Props for ToolSelectorDialog.
 */
interface ToolSelectorDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Callback to open/close the dialog. */
  onOpenChange: (open: boolean) => void;
  /** Agent ID whose configured tools are being edited. */
  agentId: number;
  /**
   * Current serialised tool selection from the agent.
   * ``null`` / ``undefined`` → no tools selected.
   * JSON string, e.g. ``'["add","test_tool"]'`` → explicit selected list.
   */
  currentToolIds: string | null | undefined;
  /** Fired after a successful save with the new ``tool_ids`` value. */
  onSaved: (newToolIds: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract the first meaningful line from a possibly multi-line description. */
function firstLine(desc: string): string {
  return desc.split('\n').find(l => l.trim().length > 0)?.trim() ?? '';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Polished tool selector for an agent.
 *
 * Features:
 * - shadcn Checkbox, Table, Input, Badge, Separator primitives
 * - Live search (filters by tool name)
 * - "Select all / deselect all" across the current filtered view
 * - Enabled count summary in the header action area
 */
function ToolSelectorDialog({
  open,
  onOpenChange,
  agentId,
  currentToolIds,
  onSaved,
}: ToolSelectorDialogProps) {
  const navigate = useNavigate();
  const [allTools, setAllTools] = useState<ToolEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  /** Explicit set of selected tool names. */
  const [checked, setChecked] = useState<Set<string>>(new Set());

  // Search / filter state
  const [searchQuery, setSearchQuery] = useState('');

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadTools = useCallback(async () => {
    setIsLoading(true);
    try {
      const usable = await getUsableTools();
      const merged: ToolEntry[] = usable.map((tool: UsableTool): ToolEntry => ({
        name: tool.name,
        summary: firstLine(tool.description),
      }));
      setAllTools(merged);

      if (currentToolIds === null || currentToolIds === undefined) {
        setChecked(new Set());
      } else {
        try {
          const parsed: unknown = JSON.parse(currentToolIds);
          const names = Array.isArray(parsed)
            ? parsed.filter((item): item is string => typeof item === 'string')
            : [];
          setChecked(new Set(names));
        } catch {
          setChecked(new Set());
        }
      }
    } catch {
      toast.error('Failed to load tools');
    } finally {
      setIsLoading(false);
    }
  }, [currentToolIds]);

  useEffect(() => {
    if (open) {
      setSearchQuery('');
      void loadTools();
    }
  }, [open, loadTools]);

  // ---------------------------------------------------------------------------
  // Filtered view
  // ---------------------------------------------------------------------------

  const filteredTools = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allTools.filter(t => {
      const matchesSearch = !q || t.name.toLowerCase().includes(q) || t.summary.toLowerCase().includes(q);
      return matchesSearch;
    });
  }, [allTools, searchQuery]);

  // ---------------------------------------------------------------------------
  // Toggle helpers
  // ---------------------------------------------------------------------------

  const isToolChecked = (name: string) => checked.has(name);

  const toggleTool = (name: string) => {
    const nextChecked = new Set(checked);
    if (nextChecked.has(name)) nextChecked.delete(name);
    else nextChecked.add(name);
    setChecked(nextChecked);
  };

  /** Check/uncheck all tools visible in the current filtered view. */
  const toggleVisibleAll = () => {
    const visibleNames = filteredTools.map(t => t.name);
    const allVisible = visibleNames.every(n => isToolChecked(n));
    const nextChecked = new Set(checked);

    if (allVisible) {
      // Deselect all visible
      visibleNames.forEach(n => nextChecked.delete(n));
    } else {
      // Select all visible (keep non-visible as-is)
      visibleNames.forEach(n => nextChecked.add(n));
    }
    setChecked(nextChecked);
  };

  // ---------------------------------------------------------------------------
  // Save
  // ---------------------------------------------------------------------------

  const handleSave = () => {
    setIsSaving(true);
    try {
      const newToolIds = JSON.stringify(Array.from(checked).sort());
      onSaved(newToolIds);
      toast.success('Tool selection staged in draft');
      onOpenChange(false);
    } catch {
      toast.error('Failed to stage tool selection');
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenToolsList = () => {
    navigate('/studio/assets/tools');
    onOpenChange(false);
  };

  // ---------------------------------------------------------------------------
  // Derived counts
  // ---------------------------------------------------------------------------

  const visibleAllChecked = filteredTools.length > 0 && filteredTools.every(t => isToolChecked(t.name));
  const visibleSomeChecked = !visibleAllChecked && filteredTools.some(t => isToolChecked(t.name));

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Configure Agent Tools"
      size="default"
    >
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center gap-2 text-sm text-muted-foreground h-full">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading tools…
        </div>
      ) : (
        <div className="flex flex-col h-full">
          {/* ---- Toolbar ---- */}
          <div className="flex flex-col gap-2 px-4 pt-3 pb-2">
            {/* Search — full-width ButtonGroup matching LLMs / Tools list pages */}
            <ButtonGroup className="w-full">
              <Input
                placeholder="Search tools…"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="h-8 text-sm flex-1"
                autoComplete="off"
              />
              <Button variant="outline" size="sm" className="h-8 px-2.5 shrink-0" tabIndex={-1} aria-label="Search">
                <Search className="w-3.5 h-3.5" />
              </Button>
            </ButtonGroup>

          </div>

          <Separator />

          {/* ---- Table ---- */}
          {/* overflow-x-hidden prevents the inner Table from pushing the dialog wider */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden">
            {filteredTools.length === 0 ? (
              allTools.length === 0 ? (
                <div className="flex h-full min-h-64 items-center justify-center px-4 py-6">
                  <Empty className="min-h-64 gap-4 p-4 md:p-6">
                    <EmptyHeader className="gap-1.5">
                      <EmptyMedia variant="icon">
                        <Inbox className="size-5" />
                      </EmptyMedia>
                      <EmptyTitle className="text-base">No tools available</EmptyTitle>
                      <EmptyDescription className="text-xs/relaxed">
                        Add or import a tool first, then configure it for this agent.
                      </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent>
                      <Button type="button" size="sm" onClick={handleOpenToolsList}>
                        <Plus className="size-3.5" />
                        Go to Tools
                      </Button>
                    </EmptyContent>
                  </Empty>
                </div>
              ) : (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  No tools match your search.
                </div>
              )
            ) : (
              <table className="w-full caption-bottom text-sm table-fixed">
                <thead className="sticky top-0 bg-background z-10 [&_tr]:border-b">
                  <tr className="border-b transition-colors">
                    <th className="w-10 h-10 px-3 text-left align-middle font-medium text-muted-foreground">
                      <Checkbox
                        checked={visibleAllChecked ? true : visibleSomeChecked ? 'indeterminate' : false}
                        onCheckedChange={toggleVisibleAll}
                        aria-label="Select all visible tools"
                      />
                    </th>
                    <th className="w-[45%] h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Tool name</th>
                    <th className="h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Description</th>
                  </tr>
                </thead>
                <tbody className="[&_tr:last-child]:border-0">
                  {filteredTools.map(tool => {
                    const isChecked = isToolChecked(tool.name);
                    return (
                      <tr
                        key={tool.name}
                        className="border-b transition-colors hover:bg-muted/50 cursor-pointer data-[state=selected]:bg-muted"
                        onClick={() => toggleTool(tool.name)}
                        data-state={isChecked ? 'selected' : undefined}
                      >
                        <td className="px-3 py-2 align-middle">
                          <Checkbox
                            checked={isChecked}
                            onCheckedChange={() => toggleTool(tool.name)}
                            onClick={e => e.stopPropagation()}
                            aria-label={`Toggle ${tool.name}`}
                          />
                        </td>
                        <td className="px-2 py-2 align-middle overflow-hidden">
                          <span className="font-mono text-xs font-medium block truncate">{tool.name}</span>
                        </td>
                        <td className="px-2 py-2 align-middle overflow-hidden">
                          {tool.summary ? (
                            <span className="text-xs text-muted-foreground block truncate">{tool.summary}</span>
                          ) : (
                            <span className="text-xs text-muted-foreground/40 italic">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          {/* ---- Footer ---- */}
          <Separator />
          <div className="flex items-center justify-end px-4 py-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <span className="tabular-nums">
                {filteredTools.filter(t => isToolChecked(t.name)).length} of {filteredTools.length} shown selected
              </span>
              <Button
                size="sm"
                disabled={isSaving || isLoading}
                onClick={() => void handleSave()}
                className="h-6 text-xs px-3"
              >
                {isSaving ? <><Loader2 className="w-3 h-3 animate-spin mr-1" />Saving…</> : 'Save'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </DraggableDialog>
  );
}

export default ToolSelectorDialog;
