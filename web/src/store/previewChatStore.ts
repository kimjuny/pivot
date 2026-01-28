import { create } from 'zustand';
import type { ChatHistory, PreviewChatRequest, Agent, SceneGraph, StreamEvent } from '../types';
import { StreamEventType } from '../types';
import { previewChatStream } from '../utils/api';
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

    // Initial agent message placeholder
    const agentMessageId = -Date.now() - 1;
    const initialAgentMessage: ChatHistory = {
        id: agentMessageId,
        agent_id: previewAgent.id,
        user: 'preview-user',
        role: 'agent',
        message: '',
        create_time: utcTimestamp
    };

    set(state => ({
      isChatting: true,
      error: null,
      chatHistory: [...state.chatHistory, userMessage, initialAgentMessage]
    }));

    try {
      const request: PreviewChatRequest = {
        message,
        agent_detail: previewAgent,
        current_scene_name: currentSceneName,
        current_subscene_name: currentSubsceneName
      };

      await previewChatStream(request, (event: StreamEvent) => {
          set(state => {
              const currentHistory = [...state.chatHistory];
              const msgIndex = currentHistory.findIndex(m => m.id === agentMessageId);
              if (msgIndex === -1) return {};

              const currentMsg = currentHistory[msgIndex];
              const updatedMsg = { ...currentMsg };

              switch (event.type) {
                  case StreamEventType.REASONING:
                      updatedMsg.reason = (updatedMsg.reason || '') + (event.delta || '');
                      break;
                  case StreamEventType.REASON:
                      updatedMsg.reason = (updatedMsg.reason || '') + (event.delta || '');
                      break;
                  case StreamEventType.RESPONSE:
                      updatedMsg.message = (updatedMsg.message || '') + (event.delta || '');
                      updatedMsg.create_time = event.create_time;
                      break;
                  case StreamEventType.UPDATED_SCENES:
                      if (event.updated_scenes && event.updated_scenes.length > 0) {
                          const targetGraph = event.updated_scenes[0];
                          if (targetGraph) {
                              updatedMsg.graph = targetGraph;
                          }
                      }
                      break;
                  case StreamEventType.MATCH_CONNECTION:
                      break;
                  case StreamEventType.ERROR:
                      console.error('Stream error:', event.error);
                      break;
                  default:
                      break;
              }

              currentHistory[msgIndex] = updatedMsg;
              return { chatHistory: currentHistory };
          });
      });

      set({ isChatting: false });

    } catch (error) {
      const err = error as Error;
      set(state => {
          const currentHistory = state.chatHistory.filter(m => m.id !== agentMessageId);
          return {
            chatHistory: currentHistory,
            isChatting: false,
            error: err.message
          };
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
