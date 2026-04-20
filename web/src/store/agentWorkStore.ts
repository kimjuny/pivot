import { create } from 'zustand';
import type { Agent } from '../types';
import { compareAgents, deepCopyAgent } from '../utils/compare';

/**
 * Store for managing agent working state with original and workspace copies.
 *
 * 1. OriginalAgentDetail: Server baseline used for dirty checking.
 * 2. WorkspaceAgentDetail: Editable working copy used by the studio editor.
 */
interface AgentWorkStore {
  /** Original agent data from server */
  originalAgent: Agent | null;
  /** Working copy of agent data */
  workspaceAgent: Agent | null;
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
   * Discard all changes and restore the original data.
   */
  discardChanges: () => void;

  /**
   * Mark changes as committed.
   */
  markAsCommitted: (newAgentData?: Agent) => void;

  setSubmitting: (isSubmitting: boolean) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const useAgentWorkStore = create<AgentWorkStore>((set, get) => ({
  originalAgent: null,
  workspaceAgent: null,
  hasUnsavedChanges: false,
  isSubmitting: false,
  error: null,

  initialize: (agent) => {
    const copy = deepCopyAgent(agent);
    set({
      originalAgent: agent,
      workspaceAgent: copy,
      hasUnsavedChanges: false,
      error: null,
    });
  },

  setWorkspaceAgent: (agent) => {
    const { originalAgent } = get();
    const hasChanges = compareAgents(originalAgent, agent);
    set({
      workspaceAgent: agent,
      hasUnsavedChanges: hasChanges,
    });
  },

  discardChanges: () => {
    const { originalAgent } = get();
    set({
      workspaceAgent: deepCopyAgent(originalAgent),
      hasUnsavedChanges: false,
      error: null,
    });
  },

  markAsCommitted: (newAgentData) => {
    const { workspaceAgent } = get();
    const confirmedAgent = newAgentData || deepCopyAgent(workspaceAgent);

    set({
      originalAgent: confirmedAgent,
      workspaceAgent: deepCopyAgent(confirmedAgent),
      hasUnsavedChanges: false,
      isSubmitting: false,
      error: null,
    });
  },

  setSubmitting: (isSubmitting) => set({ isSubmitting }),
  setError: (error) => set({ error }),

  reset: () => {
    set({
      originalAgent: null,
      workspaceAgent: null,
      hasUnsavedChanges: false,
      isSubmitting: false,
      error: null,
    });
  },
}));

export { useAgentWorkStore };
