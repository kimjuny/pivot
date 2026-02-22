import { useState, useEffect, MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, User, MoreHorizontal, Search, Bot } from 'lucide-react';
import { toast } from 'sonner';
import { getAgents, deleteAgent, updateAgent, createAgent, AuthError } from '../utils/api';
import { formatTimestamp } from '../utils/timestamp';
import type { Agent } from '../types';
import AgentModal from './AgentModal';
import ConfirmationModal from './ConfirmationModal';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Card } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';

/**
 * Agent list component.
 * Displays all available agents with their details.
 * Allows navigation to agent visualization view.
 */
function AgentList() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    agent: Agent | null;
  }>({ isOpen: false, agent: null });
  const navigate = useNavigate();

  /**
   * Load agents from server on component mount.
   * Fetches all available agents and updates state.
   */
  useEffect(() => {
    void loadAgents();
  }, []);

  /**
   * Fetch agents from API and update state.
   * Handles loading and error states.
   * AuthError is handled by ProtectedRoute which redirects to login page.
   */
  const loadAgents = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getAgents();
      setAgents(data);
    } catch (err) {
      // AuthError is handled by ProtectedRoute - just don't show error
      if (err instanceof AuthError) {
        return;
      }
      const error = err as Error;
      setError(error.message || 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  };

  /**
   * Handle create agent button click.
   * Opens the agent modal in create mode.
   */
  const handleCreateAgent = () => {
    setModalMode('create');
    setEditingAgent(null);
    setIsModalOpen(true);
  };

  /**
   * Handle edit agent button click.
   * Opens the agent modal in edit mode.
   */
  const handleEditAgent = (agent: Agent, e: MouseEvent) => {
    e.stopPropagation();
    setModalMode('edit');
    setEditingAgent(agent);
    setIsModalOpen(true);
  };

  /**
   * Handle delete agent button click.
   * Opens confirmation modal instead of using window.confirm.
   */
  const handleDeleteAgent = (agent: Agent, e: MouseEvent) => {
    e.stopPropagation();
    setDeleteConfirmation({ isOpen: true, agent });
  };

  /**
   * Confirm agent deletion.
   * Deletes the agent and reloads the list.
   */
  const confirmDeleteAgent = async () => {
    if (!deleteConfirmation.agent) return;

    try {
      await deleteAgent(deleteConfirmation.agent.id);
      setDeleteConfirmation({ isOpen: false, agent: null });
      toast.success('Agent deleted successfully');
      await loadAgents();
    } catch (err) {
      const error = err as Error;
      toast.error(`Failed to delete agent: ${error.message}`);
      setDeleteConfirmation({ isOpen: false, agent: null });
    }
  };

  /**
   * Cancel agent deletion.
   */
  const cancelDeleteAgent = () => {
    setDeleteConfirmation({ isOpen: false, agent: null });
  };

  /**
   * Handle modal save.
   * Creates or updates agent and reloads list.
   */
  const handleModalSave = async (agentData: {
    name: string;
    description?: string;
    llm_id: number | undefined;
    is_active?: boolean;
  }) => {
    if (modalMode === 'create') {
      if (!agentData.llm_id) {
        toast.error('LLM selection is required');
        return;
      }
      const newAgent = await createAgent({
        name: agentData.name,
        description: agentData.description,
        llm_id: agentData.llm_id,
        is_active: agentData.is_active
      });
      toast.success('Agent created successfully');
      navigate(`/agent/${newAgent.id}`);
    } else if (modalMode === 'edit' && editingAgent) {
      await updateAgent(editingAgent.id, {
        name: agentData.name,
        description: agentData.description,
        llm_id: agentData.llm_id,
        is_active: agentData.is_active
      });
      toast.success('Agent updated successfully');
      await loadAgents();
    }
  };

  /**
   * Navigate to agent visualization view.
   */
  const handleAgentClick = (agent: Agent) => {
    navigate(`/agent/${agent.id}`);
  };

  /**
   * Handle keyboard navigation for agent cards.
   * Allows Enter and Space to navigate to agent.
   */
  const handleCardKeyDown = (e: React.KeyboardEvent, agent: Agent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      handleAgentClick(agent);
    }
  };

  const filteredAgents = agents.filter((agent) =>
    agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (agent.description && agent.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner"></div>
          <div className="text-lg text-muted-foreground font-medium">Loading…</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-background">
        <div className="text-xl text-destructive mb-4 font-medium">Error: {error}</div>
        <Button
          onClick={() => void loadAgents()}
          className="font-medium"
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-background text-foreground">
      {/* Page header */}
      <div className="flex flex-col gap-4 px-6 pt-6 pb-4">
        {/* Title row */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary/15 flex items-center justify-center">
              <Bot className="w-4 h-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight">Agents</h1>
              <p className="text-xs text-muted-foreground mt-0.5">
                {agents.length} agent{agents.length !== 1 ? 's' : ''}
              </p>
            </div>
          </div>

          <Button size="sm" onClick={handleCreateAgent} className="gap-1.5" aria-label="Create a new agent">
            <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            New Agent
          </Button>
        </div>

        {/* Search row */}
        <div className="relative max-w-sm">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none z-10"
            aria-hidden="true"
          />
          <ButtonGroup>
            <Input
              placeholder="Search agents…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 h-8 text-sm"
              autoComplete="off"
              aria-label="Search agents"
            />
            <Button variant="outline" size="sm" className="h-8" aria-label="Execute search">
              Search
            </Button>
          </ButtonGroup>
        </div>
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-auto px-6 pb-6">

        {filteredAgents.length === 0 && agents.length > 0 ? (
          <div className="text-center py-16">
            <Bot className="w-12 h-12 mx-auto mb-3 opacity-20 text-muted-foreground" />
            <h3 className="text-base font-semibold text-foreground mb-1">No Results</h3>
            <p className="text-sm text-muted-foreground">
              Try adjusting your search query
            </p>
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-16">
            <Bot className="w-12 h-12 mx-auto mb-3 opacity-20 text-muted-foreground" />
            <h3 className="text-base font-semibold text-foreground mb-1">No Agents</h3>
            <p className="text-sm text-muted-foreground mb-4">
              Create your first agent to get started
            </p>
            <Button variant="outline" size="sm" onClick={handleCreateAgent}>
              <Plus className="w-3.5 h-3.5 mr-1.5" />
              Create your first agent
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {filteredAgents.map((agent) => (
              <Card
                key={agent.id}
                onClick={() => handleAgentClick(agent)}
                onKeyDown={(e) => handleCardKeyDown(e, agent)}
                className="cursor-pointer transition-all duration-200 hover:bg-accent/50 motion-reduce:transition-none relative group p-3 flex flex-col min-h-[130px]"
                role="button"
                tabIndex={0}
                aria-label={`View agent ${agent.name}`}
              >
                {/* Top row: Icon + Name + Menu */}
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-md bg-primary/20 flex items-center justify-center flex-shrink-0">
                    <User className="w-4 h-4 text-primary" aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium text-sm truncate">{agent.name}</span>
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${agent.is_active ? 'bg-primary' : 'bg-muted-foreground/50'}`} aria-hidden="true" />
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      Edited: {formatTimestamp(agent.updated_at)}
                    </div>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity flex-shrink-0"
                        onClick={(e) => e.stopPropagation()}
                        aria-label="Agent options"
                      >
                        <MoreHorizontal className="w-3.5 h-3.5" aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                      <DropdownMenuItem onClick={(e) => handleEditAgent(agent, e as unknown as MouseEvent)}>
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={(e) => handleDeleteAgent(agent, e as unknown as MouseEvent)}
                        className="text-destructive focus:text-destructive"
                      >
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                {/* Description (if exists) - with flex-1 to push tag to bottom */}
                <div className="flex-1 mt-2">
                  {agent.description && (
                    <p className="text-xs text-muted-foreground line-clamp-2 break-words">
                      {agent.description}
                    </p>
                  )}
                </div>

                {/* Bottom row: Model tag - always at bottom */}
                <div className="flex items-center gap-2 mt-2">
                  <Badge variant="outline" className="text-[10px] px-1.5 py-0.5">
                    {agent.model_name || 'N/A'}
                  </Badge>
                </div>
              </Card>
            ))}
          </div>
        )}

        {/* Footer count */}
        {filteredAgents.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            Showing {filteredAgents.length} of {agents.length} agent{agents.length !== 1 ? 's' : ''}
            {searchQuery && ` matching "${searchQuery}"`}
          </p>
        )}
      </div>

      <AgentModal
        isOpen={isModalOpen}
        mode={modalMode}
        onClose={() => setIsModalOpen(false)}
        onSave={handleModalSave}
        initialData={editingAgent ? {
          name: editingAgent.name,
          description: editingAgent.description,
          llm_id: editingAgent.llm_id,
          is_active: editingAgent.is_active
        } : undefined}
      />

      <ConfirmationModal
        isOpen={deleteConfirmation.isOpen}
        title="Delete Agent"
        message={`Are you sure you want to delete agent "${deleteConfirmation.agent?.name}"? This will also delete all associated scenes, subscenes, connections, and chat history.`}
        confirmText="Delete Agent"
        cancelText="Cancel"
        onConfirm={() => void confirmDeleteAgent()}
        onCancel={cancelDeleteAgent}
        variant="danger"
      />
    </div>
  );
}

export default AgentList;
