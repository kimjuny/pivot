import { create } from 'zustand';
import type { SceneGraph, ChatHistory, ChatResponse } from '../types';
import { fetchSceneGraph, initializeAgent as apiInitializeAgent, chatWithAgent, chatWithAgentById, resetAgent as apiResetAgent, getChatHistory, clearChatHistory as apiClearChatHistory } from '../utils/api';
import websocket from '../utils/websocket';

interface AgentState {
  isStarted: boolean;
  currentScene: string | null;
  currentSubscene: string | null;
  historyLength: number;
}

interface AgentStore {
  agentState: AgentState;
  sceneGraph: SceneGraph | null;
  chatHistory: ChatHistory[];
  isInitializing: boolean;
  isChatting: boolean;
  isLoadingSceneGraph: boolean;
  isLoadingChatHistory: boolean;
  hasInitialized: boolean;
  error: string | null;
  initializeAgent: () => Promise<void>;
  loadChatHistory: (agentId: number, user?: string) => Promise<void>;
  clearChatHistory: (agentId: number, user?: string) => Promise<void>;
  chatWithAgentById: (agentId: number, message: string, user?: string) => Promise<string>;
  chatWithAgent: (message: string) => Promise<string>;
  refreshSceneGraph: () => Promise<void>;
  resetAgent: () => Promise<void>;
  clearError: () => void;
}

const useAgentStore = create<AgentStore>((set, get) => ({
  agentState: {
    isStarted: false,
    currentScene: null,
    currentSubscene: null,
    historyLength: 0
  },
  
  sceneGraph: null,
  
  chatHistory: [],
  
  isInitializing: false,
  isChatting: false,
  isLoadingSceneGraph: false,
  isLoadingChatHistory: false,
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
      const sceneGraph = await fetchSceneGraph();
      set({ 
        sceneGraph,
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

  loadChatHistory: async (agentId: number, user: string = 'preview-user') => {
    set({ isLoadingChatHistory: true, error: null });
    try {
      const response = await getChatHistory(agentId, user);
      set({ 
        chatHistory: response.history,
        sceneGraph: response.latest_graph || null,
        isLoadingChatHistory: false,
        error: null
      });
    } catch (error) {
      const err = error as Error;
      set({ 
        isLoadingChatHistory: false, 
        error: err.message 
      });
      throw error;
    }
  },

  clearChatHistory: async (agentId: number, user: string = 'preview-user') => {
    set({ isLoadingChatHistory: true, error: null });
    try {
      await apiClearChatHistory(agentId, user);
      set({ 
        chatHistory: [],
        sceneGraph: null,
        isLoadingChatHistory: false,
        error: null
      });
    } catch (error) {
      const err = error as Error;
      set({ 
        isLoadingChatHistory: false, 
        error: err.message 
      });
      throw error;
    }
  },

  chatWithAgentById: async (agentId: number, message: string, user: string = 'preview-user') => {
    const now = new Date();
    const utcTimestamp = now.toISOString();
    
    set(state => {
      const newUserMessage: ChatHistory = {
        id: 0,
        agent_id: agentId,
        user: user,
        role: 'user',
        message,
        create_time: utcTimestamp
      };
      return {
        isChatting: true,
        error: null,
        chatHistory: [...state.chatHistory, newUserMessage]
      };
    });
    try {
      const response = await chatWithAgentById(agentId, message, user);
      
      set(state => {
        const newAgentMessage: ChatHistory = {
          id: 0,
          agent_id: agentId,
          user: user,
          role: 'agent',
          message: response.response,
          reason: response.reason,
          create_time: response.create_time || new Date().toISOString()
        };
        return {
          chatHistory: [...state.chatHistory, newAgentMessage],
          isChatting: false
        };
      });
      
      if (response.graph) {
        set({ sceneGraph: response.graph });
      }
      
      return response.response;
    } catch (error) {
      const err = error as Error;
      set({
        isChatting: false,
        error: err.message
      });
      throw error;
    }
  },

  chatWithAgent: async (message: string) => {
    set(state => {
      const newUserMessage: ChatHistory = {
        id: 0,
        agent_id: 0,
        user: 'preview-user',
        role: 'user',
        message,
        create_time: new Date().toISOString()
      };
      return {
        isChatting: true,
        error: null,
        chatHistory: [...state.chatHistory, newUserMessage]
      };
    });
    try {
      const response = await chatWithAgent(message);
      
      set(state => {
        const newAgentMessage: ChatHistory = {
          id: 0,
          agent_id: 0,
          user: 'preview-user',
          role: 'agent',
          message: response.response,
          reason: response.reason,
          create_time: response.create_time || new Date().toISOString()
        };
        return {
          chatHistory: [...state.chatHistory, newAgentMessage],
          isChatting: false
        };
      });
      
      return response.response;
    } catch (error) {
      const err = error as Error;
      set({
        isChatting: false,
        error: err.message
      });
      throw error;
    }
  },

  refreshSceneGraph: async () => {
    set({ isLoadingSceneGraph: true, error: null });
    try {
      const sceneGraph = await fetchSceneGraph();
      set({ 
        sceneGraph,
        isLoadingSceneGraph: false,
        error: null
      });
    } catch (error) {
      const err = error as Error;
      set({ 
        isLoadingSceneGraph: false, 
        error: err.message 
      });
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
        sceneGraph: null,
        chatHistory: [],
        hasInitialized: false
      });
    } catch (error) {
      const err = error as Error;
      set({ error: err.message });
      throw error;
    }
  },

  clearError: () => set({ error: null })
}));

websocket.connect();

websocket.on('message', (data) => {
  if ((data as { type?: string }).type === 'scene_update') {
    const sceneGraphCopy = JSON.parse(JSON.stringify((data as { data?: unknown }).data)) as SceneGraph;
    useAgentStore.setState(state => ({ ...state, sceneGraph: sceneGraphCopy }));
  }
});

export { useAgentStore };
