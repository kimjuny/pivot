import { create } from 'zustand';
import { useSceneGraphStore } from './sceneGraphStore';

/**
 * State representing the current agent status.
 */
interface AgentState {
  /** Whether the agent has been started */
  isStarted: boolean;
  /** Current scene identifier */
  currentScene: string | null;
  /** Current subscene identifier */
  currentSubscene: string | null;
  /** Number of history entries */
  historyLength: number;
}

/**
 * Store for managing agent state.
 * Coordinates between scene graph and chat stores.
 */
interface AgentStore {
  /** Current agent state */
  agentState: AgentState;
  /** Error message from last operation */
  error: string | null;
  /** Clear error message */
  clearError: () => void;
}

const useAgentStore = create<AgentStore>((set) => ({
  agentState: {
    isStarted: false,
    currentScene: null,
    currentSubscene: null,
    historyLength: 0
  },
  
  error: null,
  clearError: () => set({ error: null })
}));

export { useAgentStore };
