import { useState, useEffect, useCallback, useMemo, MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Plus,
  Bot,
  CheckCircle2,
  Loader2,
  MoreHorizontal,
  Pencil,
  Trash2,
  X,
  XCircle,
} from "@/lib/lucide";
import { toast } from 'sonner';
import {
  getAgents,
  deleteAgent,
  updateAgent,
  createAgent,
  updateAgentServing,
  AuthError,
} from '../utils/api';
import { formatTimestamp } from '../utils/timestamp';
import type { Agent } from '../types';
import AgentModal from './AgentModal';
import ConfirmationModal from './ConfirmationModal';
import { LLMBrandAvatar } from './LLMBrandAvatar';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { CenteredLoadingIndicator } from '@/components/CenteredLoadingIndicator';
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

// ---------------------------------------------------------------------------
// Pagination helper
// ---------------------------------------------------------------------------

function buildPageList(current: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | 'ellipsis')[] = [1];
  if (current > 3) pages.push('ellipsis');
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) pages.push(i);
  if (current < total - 2) pages.push('ellipsis');
  pages.push(total);
  return pages;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Agent list page.
 * Displays agents in a card grid with search, pagination, and CRUD operations.
 * Header layout matches the LLMs and Tools list pages for visual consistency.
 */
function AgentList() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [servingAgentIds, setServingAgentIds] = useState<number[]>([]);
  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    agent: Agent | null;
  }>({ isOpen: false, agent: null });
  const navigate = useNavigate();

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadAgents = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getAgents();
      setAgents(data);
    } catch (err) {
      if (err instanceof AuthError) return;
      setError((err as Error).message || 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  // ---------------------------------------------------------------------------
  // Filter + pagination
  // ---------------------------------------------------------------------------

  const activeCount = useMemo(() => agents.filter(a => a.is_active).length, [agents]);
  const inactiveCount = agents.length - activeCount;

  const filteredAgents = useMemo(() => {
    const q = searchQuery.toLowerCase();
    return agents.filter(a => {
      if (statusFilter === 'active' && !a.is_active) return false;
      if (statusFilter === 'inactive' && a.is_active) return false;
      if (!q) return true;
      return a.name.toLowerCase().includes(q) || (a.description && a.description.toLowerCase().includes(q));
    });
  }, [agents, searchQuery, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredAgents.length / PAGE_SIZE));

  useEffect(() => { setCurrentPage(1); }, [searchQuery, statusFilter]);

  const pagedAgents = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredAgents.slice(start, start + PAGE_SIZE);
  }, [filteredAgents, currentPage]);

  // ---------------------------------------------------------------------------
  // CRUD handlers
  // ---------------------------------------------------------------------------

  const handleCreateAgent = () => {
    setModalMode('create');
    setEditingAgent(null);
    setIsModalOpen(true);
  };

  const handleEditAgent = (agent: Agent, e: MouseEvent) => {
    e.stopPropagation();
    setModalMode('edit');
    setEditingAgent(agent);
    setIsModalOpen(true);
  };

  const handleDeleteAgent = (agent: Agent, e: MouseEvent) => {
    e.stopPropagation();
    setDeleteConfirmation({ isOpen: true, agent });
  };

  const handleServingToggle = async (agent: Agent, e: MouseEvent) => {
    e.stopPropagation();
    setServingAgentIds(previous => [...previous, agent.id]);
    try {
      const nextServingEnabled = agent.serving_enabled === false;
      const updatedAgent = await updateAgentServing(agent.id, nextServingEnabled);
      setAgents(previous =>
        previous.map(existing => (existing.id === updatedAgent.id ? updatedAgent : existing)),
      );
      toast.success(nextServingEnabled ? 'Agent enabled' : 'Agent disabled');
    } catch (err) {
      toast.error(`Failed to update availability: ${(err as Error).message}`);
    } finally {
      setServingAgentIds(previous => previous.filter(id => id !== agent.id));
    }
  };

  const confirmDeleteAgent = async () => {
    if (!deleteConfirmation.agent) return;
    try {
      await deleteAgent(deleteConfirmation.agent.id);
      setDeleteConfirmation({ isOpen: false, agent: null });
      toast.success('Agent deleted');
      await loadAgents();
    } catch (err) {
      toast.error(`Failed to delete: ${(err as Error).message}`);
      setDeleteConfirmation({ isOpen: false, agent: null });
    }
  };

  const handleModalSave = async (agentData: {
    name: string;
    description?: string;
    llm_id: number | undefined;
    session_idle_timeout_minutes: number;
    sandbox_timeout_seconds: number;
    compact_threshold_percent: number;
    max_iteration: number;
  }) => {
    if (modalMode === 'create') {
      if (!agentData.llm_id) { toast.error('LLM selection is required'); return; }
      const newAgent = await createAgent({
        name: agentData.name,
        description: agentData.description,
        llm_id: agentData.llm_id,
        session_idle_timeout_minutes: agentData.session_idle_timeout_minutes,
        sandbox_timeout_seconds: agentData.sandbox_timeout_seconds,
        compact_threshold_percent: agentData.compact_threshold_percent,
        max_iteration: agentData.max_iteration,
      });
      toast.success('Agent created');
      navigate(`/studio/agents/${newAgent.id}`);
    } else if (modalMode === 'edit' && editingAgent) {
      await updateAgent(editingAgent.id, {
        name: agentData.name,
        description: agentData.description,
        llm_id: agentData.llm_id,
        session_idle_timeout_minutes: agentData.session_idle_timeout_minutes,
        sandbox_timeout_seconds: agentData.sandbox_timeout_seconds,
        compact_threshold_percent: agentData.compact_threshold_percent,
        max_iteration: agentData.max_iteration,
      });
      toast.success('Agent updated');
      await loadAgents();
    }
  };

  const handleAgentClick = (agent: Agent) => navigate(`/studio/agents/${agent.id}`);
  const handleCardKeyDown = (e: React.KeyboardEvent, agent: Agent) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handleAgentClick(agent); }
  };

  // ---------------------------------------------------------------------------
  // Render states
  // ---------------------------------------------------------------------------

  if (loading) {
    return <CenteredLoadingIndicator className="h-screen" label="Loading agents" />;
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-background">
        <div className="text-xl text-destructive mb-4 font-medium">Error: {error}</div>
        <Button onClick={() => void loadAgents()}>Retry</Button>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Main render
  // ---------------------------------------------------------------------------

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Page header — same layout as LLMs and Tools pages */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Agents</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Create and manage your AI agents.
          </p>
        </div>
        <Button size="sm" onClick={handleCreateAgent} className="flex items-center gap-1.5">
          <Plus className="w-4 h-4" />
          New
        </Button>
      </div>

      {/* Filter + search bar */}
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        {/* Status badge filters */}
        <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap">
          {(
            [
              { value: 'all', label: 'All', count: agents.length },
              { value: 'active', label: 'Active', count: activeCount },
              { value: 'inactive', label: 'Inactive', count: inactiveCount },
            ] as const
          ).map(({ value, label, count }) => (
            <button
              key={value}
              onClick={() => setStatusFilter(value)}
              className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
            >
              <Badge
                variant={statusFilter === value ? 'default' : 'outline'}
                className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                  statusFilter === value ? 'list-filter-badge-active' : ''
                }`}
              >
                {label}
                <span className={statusFilter === value ? 'opacity-70' : 'text-muted-foreground'}>
                  {count}
                </span>
              </Badge>
            </button>
          ))}
          {statusFilter !== 'all' && (
            <button
              onClick={() => setStatusFilter('all')}
              className="text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Clear filter"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        {/* Search */}
        <ButtonGroup className="list-search-group">
          <Input
            placeholder="Search by name or description…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            aria-label="Search agents"
            autoComplete="off"
          />
          <Button variant="outline" size="sm" aria-label="Search agents" tabIndex={-1}>
            Search
          </Button>
        </ButtonGroup>
      </div>

      {/* Empty states */}
      {filteredAgents.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
          {agents.length === 0 ? (
            <>
              <p className="text-sm">No agents yet.</p>
              <Button size="sm" variant="outline" onClick={handleCreateAgent}>
                <Plus className="w-4 h-4 mr-1.5" />
                Create your first agent
              </Button>
            </>
          ) : (
            <p className="text-sm">No agents match your search.</p>
          )}
        </div>
      ) : (
        <>
          {/* Agent card grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
            {pagedAgents.map(agent => {
              const isPublished = agent.active_release_id != null;
              const isServingEnabled = agent.serving_enabled !== false;
              const isServingPending = servingAgentIds.includes(agent.id);

              return (
                <Card
                  key={agent.id}
                  onClick={() => handleAgentClick(agent)}
                  onKeyDown={e => handleCardKeyDown(e, agent)}
                  className="cursor-pointer transition-colors duration-150 hover:bg-accent/50 relative group p-3 flex flex-col min-h-[120px]"
                  role="button"
                  tabIndex={0}
                  aria-label={`Open agent ${agent.name}`}
                >
                  {/* Top: icon + name + menu */}
                  <div className="flex items-start gap-2">
                    <LLMBrandAvatar
                      model={agent.model_name}
                      containerClassName="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5"
                      imageClassName="w-3.5 h-3.5"
                      fallback={<Bot className="w-3.5 h-3.5 text-primary" aria-hidden="true" />}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1">
                        <span className="font-medium text-sm truncate leading-tight">{agent.name}</span>
                        <span
                          className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${agent.is_active ? 'bg-primary' : 'bg-muted-foreground/40'}`}
                          aria-hidden="true"
                        />
                      </div>
                      <div className="text-[11px] text-muted-foreground truncate leading-tight mt-0.5">
                        {formatTimestamp(agent.updated_at)}
                      </div>
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity flex-shrink-0 -mr-0.5 -mt-0.5"
                          onClick={e => e.stopPropagation()}
                          aria-label="Agent options"
                        >
                          <MoreHorizontal className="w-3 h-3" aria-hidden="true" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        size="medium"
                        onClick={e => e.stopPropagation()}
                      >
                        <DropdownMenuItem
                          onClick={e => void handleServingToggle(agent, e as unknown as MouseEvent)}
                          disabled={isServingPending}
                        >
                          {isServingPending ? (
                            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                          ) : isServingEnabled ? (
                            <XCircle className="w-4 h-4" aria-hidden="true" />
                          ) : (
                            <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                          )}
                          {isServingEnabled ? 'Disable' : 'Enable'}
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={e => handleEditAgent(agent, e as unknown as MouseEvent)}>
                          <Pencil className="w-4 h-4" aria-hidden="true" />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={e => handleDeleteAgent(agent, e as unknown as MouseEvent)}
                          className="text-destructive focus:text-destructive"
                        >
                          <Trash2 className="w-4 h-4" aria-hidden="true" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>

                  {/* Description */}
                  <div className="flex-1 mt-2 min-h-0">
                    {agent.description && (
                      <p className="text-[11px] text-muted-foreground line-clamp-2 leading-relaxed">
                        {agent.description}
                      </p>
                    )}
                  </div>

                  {/* Bottom: badges */}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {isPublished && agent.active_release_version != null && (
                      <Badge
                        variant="default"
                        className="text-[10px] px-1.5 py-0 h-4"
                      >
                        v{agent.active_release_version}
                      </Badge>
                    )}
                    <Badge
                      variant="outline"
                      className={`text-[10px] px-1.5 py-0 h-4 ${
                        isServingEnabled
                          ? 'border-emerald-500/30 text-emerald-700 dark:text-emerald-300'
                          : 'border-amber-500/30 text-amber-700 dark:text-amber-300'
                      }`}
                    >
                      {isServingEnabled ? 'Enabled' : 'Disabled'}
                    </Badge>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 max-w-full truncate">
                      {agent.model_name || 'No LLM'}
                    </Badge>
                  </div>
                </Card>
              );
            })}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {filteredAgents.length} agent{filteredAgents.length !== 1 ? 's' : ''}
                {searchQuery ? ' found' : ' total'}
              </span>
              <Pagination className="w-auto mx-0 justify-end">
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      href="#"
                      onClick={e => { e.preventDefault(); if (currentPage > 1) setCurrentPage(p => p - 1); }}
                      className={currentPage === 1 ? 'pointer-events-none opacity-50' : ''}
                    />
                  </PaginationItem>
                  {buildPageList(currentPage, totalPages).map((page, idx) =>
                    page === 'ellipsis' ? (
                      <PaginationItem key={`ellipsis-${idx}`}>
                        <PaginationEllipsis />
                      </PaginationItem>
                    ) : (
                      <PaginationItem key={page}>
                        <PaginationLink
                          href="#"
                          isActive={page === currentPage}
                          onClick={e => { e.preventDefault(); setCurrentPage(page); }}
                        >
                          {page}
                        </PaginationLink>
                      </PaginationItem>
                    )
                  )}
                  <PaginationItem>
                    <PaginationNext
                      href="#"
                      onClick={e => { e.preventDefault(); if (currentPage < totalPages) setCurrentPage(p => p + 1); }}
                      className={currentPage === totalPages ? 'pointer-events-none opacity-50' : ''}
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            </div>
          )}
        </>
      )}

      {/* Modals */}
      <AgentModal
        isOpen={isModalOpen}
        mode={modalMode}
        onClose={() => setIsModalOpen(false)}
        onSave={handleModalSave}
        initialData={
          editingAgent
            ? {
                name: editingAgent.name,
                description: editingAgent.description,
                llm_id: editingAgent.llm_id,
                session_idle_timeout_minutes:
                  editingAgent.session_idle_timeout_minutes,
                sandbox_timeout_seconds:
                  editingAgent.sandbox_timeout_seconds,
                compact_threshold_percent:
                  editingAgent.compact_threshold_percent,
                max_iteration: editingAgent.max_iteration,
              }
            : undefined
        }
      />

      <ConfirmationModal
        isOpen={deleteConfirmation.isOpen}
        title="Delete Agent"
        message={`Are you sure you want to delete "${deleteConfirmation.agent?.name}"? This will also delete all associated scenes, subscenes, connections, and chat history.`}
        confirmText="Delete"
        cancelText="Cancel"
        onConfirm={() => void confirmDeleteAgent()}
        onCancel={() => setDeleteConfirmation({ isOpen: false, agent: null })}
        variant="danger"
      />
    </div>
  );
}

export default AgentList;
