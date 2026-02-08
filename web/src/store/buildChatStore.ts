import { create } from 'zustand';
import type { BuildHistory, BuildChatRequest, SceneGraph, Scene, SceneNode, Connection } from '../types';
import { StreamEventType } from '../types';
import { chatWithBuildAgent } from '../utils/api';
import { useAgentWorkStore } from './agentWorkStore';

/**
 * Interface for scene data returned by Build Agent
 */
interface BuildConnectionData {
  name: string;
  from_subscene: string;
  to_subscene: string;
  condition?: string;
  [key: string]: unknown;
}

interface BuildSceneData {
  name: string;
  description?: string;
  type?: string;
  state?: string;
  mandatory?: boolean;
  objective?: string;
  subscenes?: Array<{
    name: string;
    description?: string;
    type?: string;
    state?: string;
    mandatory?: boolean;
    objective?: string;
    connections?: Array<BuildConnectionData>;
  }>;
  connections?: Array<BuildConnectionData>;
}

/**
 * Helper to convert backend scene data to frontend SceneGraph format
 */
const convertToSceneGraph = (
  sceneData: BuildSceneData,
  sceneId: number,
  agentId: number
): SceneGraph => {
  // Map connections to their source subscenes
  const subscenes = (sceneData.subscenes || []).map((sub) => {
    // Ensure name exists
    const subName = sub.name || '';

    // Find all connections originating from this subscene
    // Check top-level connections first (standard)
    let relevantConnections: BuildConnectionData[] = [];

    if (sceneData.connections && Array.isArray(sceneData.connections)) {
      relevantConnections = sceneData.connections.filter(
        (conn) => conn.from_subscene === subName
      );
    }

    // Fallback: check if connections are nested (non-standard but possible)
    if (relevantConnections.length === 0 && sub.connections && Array.isArray(sub.connections)) {
      relevantConnections = sub.connections;
    }

    return {
      ...sub,
      id: `subscene-${subName}`, // Ensure ID format matches frontend expectation
      position: { x: 0, y: 0 }, // Default position, will be laid out by auto-layout
      data: {
        label: subName,
        description: sub.description,
        type: sub.type || 'normal', // Default to normal if missing
        state: sub.state || 'inactive',
        mandatory: sub.mandatory,
        objective: sub.objective
      },
      connections: relevantConnections.map((conn, idx) => ({
        id: Date.now() + Math.floor(Math.random() * 10000) + idx, // Unique ID
        name: conn.name,
        condition: conn.condition,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        from_subscene: subName,
        to_subscene: conn.to_subscene
      }))
    } as SceneNode;
  });

  return {
    id: sceneId,
    name: sceneData.name,
    description: sceneData.description,
    agent_id: agentId,
    subscenes: subscenes,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  };
};

/**
 * Store for managing Build Chat state and operations.
 * Handles conversation with Build Agent for agent editing assistance.
 */
interface BuildChatStore {
  /** Array of build chat messages */
  buildChatHistory: BuildHistory[];
  /** Current session ID for the build conversation */
  currentBuildSession: string | null;
  /** Pending graph changes from Build Agent waiting to be applied */
  pendingBuildChanges: BuildSceneData[] | null;
  /** Loading state for active build chat operation */
  isChatting: boolean;
  /** Error message from last operation */
  error: string | null;

  /**
   * Send a message to the Build Agent.
   *
   * @param agentId - Unique identifier of the agent being edited
   * @param content - User's message to the Build Agent
   */
  chatWithBuildAgent: (agentId: number, content: string) => Promise<void>;

  /**
   * Apply pending build changes to the working scene graph.
   * This updates the AgentWorkStore's workingSceneGraph.
   */
  applyBuildChanges: () => void;

  /**
   * Discard pending build changes.
   */
  discardBuildChanges: () => void;

  /**
   * Clear error message.
   */
  clearError: () => void;

  /**
   * Reset the store state (used when switching to a different agent).
   */
  reset: () => void;
}

const useBuildChatStore = create<BuildChatStore>((set, get) => ({
  buildChatHistory: [],
  currentBuildSession: null,
  pendingBuildChanges: null,
  isChatting: false,
  error: null,

  chatWithBuildAgent: async (agentId: number, content: string) => {
    const now = new Date();
    const utcTimestamp = now.toISOString();

    set(state => {
      const newUserMessage: BuildHistory = {
        id: 0,
        session_id: state.currentBuildSession || '',
        role: 'user',
        content,
        created_at: utcTimestamp
      };
      // Also create an empty assistant message to avoid duplicate messages during streaming
      const emptyAssistantMessage: BuildHistory = {
        id: 0,
        session_id: state.currentBuildSession || '',
        role: 'assistant',
        content: '',
        created_at: new Date().toISOString()
      };
      return {
        isChatting: true,
        error: null,
        buildChatHistory: [...state.buildChatHistory, newUserMessage, emptyAssistantMessage]
      };
    });

    // Prepare accumulator for streaming response
    let responseText = '';
    let reasonText = '';
    let thinkingText = '';
    let agentJson = '';
    let error: string | null = null;

    try {
      const request: BuildChatRequest = {
        content,
        session_id: get().currentBuildSession,
        agent_id: agentId.toString()
      };

      // Import streaming API
      const { buildChatStream } = await import('../utils/api');

      await buildChatStream(request, (event) => {
        switch (event.type) {
          case StreamEventType.REASONING:
            // Accumulate thinking/reasoning content
            if (event.delta) {
              thinkingText += event.delta;
              // Update the assistant message in real-time
              set(state => {
                const history = [...state.buildChatHistory];
                const lastMsg = history[history.length - 1];
                if (lastMsg && lastMsg.role === 'assistant') {
                  lastMsg.thinking = thinkingText;
                }
                return { buildChatHistory: history };
              });
            }
            break;

          case StreamEventType.RESPONSE:
            // Accumulate response text
            if (event.delta) {
              responseText += event.delta;
              // Update the assistant message in real-time
              set(state => {
                const history = [...state.buildChatHistory];
                const lastMsg = history[history.length - 1];
                if (lastMsg && lastMsg.role === 'assistant') {
                  lastMsg.content = responseText;
                }
                return { buildChatHistory: history };
              });
            }
            break;

          case StreamEventType.REASON:
            // Store reason separately
            if (event.delta) {
              reasonText += event.delta;
            }
            break;

          case StreamEventType.UPDATED_SCENES:
            // Receive the complete agent JSON
            if (event.delta) {
              agentJson = event.delta;
            }
            break;

          case StreamEventType.ERROR:
            error = event.error || 'Unknown error';
            break;
        }
      });

      // After stream completes, finalize the message
      if (error) {
        throw new Error(error);
      }

      // Parse the agent JSON and extract scenes
      let parsedAgent: { scenes?: BuildSceneData[] } = {};
      if (agentJson) {
        try {
          parsedAgent = JSON.parse(agentJson) as { scenes?: BuildSceneData[] };
        } catch (e) {
          console.error('Failed to parse agent JSON:', e);
        }
      }

      set(state => {
        const history = [...state.buildChatHistory];
        const lastMsg = history[history.length - 1];
        if (lastMsg && lastMsg.role === 'assistant') {
          // Update the final message with agent snapshot
          lastMsg.agent_snapshot = agentJson;
        }

        return {
          buildChatHistory: history,
          isChatting: false,
          pendingBuildChanges: parsedAgent.scenes || null,
          error: null
        };
      });

    } catch (error) {
      const err = error as Error;
      set({
        isChatting: false,
        error: err.message
      });
      throw error;
    }
  },

  applyBuildChanges: () => {
    const { pendingBuildChanges } = get();
    if (pendingBuildChanges && Array.isArray(pendingBuildChanges)) {
      const agentWorkStore = useAgentWorkStore.getState();
      const { workspaceAgent, currentSceneId } = agentWorkStore;

      if (!workspaceAgent) return;

      const workingScenes = (workspaceAgent.scenes || []) as unknown as Scene[];

      // 1. Update Scenes List
      // We map BuildSceneData to SceneGraph objects
      const newScenes: SceneGraph[] = pendingBuildChanges.map((sceneData) => {
        // Try to match existing scene to preserve ID
        const existingScene = workingScenes.find(s => s.name === sceneData.name);

        // Calculate IDs
        const sceneId = existingScene ? existingScene.id : (-Date.now() - Math.floor(Math.random() * 1000));
        const agentId = existingScene?.agent_id || workspaceAgent.id;

        // Generate graph data
        const graphData = convertToSceneGraph(sceneData, sceneId, agentId);

        // If existing scene, we merge/replace. 
        // Since convertToSceneGraph returns a full SceneGraph, we can just use it.
        // But we might want to preserve some fields from existingScene if they are not in graphData?
        // Actually convertToSceneGraph creates a fresh one.

        return graphData;
      });

      // Update the agent with new scenes
      const newAgent = { ...workspaceAgent, scenes: newScenes };
      agentWorkStore.setWorkspaceAgent(newAgent);

      // 2. Update Current Scene Selection if needed
      // If the current scene was deleted (not in newScenes), switch to another one
      if (currentSceneId) {
        const currentSceneExists = newScenes.some(s => s.id === currentSceneId);
        if (!currentSceneExists) {
          if (newScenes.length > 0) {
            // Switch to first scene if current was deleted
            agentWorkStore.setCurrentSceneId(newScenes[0].id || null);
          } else {
            agentWorkStore.setCurrentSceneId(null);
          }
        }
      } else if (newScenes.length > 0) {
        // If no scene was selected, select the first one
        agentWorkStore.setCurrentSceneId(newScenes[0].id || null);
      }

      set({
        pendingBuildChanges: null,
        error: null
      });
    } else {
      // Fallback for unexpected data structure
      console.warn('Pending build changes is not an array:', pendingBuildChanges);
      set({ pendingBuildChanges: null, error: null });
    }
  },

  discardBuildChanges: () => {
    set({
      pendingBuildChanges: null,
      error: null
    });
  },

  clearError: () => set({ error: null }),

  reset: () => {
    set({
      buildChatHistory: [],
      currentBuildSession: null,
      pendingBuildChanges: null,
      isChatting: false,
      error: null
    });
  }
}));

export { useBuildChatStore };
