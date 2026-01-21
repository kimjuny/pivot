import { create } from 'zustand';
import type { SceneGraph } from '../types';
import { getSceneGraph } from '../utils/api';

/**
 * Store for managing SceneGraph state and operations.
 * Handles scene graph data fetching and updates.
 */
interface SceneGraphStore {
  /** Current scene graph data */
  sceneGraph: SceneGraph | null;
  /** Loading state for scene graph operations */
  isLoadingSceneGraph: boolean;
  /** Error message from last operation */
  error: string | null;
  /** Refresh scene graph data from server for a specific scene */
  refreshSceneGraph: (sceneId: number) => Promise<void>;
  /** Update scene graph with provided data */
  updateSceneGraph: (sceneGraph: SceneGraph | null) => void;
  /** Clear error message */
  clearError: () => void;
}

const useSceneGraphStore = create<SceneGraphStore>((set) => ({
  sceneGraph: null,
  isLoadingSceneGraph: false,
  error: null,

  refreshSceneGraph: async (sceneId: number) => {
    set({ isLoadingSceneGraph: true, error: null });
    try {
      const sceneGraph = await getSceneGraph(sceneId);
      set({ 
        sceneGraph: sceneGraph as SceneGraph | null,
        isLoadingSceneGraph: false,
        error: null
      });
    } catch (error) {
      const err = error instanceof Error ? error : new Error(String(error));
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

export { useSceneGraphStore };
