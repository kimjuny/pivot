import { create } from 'zustand';
import type { ChatHistory, ChatResponse, SceneGraph } from '../types';
import { chatWithAgentById, getChatHistory, clearChatHistory as apiClearChatHistory } from '../utils/api';
import { useSceneGraphStore } from './sceneGraphStore';

/**
 * Store for managing chat history and chat operations.
 * Handles message sending, history loading, and clearing.
 */
interface ChatStore {
  /** Array of chat messages between user and agent */
  chatHistory: ChatHistory[];
  /** Loading state for active chat operation */
  isChatting: boolean;
  /** Loading state for chat history operations */
  isLoadingChatHistory: boolean;
  /** Error message from last operation */
  error: string | null;
  /** Load chat history for a specific agent */
  loadChatHistory: (agentId: number, user?: string) => Promise<void>;
  /** Clear chat history for a specific agent */
  clearChatHistory: (agentId: number, user?: string) => Promise<void>;
  /** Send message to a specific agent by ID */
  chatWithAgentById: (agentId: number, message: string, user?: string) => Promise<string>;
  /** Clear error message */
  clearError: () => void;
}

const useChatStore = create<ChatStore>((set) => ({
  chatHistory: [],
  isChatting: false,
  isLoadingChatHistory: false,
  error: null,

  loadChatHistory: async (agentId: number, user: string = 'preview-user') => {
    set({ isLoadingChatHistory: true, error: null });
    try {
      const response = await getChatHistory(agentId, user);
      set({ 
        chatHistory: response.history,
        isLoadingChatHistory: false,
        error: null
      });
      if (response.latest_graph) {
        useSceneGraphStore.getState().updateSceneGraph(response.latest_graph);
      }
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
        useSceneGraphStore.getState().updateSceneGraph(response.graph);
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

  clearError: () => set({ error: null })
}));

export { useChatStore };
