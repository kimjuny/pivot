import { create } from 'zustand';
import type { Agent, SceneGraph } from '../types';
import { compareAgents, deepCopyAgent, deepCopySceneGraph } from '../utils/compare';

/**
 * Store for managing agent working state with A/B/C data comparison.
 * 
 * 1. OriginalAgentDetail (A data): From server, read-only baseline.
 * 2. WorkspaceAgentDetail (B data): User working copy, editable.
 * 3. PreviewAgentDetail (C data): For preview mode interaction.
 */
interface AgentWorkStore {
  /** Original agent data from server (A data) */
  originalAgent: Agent | null;
  /** Working copy of agent data (B data) */
  workspaceAgent: Agent | null;
  /** Preview copy of agent data (C data) */
  previewAgent: Agent | null;

  /** Current scene ID being edited/viewed */
  currentSceneId: number | null;
  
  /** Whether there are unsaved changes (A != B) */
  hasUnsavedChanges: boolean;
  /** Whether a submit operation is in progress */
  isSubmitting: boolean;
  /** Error message */
  error: string | null;

  /**
   * Initialize the store with data from server.
   * Sets A and B data.
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
   * Enter preview mode: Copy B -> C.
   */
  enterPreviewMode: () => void;

  /**
   * Update preview agent (C data).
   */
  updatePreviewAgent: (agent: Agent) => void;

  /**
   * Discard all changes: Reset B -> A.
   */
  discardChanges: () => void;

  /**
   * Mark changes as committed: Update A -> B.
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
  previewAgent: null,
  currentSceneId: null,
  hasUnsavedChanges: false,
  isSubmitting: false,
  error: null,

  initialize: (agent) => {
    const copy = deepCopyAgent(agent);
    set({
      originalAgent: agent, // Keep original reference or deep copy? Safer to deep copy if we mutate strictly, but here we treat it as immutable.
      workspaceAgent: copy,
      previewAgent: null, // Clear preview on init
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

  enterPreviewMode: () => {
    const { workspaceAgent } = get();
    if (workspaceAgent) {
      set({
        previewAgent: deepCopyAgent(workspaceAgent)
      });
    }
  },

  updatePreviewAgent: (agent) => {
    set({ previewAgent: agent });
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
      previewAgent: null,
      currentSceneId: null,
      hasUnsavedChanges: false,
      isSubmitting: false,
      error: null
    });
  }
}));

export { useAgentWorkStore };
