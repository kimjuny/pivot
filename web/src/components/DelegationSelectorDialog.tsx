import { useState, useEffect, useCallback, useMemo } from 'react';
import { Search, Loader2, Inbox, Settings2, ChevronRight } from 'lucide-react';
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

/** Per-row configuration state for a checked delegation. */
interface DelegationRowConfig {
  callee_alias: string;
  description_override: string;
  max_timeout_seconds: number;
  /** String for empty-state handling; parsed to number|null on save. */
  max_iterations_override: string;
}

interface DelegationRowState {
  checked: boolean;
  config: DelegationRowConfig;
  configExpanded: boolean;
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

function makeDefaultConfig(agentName: string): DelegationRowConfig {
  return {
    callee_alias: generateAlias(agentName),
    description_override: '',
    max_timeout_seconds: 300,
    max_iterations_override: '',
  };
}

function configFromExisting(existing: AgentDelegation): DelegationRowConfig {
  return {
    callee_alias: existing.callee_alias,
    description_override: existing.description_override ?? '',
    max_timeout_seconds: existing.max_timeout_seconds,
    max_iterations_override: existing.max_iterations_override != null
      ? String(existing.max_iterations_override)
      : '',
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Agent delegation selector dialog with per-row configuration.
 *
 * Allows selecting which agents the current agent can delegate to and
 * configuring per-delegation settings (alias, description, timeout,
 * max iterations).
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
  const [rowStates, setRowStates] = useState<Map<number, DelegationRowState>>(new Map());
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

      // Build initial row states from existing delegations.
      const initial = new Map<number, DelegationRowState>();
      for (const d of delegations) {
        if (d.enabled) {
          initial.set(d.callee_agent_id, {
            checked: true,
            config: configFromExisting(d),
            configExpanded: false,
          });
        }
      }
      setRowStates(initial);
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

  const isAgentChecked = (id: number) => rowStates.get(id)?.checked === true;

  const toggleAgent = (id: number) => {
    setRowStates(prev => {
      const next = new Map(prev);
      const current = next.get(id);
      if (current?.checked) {
        next.delete(id);
      } else {
        const agent = availableAgents.find(a => a.id === id);
        const existing = existingDelegations.find(d => d.callee_agent_id === id);
        next.set(id, {
          checked: true,
          config: existing ? configFromExisting(existing) : makeDefaultConfig(agent?.name ?? `agent_${id}`),
          configExpanded: false,
        });
      }
      return next;
    });
  };

  const toggleVisibleAll = () => {
    const visibleIds = filteredAgents.map(a => a.id);
    const allVisible = visibleIds.every(id => isAgentChecked(id));
    setRowStates(prev => {
      const next = new Map(prev);
      if (allVisible) {
        for (const id of visibleIds) {
          next.delete(id);
        }
      } else {
        for (const id of visibleIds) {
          if (!next.has(id)) {
            const agent = availableAgents.find(a => a.id === id);
            const existing = existingDelegations.find(d => d.callee_agent_id === id);
            next.set(id, {
              checked: true,
              config: existing ? configFromExisting(existing) : makeDefaultConfig(agent?.name ?? `agent_${id}`),
              configExpanded: false,
            });
          }
        }
      }
      return next;
    });
  };

  const toggleConfigExpanded = (id: number) => {
    setRowStates(prev => {
      const current = prev.get(id);
      if (!current) return prev;
      const next = new Map(prev);
      next.set(id, { ...current, configExpanded: !current.configExpanded });
      return next;
    });
  };

  const updateConfig = (id: number, patch: Partial<DelegationRowConfig>) => {
    setRowStates(prev => {
      const current = prev.get(id);
      if (!current) return prev;
      const next = new Map(prev);
      next.set(id, { ...current, config: { ...current.config, ...patch } });
      return next;
    });
  };

  // ---------------------------------------------------------------------------
  // Save
  // ---------------------------------------------------------------------------

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const items = Array.from(rowStates.entries())
        .filter(([, state]) => state.checked)
        .map(([calleeId, state]) => ({
          callee_agent_id: calleeId,
          callee_alias: state.config.callee_alias,
          description_override: state.config.description_override || null,
          pass_mode: 'instruction_only' as const,
          max_timeout_seconds: state.config.max_timeout_seconds,
          max_iterations_override: state.config.max_iterations_override
            ? Number(state.config.max_iterations_override)
            : null,
          enabled: true,
          priority: 100,
        }));
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
  const selectedCount = filteredAgents.filter(a => isAgentChecked(a.id)).length;

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
              <table className="w-full caption-bottom text-sm">
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
                    <th className="w-10 h-10 px-2 text-right align-middle font-medium text-muted-foreground" />
                  </tr>
                </thead>
                <tbody className="[&_tr:last-child]:border-0">
                  {filteredAgents.map(agent => {
                    const state = rowStates.get(agent.id);
                    const isChecked = state?.checked === true;
                    const isExpanded = state?.configExpanded === true;
                    const config = state?.config;

                    return (
                      <AgentRow
                        key={agent.id}
                        agent={agent}
                        isChecked={isChecked}
                        isExpanded={isExpanded}
                        config={config}
                        onToggle={() => toggleAgent(agent.id)}
                        onToggleConfig={() => toggleConfigExpanded(agent.id)}
                        onUpdateConfig={patch => updateConfig(agent.id, patch)}
                      />
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
                {selectedCount} of {filteredAgents.length} shown selected
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

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Config section rendered below a checked row. */
function ConfigSection({
  config,
  onUpdate,
}: {
  config: DelegationRowConfig;
  onUpdate: (patch: Partial<DelegationRowConfig>) => void;
}) {
  return (
    <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 px-3 py-2 text-xs">
      <label className="flex items-center text-muted-foreground whitespace-nowrap">Alias</label>
      <Input
        value={config.callee_alias}
        onChange={e => onUpdate({ callee_alias: e.target.value })}
        className="h-6 text-xs"
        placeholder="agent_alias"
      />
      <label className="flex items-center text-muted-foreground whitespace-nowrap">Description</label>
      <Input
        value={config.description_override}
        onChange={e => onUpdate({ description_override: e.target.value })}
        className="h-6 text-xs"
        placeholder="Custom description (optional)"
      />
      <label className="flex items-center text-muted-foreground whitespace-nowrap">Timeout</label>
      <div className="flex items-center gap-1.5">
        <Input
          type="number"
          value={config.max_timeout_seconds}
          onChange={e => onUpdate({ max_timeout_seconds: Math.max(10, Number(e.target.value) || 300) })}
          className="h-6 w-20 text-xs"
          min={10}
        />
        <span className="text-muted-foreground">sec</span>
        <span className="mx-2 text-muted-foreground/40">|</span>
        <span className="text-muted-foreground whitespace-nowrap">Max Iterations</span>
        <Input
          type="number"
          value={config.max_iterations_override}
          onChange={e => onUpdate({ max_iterations_override: e.target.value })}
          className="h-6 w-20 text-xs"
          placeholder="Default"
          min={1}
        />
      </div>
    </div>
  );
}

/** One row in the delegation agent table, with optional expandable config. */
function AgentRow({
  agent,
  isChecked,
  isExpanded,
  config,
  onToggle,
  onToggleConfig,
  onUpdateConfig,
}: {
  agent: AgentEntry;
  isChecked: boolean;
  isExpanded: boolean;
  config: DelegationRowConfig | undefined;
  onToggle: () => void;
  onToggleConfig: () => void;
  onUpdateConfig: (patch: Partial<DelegationRowConfig>) => void;
}) {
  return (
    <>
      <tr
        className={`border-b transition-colors hover:bg-muted/50 cursor-pointer ${isChecked ? 'bg-muted/30' : ''}`}
        onClick={onToggle}
        data-state={isChecked ? 'selected' : undefined}
      >
        <td className="px-3 py-2 align-middle">
          <Checkbox
            checked={isChecked}
            onCheckedChange={onToggle}
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
        <td className="w-10 px-2 py-2 align-middle text-right">
          {isChecked && (
            <button
              type="button"
              className={`inline-flex items-center justify-center rounded p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground ${isExpanded ? 'text-foreground' : ''}`}
              onClick={e => {
                e.stopPropagation();
                onToggleConfig();
              }}
              aria-label={`Configure ${agent.name}`}
            >
              <ChevronRight className={`w-3.5 h-3.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
            </button>
          )}
        </td>
      </tr>
      {isChecked && isExpanded && config && (
        <tr className="border-b bg-muted/15">
          <td colSpan={4} className="p-0">
            <ConfigSection config={config} onUpdate={onUpdateConfig} />
          </td>
        </tr>
      )}
    </>
  );
}

export default DelegationSelectorDialog;
