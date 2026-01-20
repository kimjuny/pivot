import { create } from 'zustand';
import type { ChatHistory, PreviewChatRequest, Agent, SceneGraph } from '../types';
import { previewChat } from '../utils/api';
import { useAgentWorkStore } from './agentWorkStore';

/**
 * Store for managing ephemeral preview chat state.
 * Handles conversation with the Preview Agent using the current workspace agent definition.
 */
interface PreviewChatStore {
  /** Array of chat messages for the current preview session */
  chatHistory: ChatHistory[];
  /** Loading state for active chat operation */
  isChatting: boolean;
  /** Error message from last operation */
  error: string | null;

  /**
   * Send a message to the Preview Agent.
   * Uses the WorkspaceAgentDetail from agentWorkStore as the source of truth.
   * 
   * @param message - User's message
   */
  sendMessage: (message: string) => Promise<void>;

  /**
   * Clear the preview chat history.
   * Should be called when entering preview mode or resetting.
   */
  clearHistory: () => void;

  /**
   * Clear error message.
   */
  clearError: () => void;
}

const usePreviewChatStore = create<PreviewChatStore>((set, get) => ({
  chatHistory: [],
  isChatting: false,
  error: null,

  sendMessage: async (message: string) => {
    const { previewAgent, currentSceneId } = useAgentWorkStore.getState();
    
    if (!previewAgent) {
      set({ error: 'No preview agent available. Please try entering preview mode again.' });
      return;
    }

    // Determine current scene/subscene names for context
    let currentSceneName: string | null = null;
    const currentSubsceneName: string | null = null; // We might track this in agentWorkStore too?

    // For now, let's assume we start from the current scene in view, or the first one if none selected
    if (previewAgent.scenes) {
        const scene = previewAgent.scenes.find(s => s.id === currentSceneId) || previewAgent.scenes[0];
        if (scene) {
            currentSceneName = scene.name || null;
            // currentSubsceneName - we don't track this in store explicitly yet, 
            // but the backend will default to start/first subscene if not provided.
            // If we want to support continuing from a specific state, we need to store it.
            // For now, let's leave subscene null and let backend decide.
        }
    }

    const now = new Date();
    const utcTimestamp = now.toISOString();

    // Optimistic user message
    const userMessage: ChatHistory = {
      id: -Date.now(), // Temporary ID
      agent_id: previewAgent.id,
      user: 'preview-user',
      role: 'user',
      message,
      create_time: utcTimestamp
    };

    set(state => ({
      isChatting: true,
      error: null,
      chatHistory: [...state.chatHistory, userMessage]
    }));

    try {
      const request: PreviewChatRequest = {
        message,
        agent_detail: previewAgent,
        current_scene_name: currentSceneName,
        current_subscene_name: currentSubsceneName
      };

      const response = await previewChat(request);

      let targetGraph: SceneGraph | undefined;

      if (response.graph && Array.isArray(response.graph) && response.graph.length > 0) {
        // Find the active scene
        const activeSceneName = response.current_scene_name;
        targetGraph = response.graph.find(g => g.name === activeSceneName) || response.graph[0];
        
        // Inject active state
        if (targetGraph) {
          targetGraph.current_scene = response.current_scene_name || undefined;
          targetGraph.current_subscene = response.current_subscene_name || undefined;
        }
      } else if (response.graph && !Array.isArray(response.graph)) {
        // Fallback for potential legacy response or single object
        targetGraph = response.graph as SceneGraph;
        if (targetGraph) {
          targetGraph.current_scene = response.current_scene_name || undefined;
          targetGraph.current_subscene = response.current_subscene_name || undefined;
        }
      }

      const agentMessage: ChatHistory = {
        id: -Date.now() - 1, // Temporary ID
        agent_id: previewAgent.id,
        user: 'preview-user',
        role: 'agent',
        message: response.response,
        reason: response.reason,
        create_time: response.create_time,
        graph: targetGraph
      };

      set(state => ({
        chatHistory: [...state.chatHistory, agentMessage],
        isChatting: false
      }));

      // TODO: If the backend returns updated state (current scene/subscene), 
      // we should probably update our local state tracking if we want continuity.
      // But for "Preview", maybe we just want to see the flow.
      
    } catch (error) {
      const err = error as Error;
      set({
        isChatting: false,
        error: err.message
      });
    }
  },

  clearHistory: () => {
    set({
      chatHistory: [],
      error: null,
      isChatting: false
    });
  },

  clearError: () => set({ error: null })
}));

export { usePreviewChatStore };
