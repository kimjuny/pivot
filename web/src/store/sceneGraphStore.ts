import { create } from 'zustand';
import type { SceneGraph } from '../types';
import { fetchSceneGraph } from '../utils/api';
import websocket from '../utils/websocket';

/**
 * Store for managing SceneGraph state and operations.
 * Handles scene graph data fetching, updates, and WebSocket synchronization.
 */
interface SceneGraphStore {
  /** Current scene graph data */
  sceneGraph: SceneGraph | null;
  /** Loading state for scene graph operations */
  isLoadingSceneGraph: boolean;
  /** Error message from last operation */
  error: string | null;
  /** Refresh scene graph data from server */
  refreshSceneGraph: () => Promise<void>;
  /** Update scene graph with provided data */
  updateSceneGraph: (sceneGraph: SceneGraph | null) => void;
  /** Clear error message */
  clearError: () => void;
}

const useSceneGraphStore = create<SceneGraphStore>((set) => ({
  sceneGraph: null,
  isLoadingSceneGraph: false,
  error: null,

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

  updateSceneGraph: (sceneGraph: SceneGraph | null) => {
    set({ sceneGraph, error: null });
  },

  clearError: () => set({ error: null })
}));

/**
 * Establish WebSocket connection and listen for scene updates.
 * This is called once when the module is loaded to enable real-time updates.
 */
websocket.connect();

/**
 * Handle WebSocket messages for scene graph updates.
 * When a scene_update message is received, update the scene graph state.
 */
websocket.on('message', (data) => {
  if ((data as { type?: string }).type === 'scene_update') {
    const sceneGraphCopy = JSON.parse(JSON.stringify((data as { data?: unknown }).data)) as SceneGraph;
    useSceneGraphStore.setState({ sceneGraph: sceneGraphCopy });
  }
});

export { useSceneGraphStore };
