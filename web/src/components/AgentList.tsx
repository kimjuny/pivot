import React, { useState, useEffect, useRef, MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, User, MoreHorizontal, Search } from 'lucide-react';
import { Input } from '@base-ui/react/input';
import { Button } from '@base-ui/react/button';
import { getAgents, deleteAgent, updateAgent, createAgent } from '../utils/api';
import { formatTimestamp } from '../utils/timestamp';
import type { Agent } from '../types';
import AgentModal from './AgentModal';

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
  const [menuOpenAgentId, setMenuOpenAgentId] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const menuRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  /**
   * Load agents from server on component mount.
   * Fetches all available agents and updates state.
   */
  useEffect(() => {
    void loadAgents();
  }, []);

  /**
   * Close menu when clicking outside.
   */
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpenAgentId(null);
      }
    };

    if (menuOpenAgentId !== null) {
      document.addEventListener('mousedown', handleClickOutside as unknown as EventListener);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside as unknown as EventListener);
      };
    }
  }, [menuOpenAgentId]);

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
    setMenuOpenAgentId(null);
  };

  /**
   * Handle delete agent button click.
   * Deletes the agent and reloads the list.
   */
  const handleDeleteAgent = async (agent: Agent, e: MouseEvent) => {
    e.stopPropagation();
    
    // We must ensure the event doesn't propagate to the card click handler
    // and that we wait for confirmation.
    
    // Using window.confirm inside an async function is blocking in browser main thread,
    // but we need to be careful about React event pooling or other side effects.
    
    const confirmed = window.confirm(`Are you sure you want to delete agent "${agent.name}"? This will also delete all associated scenes, subscenes, connections, and chat history.`);
    
    if (confirmed) {
      try {
        await deleteAgent(agent.id);
        setMenuOpenAgentId(null);
        await loadAgents();
      } catch (err) {
        const error = err as Error;
        alert(`Failed to delete agent: ${error.message}`);
      }
    } else {
      // If cancelled, just close the menu
      setMenuOpenAgentId(null);
    }
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
      navigate(`/agent/${newAgent.id}`);
    } else if (modalMode === 'edit' && editingAgent) {
      await updateAgent(editingAgent.id, agentData);
      await loadAgents();
    }
  };

  /**
   * Navigate to agent visualization view.
   */
  const handleAgentClick = (agent: Agent) => {
    navigate(`/agent/${agent.id}`);
  };

  const filteredAgents = agents.filter((agent) =>
    agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (agent.description && agent.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-dark-bg">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner"></div>
          <div className="text-lg text-dark-text-secondary font-medium">Loading...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-dark-bg">
        <div className="text-xl text-red-400 mb-4 font-medium">Error: {error}</div>
        <button
          onClick={() => void loadAgents()}
          className="px-6 py-3 btn-accent rounded-lg font-medium"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex-1 bg-dark-bg text-dark-text-primary">
      <div className="w-full px-4 py-8">
        <div className="flex items-center justify-between mb-8 gap-4">
          <div className="flex-1 max-w-md relative">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-text-muted pointer-events-none" />
            <Input
              placeholder="Search agents..."
              value={searchQuery}
              onValueChange={(value) => setSearchQuery(value)}
              className="h-10 w-full pl-10 pr-4 rounded-md border border-gray-200 bg-dark-bg-lighter text-base text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary"
            />
          </div>
          <Button
            onClick={handleCreateAgent}
            className="flex items-center space-x-2 h-10 px-4 btn-accent rounded-md font-medium whitespace-nowrap"
            title="Create a new agent"
          >
            <Plus className="w-5 h-5" />
            <span>Create Agent</span>
          </Button>
        </div>

        {filteredAgents.length === 0 && agents.length > 0 ? (
          <div className="text-center py-16">
            <div className="text-6xl text-dark-text-muted mb-4">🔍</div>
            <h3 className="text-xl font-semibold text-dark-text-secondary mb-2">No Results</h3>
            <p className="text-dark-text-muted">
              Try adjusting your search query
            </p>
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-6xl text-dark-text-muted mb-4">📭</div>
            <h3 className="text-xl font-semibold text-dark-text-secondary mb-2">No Agents</h3>
            <p className="text-dark-text-muted mb-6">
              Click the 'Create Agent' button to create your first agent
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredAgents.map((agent) => (
              <div
                key={agent.id}
                onClick={() => handleAgentClick(agent)}
                className="card-subtle rounded-xl p-6 cursor-pointer hover:shadow-lg transition-all duration-200 relative group"
                onMouseEnter={() => setMenuOpenAgentId(null)}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center space-x-3">
                    <div className="w-12 h-12 rounded-lg bg-primary/20 flex items-center justify-center p-2">
                      <User className="w-6 h-6 text-primary" />
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-dark-text-primary">{agent.name}</h3>
                      <div className="flex items-center space-x-2 mt-1">
                        <span className={`status-dot ${agent.is_active ? 'active' : ''}`}></span>
                        <span className="text-sm text-dark-text-secondary">
                          {agent.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="relative">
                    <div className="text-xs text-dark-text-muted">
                      ID: {agent.id}
                    </div>
                    <button
                      onClick={(e: MouseEvent) => {
                        e.stopPropagation();
                        setMenuOpenAgentId(menuOpenAgentId === agent.id ? null : agent.id);
                      }}
                      className="nav-hover-effect absolute -right-2 -top-1 p-1 rounded text-dark-text-secondary hover:text-dark-text-primary transition-colors opacity-0 group-hover:opacity-100"
                    >
                      <MoreHorizontal className="w-5 h-5 text-dark-text-secondary" />
                    </button>
                    {menuOpenAgentId === agent.id && (
                      <div
                        ref={menuRef}
                        className="absolute right-0 top-6 z-10 bg-dark-bg-lighter border border-dark-border rounded-lg shadow-card-lg py-1 min-w-[120px]"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={(e) => handleEditAgent(agent, e)}
                          className="w-full px-4 py-2 text-left text-sm text-dark-text-primary hover:bg-dark-border-light transition-colors flex items-center space-x-2"
                        >
                          <span>Edit</span>
                        </button>
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            void handleDeleteAgent(agent, e);
                          }}
                          className="w-full px-4 py-2 text-left text-sm text-red-400 hover:bg-red-500 hover:text-white transition-colors flex items-center space-x-2"
                        >
                          <span>Delete</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center space-x-2 text-sm">
                    <span className="text-dark-text-secondary">Model:</span>
                    <span className="text-dark-text-primary font-medium">{agent.model_name || 'N/A'}</span>
                  </div>

                  <div className="flex items-center space-x-2 text-sm">
                    <span className="text-dark-text-secondary">Updated:</span>
                    <span className="text-dark-text-primary font-medium">{formatTimestamp(agent.updated_at)}</span>
                  </div>

                  {agent.description && (
                    <div className="flex items-start space-x-2 text-sm">
                      <p className="text-dark-text-secondary line-clamp-2">{agent.description}</p>
                    </div>
                  )}
                </div>
              </div>
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
    </div>
  );
}

export default AgentList;
