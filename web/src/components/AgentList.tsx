import { useState, useEffect, MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, User, MoreHorizontal, Search } from 'lucide-react';
import { toast } from 'sonner';
import { getAgents, deleteAgent, updateAgent, createAgent } from '../utils/api';
import { formatTimestamp } from '../utils/timestamp';
import type { Agent } from '../types';
import AgentModal from './AgentModal';
import ConfirmationModal from './ConfirmationModal';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

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
   */
  const loadAgents = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getAgents();
      setAgents(data);
    } catch (err) {
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
    model_name?: string;
    is_active?: boolean;
  }) => {
    if (modalMode === 'create') {
      const newAgent = await createAgent(agentData);
      toast.success('Agent created successfully');
      navigate(`/agent/${newAgent.id}`);
    } else if (modalMode === 'edit' && editingAgent) {
      await updateAgent(editingAgent.id, agentData);
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
    <div className="flex-1 bg-background text-foreground">
      <div className="w-full px-4 py-8">
        <div className="flex items-center justify-between mb-8 gap-4">
          <div className="flex-1 max-w-md relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" aria-hidden="true" />
            <Input
              placeholder="Search agents…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
              autoComplete="off"
              inputMode="search"
              name="search"
              aria-label="Search agents"
            />
          </div>
          <Button
            onClick={handleCreateAgent}
            className="flex items-center gap-2"
            aria-label="Create a new agent"
          >
            <Plus className="w-5 h-5" aria-hidden="true" />
            <span>Create Agent</span>
          </Button>
        </div>

        {filteredAgents.length === 0 && agents.length > 0 ? (
          <div className="text-center py-16">
            <div className="text-6xl text-muted-foreground mb-4">🔍</div>
            <h3 className="text-xl font-semibold text-foreground mb-2">No Results</h3>
            <p className="text-muted-foreground">
              Try adjusting your search query
            </p>
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-6xl text-muted-foreground mb-4">📭</div>
            <h3 className="text-xl font-semibold text-foreground mb-2">No Agents</h3>
            <p className="text-muted-foreground mb-6">
              Click the "Create Agent" button to create your first agent
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredAgents.map((agent) => (
              <Card
                key={agent.id}
                onClick={() => handleAgentClick(agent)}
                onKeyDown={(e) => handleCardKeyDown(e, agent)}
                className="cursor-pointer transition-all duration-200 hover:shadow-lg hover:scale-[1.02] motion-reduce:transition-none motion-reduce:hover:scale-100 relative group"
                role="button"
                tabIndex={0}
                aria-label={`View agent ${agent.name}`}
              >
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center space-x-3 min-w-0 flex-1">
                      <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center p-2 flex-shrink-0">
                        <User className="w-5 h-5 text-primary" aria-hidden="true" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <CardTitle className="text-lg truncate">{agent.name}</CardTitle>
                        <div className="flex items-center space-x-2 mt-1">
                          <span className={`w-2 h-2 rounded-full ${agent.is_active ? 'bg-primary animate-pulse' : 'bg-muted-foreground'}`} aria-hidden="true"></span>
                          <span className="text-sm text-muted-foreground">
                            {agent.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex-shrink-0 flex flex-col items-end gap-1">
                      <span className="text-xs text-muted-foreground">
                        ID: {agent.id}
                      </span>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                            onClick={(e) => e.stopPropagation()}
                            aria-label="Agent options"
                          >
                            <MoreHorizontal className="w-4 h-4" aria-hidden="true" />
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
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="space-y-2 text-sm">
                    <div className="flex items-center space-x-2">
                      <span className="text-muted-foreground">Model:</span>
                      <span className="font-medium">{agent.model_name || 'N/A'}</span>
                    </div>
                    <div className="flex items-center space-x-2">
                      <span className="text-muted-foreground">Updated:</span>
                      <span className="font-medium">{formatTimestamp(agent.updated_at)}</span>
                    </div>
                    {agent.description && (
                      <CardDescription className="line-clamp-2 break-words mt-2">
                        {agent.description}
                      </CardDescription>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
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
          model_name: editingAgent.model_name,
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
