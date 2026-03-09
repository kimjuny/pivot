import { create } from 'zustand';
import type { Agent, SceneGraph } from '../types';
import { compareAgents, deepCopyAgent } from '../utils/compare';

/**
 * Store for managing agent working state with original and workspace copies.
 *
 * 1. OriginalAgentDetail: Server baseline used for dirty checking.
 * 2. WorkspaceAgentDetail: Editable working copy used by the scene editor.
 */
interface AgentWorkStore {
  /** Original agent data from server */
  originalAgent: Agent | null;
  /** Working copy of agent data */
  workspaceAgent: Agent | null;

  /** Current scene ID being edited/viewed */
  currentSceneId: number | null;

  /** Whether there are unsaved changes */
  hasUnsavedChanges: boolean;
  /** Whether a submit operation is in progress */
  isSubmitting: boolean;
  /** Error message */
  error: string | null;

  /**
   * Initialize the store with data from server.
   * Sets original and workspace data.
   */
  initialize: (agent: Agent) => void;

  /**
   * Update the entire workspace agent.
   */
  setWorkspaceAgent: (agent: Agent) => void;

  /**
   * Update a specific scene's graph in the workspace.
   */
  updateSceneInWorkspace: (sceneId: number, graph: SceneGraph) => void;

  /**
   * Discard all changes and restore the original data.
   */
  discardChanges: () => void;

  /**
   * Mark changes as committed.
   */
  markAsCommitted: (newAgentData?: Agent) => void;

  /**
   * Set current scene ID.
   */
  setCurrentSceneId: (id: number | null) => void;

  setSubmitting: (isSubmitting: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const useAgentWorkStore = create<AgentWorkStore>((set, get) => ({
  originalAgent: null,
  workspaceAgent: null,
  currentSceneId: null,
  hasUnsavedChanges: false,
  isSubmitting: false,
  error: null,

  initialize: (agent) => {
    const copy = deepCopyAgent(agent);
    set({
      originalAgent: agent, // Keep original reference or deep copy? Safer to deep copy if we mutate strictly, but here we treat it as immutable.
      workspaceAgent: copy,
      hasUnsavedChanges: false,
      error: null
    });
  },

  setWorkspaceAgent: (agent) => {
    const { originalAgent } = get();
    const hasChanges = compareAgents(originalAgent, agent);
    set({
      workspaceAgent: agent,
      hasUnsavedChanges: hasChanges
    });
  },

  updateSceneInWorkspace: (sceneId, graph) => {
    const { workspaceAgent, originalAgent } = get();
    if (!workspaceAgent || !workspaceAgent.scenes) return;

    // Create new scenes array with updated graph
    const newScenes = workspaceAgent.scenes.map(s => {
      if (s.id === sceneId) {
        return { ...s, ...graph }; // Merge updates
      }
      return s;
    });

    const newAgent = { ...workspaceAgent, scenes: newScenes };
    const hasChanges = compareAgents(originalAgent, newAgent);

    set({
      workspaceAgent: newAgent,
      hasUnsavedChanges: hasChanges
    });
  },

  discardChanges: () => {
    const { originalAgent } = get();
    set({
      workspaceAgent: deepCopyAgent(originalAgent),
      hasUnsavedChanges: false,
      error: null
    });
  },

  markAsCommitted: (newAgentData) => {
    const { workspaceAgent } = get();
    const confirmedAgent = newAgentData || deepCopyAgent(workspaceAgent);
    
    set({
      originalAgent: confirmedAgent,
      workspaceAgent: deepCopyAgent(confirmedAgent), // Ensure workspace is a fresh copy
      hasUnsavedChanges: false,
      isSubmitting: false,
      error: null
    });
  },

  setCurrentSceneId: (id) => set({ currentSceneId: id }),
  setSubmitting: (isSubmitting) => set({ isSubmitting }),
  setError: (error) => set({ error }),

  reset: () => {
    set({
      originalAgent: null,
      workspaceAgent: null,
      currentSceneId: null,
      hasUnsavedChanges: false,
      isSubmitting: false,
      error: null
    });
  }
}));

export { useAgentWorkStore };
