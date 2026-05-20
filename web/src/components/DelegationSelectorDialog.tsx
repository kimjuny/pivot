import { useState, useEffect, useCallback, useMemo } from 'react';
import { Search, Loader2, Inbox } from 'lucide-react';
import { toast } from 'sonner';
import {
  getAgentDelegations,
  replaceAgentDelegations,
  getAgents,
} from '../utils/api';
import type { AgentDelegation } from '../types';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { ButtonGroup } from '@/components/ui/button-group';
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

/** An agent available for delegation selection. */
interface AgentEntry {
  id: number;
  name: string;
  description: string | null;
  llm_id: number | null;
  client_state?: string;
}

interface DelegationSelectorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  /** Exclude this agent ID from the selection list (the caller itself). */
  excludeAgentId?: number;
  /** Called after delegations are successfully saved. */
  onSaved?: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function firstLine(desc: string | null | undefined): string {
  if (!desc) return '';
  return desc.split('\n').find(l => l.trim().length > 0)?.trim() ?? '';
}

function generateAlias(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 32);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Agent delegation selector dialog.
 *
 * Mirrors the ToolSelectorDialog interaction model for consistency.
 * Allows selecting which agents the current agent can delegate to.
 */
function DelegationSelectorDialog({
  open,
  onOpenChange,
  agentId,
  excludeAgentId,
  onSaved,
}: DelegationSelectorDialogProps) {
  const [existingDelegations, setExistingDelegations] = useState<AgentDelegation[]>([]);
  const [availableAgents, setAvailableAgents] = useState<AgentEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [delegations, allAgents] = await Promise.all([
        getAgentDelegations(agentId),
        getAgents(),
      ]);
      setExistingDelegations(delegations);
      setChecked(new Set(delegations.filter(d => d.enabled).map(d => d.callee_agent_id)));
      setAvailableAgents(
        allAgents
          .filter(a => a.id !== excludeAgentId)
          .map(a => ({
            id: a.id,
            name: a.name,
            description: a.description ?? null,
            llm_id: a.llm_id ?? null,
            client_state: a.client_state,
          }))
      );
    } catch {
      toast.error('Failed to load delegations');
    } finally {
      setIsLoading(false);
    }
  }, [agentId, excludeAgentId]);

  useEffect(() => {
    if (open) {
      setSearchQuery('');
      void loadData();
    }
  }, [open, loadData]);

  // ---------------------------------------------------------------------------
  // Filtered view
  // ---------------------------------------------------------------------------

  const filteredAgents = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return availableAgents.filter(a => {
      if (!q) return true;
      return (
        a.name.toLowerCase().includes(q) ||
        (a.description ?? '').toLowerCase().includes(q)
      );
    });
  }, [availableAgents, searchQuery]);

  // ---------------------------------------------------------------------------
  // Toggle helpers
  // ---------------------------------------------------------------------------

  const isAgentChecked = (id: number) => checked.has(id);

  const toggleAgent = (id: number) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  };

  const toggleVisibleAll = () => {
    const visibleIds = filteredAgents.map(a => a.id);
    const allVisible = visibleIds.every(id => isAgentChecked(id));
    const next = new Set(checked);
    if (allVisible) {
      visibleIds.forEach(id => next.delete(id));
    } else {
      visibleIds.forEach(id => next.add(id));
    }
    setChecked(next);
  };

  // ---------------------------------------------------------------------------
  // Save
  // ---------------------------------------------------------------------------

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const items = Array.from(checked).map(calleeId => {
        const agent = availableAgents.find(a => a.id === calleeId);
        const existing = existingDelegations.find(d => d.callee_agent_id === calleeId);
        return {
          callee_agent_id: calleeId,
          callee_alias: existing?.callee_alias ?? generateAlias(agent?.name ?? `agent_${calleeId}`),
          description_override: existing?.description_override ?? null,
          pass_mode: existing?.pass_mode ?? 'instruction_only',
          max_timeout_seconds: existing?.max_timeout_seconds ?? 300,
          max_iterations_override: existing?.max_iterations_override ?? null,
          enabled: true,
          priority: existing?.priority ?? 100,
        };
      });
      await replaceAgentDelegations(agentId, items);
      toast.success('Delegation configuration saved');
      onOpenChange(false);
      await onSaved?.();
    } catch {
      toast.error('Failed to save delegations');
    } finally {
      setIsSaving(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Derived counts
  // ---------------------------------------------------------------------------

  const visibleAllChecked = filteredAgents.length > 0 && filteredAgents.every(a => isAgentChecked(a.id));
  const visibleSomeChecked = !visibleAllChecked && filteredAgents.some(a => isAgentChecked(a.id));

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Configure Agent Delegations"
      size="default"
    >
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center gap-2 text-sm text-muted-foreground h-full">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading delegations…
        </div>
      ) : (
        <div className="flex flex-col h-full">
          {/* Search */}
          <div className="flex flex-col gap-2 px-4 pt-3 pb-2">
            <ButtonGroup className="w-full">
              <Input
                placeholder="Search agents…"
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

          {/* Table */}
          <div className="flex-1 overflow-y-auto overflow-x-hidden">
            {filteredAgents.length === 0 ? (
              availableAgents.length === 0 ? (
                <div className="flex h-full min-h-64 items-center justify-center px-4 py-6">
                  <Empty className="min-h-64 gap-4 p-4 md:p-6">
                    <EmptyHeader className="gap-1.5">
                      <EmptyMedia variant="icon">
                        <Inbox className="size-5" />
                      </EmptyMedia>
                      <EmptyTitle className="text-base">No agents available</EmptyTitle>
                      <EmptyDescription className="text-xs/relaxed">
                        Create another agent first, then configure delegation here.
                      </EmptyDescription>
                    </EmptyHeader>
                  </Empty>
                </div>
              ) : (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  No agents match your search.
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
                        aria-label="Select all visible agents"
                      />
                    </th>
                    <th className="w-[30%] h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Name</th>
                    <th className="h-10 px-2 text-left align-middle text-xs font-medium text-muted-foreground">Description</th>
                  </tr>
                </thead>
                <tbody className="[&_tr:last-child]:border-0">
                  {filteredAgents.map(agent => {
                    const isChecked = isAgentChecked(agent.id);
                    return (
                      <tr
                        key={agent.id}
                        className="border-b transition-colors hover:bg-muted/50 cursor-pointer data-[state=selected]:bg-muted"
                        onClick={() => toggleAgent(agent.id)}
                        data-state={isChecked ? 'selected' : undefined}
                      >
                        <td className="px-3 py-2 align-middle">
                          <Checkbox
                            checked={isChecked}
                            onCheckedChange={() => toggleAgent(agent.id)}
                            onClick={e => e.stopPropagation()}
                            aria-label={`Toggle ${agent.name}`}
                          />
                        </td>
                        <td className="px-2 py-2 align-middle overflow-hidden">
                          <span className="text-xs font-medium block truncate">{agent.name}</span>
                        </td>
                        <td className="px-2 py-2 align-middle overflow-hidden">
                          {agent.description ? (
                            <span className="text-xs text-muted-foreground block truncate">
                              {firstLine(agent.description)}
                            </span>
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

          {/* Footer */}
          <Separator />
          <div className="flex items-center justify-end px-4 py-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
              <span className="tabular-nums">
                {filteredAgents.filter(a => isAgentChecked(a.id)).length} of {filteredAgents.length} shown selected
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

export default DelegationSelectorDialog;
