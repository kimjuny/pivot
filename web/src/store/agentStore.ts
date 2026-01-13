import { create } from 'zustand';
import { initializeAgent as apiInitializeAgent, resetAgent as apiResetAgent } from '../utils/api';
import { useSceneGraphStore } from './sceneGraphStore';
import { useChatStore } from './chatStore';

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
 * Store for managing agent initialization and reset operations.
 * Coordinates between scene graph and chat stores during initialization and reset.
 */
interface AgentStore {
  /** Current agent state */
  agentState: AgentState;
  /** Loading state for initialization */
  isInitializing: boolean;
  /** Whether agent has been initialized */
  hasInitialized: boolean;
  /** Error message from last operation */
  error: string | null;
  /** Initialize agent and load initial data */
  initializeAgent: () => Promise<void>;
  /** Reset agent to initial state */
  resetAgent: () => Promise<void>;
  /** Clear error message */
  clearError: () => void;
}

const useAgentStore = create<AgentStore>((set, get) => ({
  agentState: {
    isStarted: false,
    currentScene: null,
    currentSubscene: null,
    historyLength: 0
  },
  
  isInitializing: false,
  hasInitialized: false,
  error: null,

  initializeAgent: async () => {
    const { hasInitialized, isInitializing } = get();
    if (hasInitialized || isInitializing) {
      return;
    }
    
    set({ isInitializing: true, error: null });
    try {
      await apiInitializeAgent();
      await useSceneGraphStore.getState().refreshSceneGraph();
      set({ 
        isInitializing: false,
        hasInitialized: true,
        error: null
      });
    } catch (error) {
      const err = error as Error;
      set({ 
        isInitializing: false, 
        error: err.message 
      });
      throw error;
    }
  },

  resetAgent: async () => {
    try {
      await apiResetAgent();
      set({ 
        agentState: {
          isStarted: false,
          currentScene: null,
          currentSubscene: null,
          historyLength: 0
        },
        hasInitialized: false
      });
      useSceneGraphStore.getState().updateSceneGraph(null);
      void useChatStore.getState().clearChatHistory(0);
    } catch (error) {
      const err = error as Error;
      set({ error: err.message });
      throw error;
    }
  },

  clearError: () => set({ error: null })
}));

export { useAgentStore };
