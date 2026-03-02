import { useState, useEffect, useCallback, useMemo } from 'react';
import { Lock, User as UserIcon, Search, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import {
  getSharedTools,
  getPrivateTools,
  updateAgentToolIds,
  type SharedTool,
  type PrivateTool,
} from '../utils/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { ButtonGroup } from '@/components/ui/button-group';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Label } from '@/components/ui/label';
import DraggableDialog from './DraggableDialog';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Unified entry shown in the tool table. */
interface ToolEntry {
  name: string;
  /** First non-blank line of the description, for compact display. */
  summary: string;
  kind: 'shared' | 'private';
}

type FilterKind = 'all' | 'shared' | 'private';

/**
 * Props for ToolSelectorDialog.
 */
interface ToolSelectorDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Callback to open/close the dialog. */
  onOpenChange: (open: boolean) => void;
  /** Agent ID whose tool allowlist is being edited. */
  agentId: number;
  /**
   * Current serialised allowlist from the agent.
   * ``null`` / ``undefined`` → no restriction (all tools enabled).
   * JSON string, e.g. ``'["add","test_tool"]'`` → explicit list.
   */
  currentToolIds: string | null | undefined;
  /** Fired after a successful save with the new ``tool_ids`` value. */
  onSaved: (newToolIds: string | null) => void;
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
 * Polished tool-allowlist editor for an agent.
 *
 * Features:
 * - shadcn Checkbox, Table, Input, Badge, Separator primitives
 * - Live search (filters by tool name)
 * - Kind filter tabs: All / Shared / Private
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
  const [allTools, setAllTools] = useState<ToolEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  /** Explicit set of enabled tool names. Sync'd with ``allowAll``. */
  const [checked, setChecked] = useState<Set<string>>(new Set());
  /**
   * When true the agent has unrestricted access (``tool_ids === null``).
   * Visually every row appears checked; on save we send ``null``.
   */
  const [allowAll, setAllowAll] = useState(true);

  // Search / filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [filterKind, setFilterKind] = useState<FilterKind>('all');

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadTools = useCallback(async () => {
    setIsLoading(true);
    try {
      const [shared, priv] = await Promise.all([getSharedTools(), getPrivateTools()]);
      const merged: ToolEntry[] = [
        ...shared.map((t: SharedTool): ToolEntry => ({
          name: t.name,
          summary: firstLine(t.description),
          kind: 'shared',
        })),
        ...priv.map((t: PrivateTool): ToolEntry => ({
          name: t.name,
          summary: '',
          kind: 'private',
        })),
      ];
      setAllTools(merged);

      if (currentToolIds === null || currentToolIds === undefined) {
        setAllowAll(true);
        setChecked(new Set(merged.map(t => t.name)));
      } else {
        setAllowAll(false);
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
      setFilterKind('all');
      void loadTools();
    }
  }, [open, loadTools]);

  // ---------------------------------------------------------------------------
  // Filtered view
  // ---------------------------------------------------------------------------

  const filteredTools = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allTools.filter(t => {
      const matchesKind = filterKind === 'all' || t.kind === filterKind;
      const matchesSearch = !q || t.name.toLowerCase().includes(q) || t.summary.toLowerCase().includes(q);
      return matchesKind && matchesSearch;
    });
  }, [allTools, searchQuery, filterKind]);

  // ---------------------------------------------------------------------------
  // Toggle helpers
  // ---------------------------------------------------------------------------

  const isToolChecked = (name: string) => allowAll || checked.has(name);

  const toggleTool = (name: string) => {
    // Clicking any row exits "allow-all" mode and enters explicit mode.
    const nextChecked = new Set(checked);
    if (allowAll) {
      // Start from "everything" then uncheck this one
      allTools.forEach(t => nextChecked.add(t.name));
      nextChecked.delete(name);
      setAllowAll(false);
    } else {
      if (nextChecked.has(name)) nextChecked.delete(name);
      else nextChecked.add(name);
    }
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
      setAllowAll(false);
    } else {
      // Select all visible (keep non-visible as-is)
      visibleNames.forEach(n => nextChecked.add(n));
      // If no filter is active and all are now checked, re-enter allow-all mode
      const unfiltered = !searchQuery.trim() && filterKind === 'all';
      if (unfiltered && nextChecked.size === allTools.length) {
        setAllowAll(true);
      } else {
        setAllowAll(false);
      }
    }
    setChecked(nextChecked);
  };

  // ---------------------------------------------------------------------------
  // Save
  // ---------------------------------------------------------------------------

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const newToolIds = allowAll ? null : Array.from(checked);
      const updated = await updateAgentToolIds(agentId, newToolIds);
      onSaved(updated.tool_ids ?? null);
      toast.success('Tool allowlist saved');
      onOpenChange(false);
    } catch {
      toast.error('Failed to save tool allowlist');
    } finally {
      setIsSaving(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Derived counts
  // ---------------------------------------------------------------------------

  const enabledCount = allowAll ? allTools.length : checked.size;
  const visibleAllChecked = filteredTools.length > 0 && filteredTools.every(t => isToolChecked(t.name));
  const visibleSomeChecked = !visibleAllChecked && filteredTools.some(t => isToolChecked(t.name));

  const kindCounts = useMemo(() => ({
    all: allTools.length,
    shared: allTools.filter(t => t.kind === 'shared').length,
    private: allTools.filter(t => t.kind === 'private').length,
  }), [allTools]);

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

            {/* Kind filter — official shadcn Tabs */}
            <Tabs value={filterKind} onValueChange={v => setFilterKind(v as FilterKind)}>
              <TabsList className="h-7 p-0.5 gap-0.5">
                <TabsTrigger value="all" className="h-6 px-2.5 text-xs gap-1">
                  All
                  <span className="tabular-nums text-[10px] opacity-70">{kindCounts.all}</span>
                </TabsTrigger>
                <TabsTrigger value="shared" className="h-6 px-2.5 text-xs gap-1">
                  <Lock className="w-3 h-3" />Shared
                  <span className="tabular-nums text-[10px] opacity-70">{kindCounts.shared}</span>
                </TabsTrigger>
                <TabsTrigger value="private" className="h-6 px-2.5 text-xs gap-1">
                  <UserIcon className="w-3 h-3" />Private
                  <span className="tabular-nums text-[10px] opacity-70">{kindCounts.private}</span>
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <Separator />

          {/* ---- Table ---- */}
          {/* overflow-x-hidden prevents the inner Table from pushing the dialog wider */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden">
            {filteredTools.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-sm text-muted-foreground">
                {allTools.length === 0 ? 'No tools available.' : 'No tools match your search.'}
              </div>
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
                    <th className="w-[38%] h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Tool name</th>
                    <th className="w-[22%] h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Type</th>
                    <th className="h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Description</th>
                  </tr>
                </thead>
                <tbody className="[&_tr:last-child]:border-0">
                  {filteredTools.map(tool => {
                    const isChecked = isToolChecked(tool.name);
                    return (
                      <tr
                        key={`${tool.kind}-${tool.name}`}
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
                        <td className="px-2 py-2 align-middle">
                          {tool.kind === 'shared' ? (
                            <Badge variant="secondary" className="gap-1 text-[10px] px-1.5 h-5 whitespace-nowrap">
                              <Lock className="w-2.5 h-2.5" />Shared
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="gap-1 text-[10px] px-1.5 h-5 whitespace-nowrap">
                              <UserIcon className="w-2.5 h-2.5" />Private
                            </Badge>
                          )}
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
          <div className="flex items-center justify-between px-4 py-2 text-xs text-muted-foreground">
            {/* Left: allow-all shortcut */}
            <Label className="flex items-center gap-1.5 cursor-pointer select-none font-normal" onClick={() => {
              if (allowAll) {
                setAllowAll(false);
                setChecked(new Set());
              } else {
                setAllowAll(true);
                setChecked(new Set(allTools.map(t => t.name)));
              }
            }}>
              <Checkbox
                checked={allowAll}
                onCheckedChange={v => {
                  if (v) {
                    setAllowAll(true);
                    setChecked(new Set(allTools.map(t => t.name)));
                  } else {
                    setAllowAll(false);
                  }
                }}
                onClick={e => e.stopPropagation()}
              />
              Allow all
            </Label>

            {/* Right: count + Save fused */}
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
