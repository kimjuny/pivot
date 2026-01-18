import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import AgentList from './components/AgentList';
import AgentVisualization from './components/AgentVisualization';
import { getAgentById, getScenes } from './utils/api';
import type { Agent, Scene } from './types';
import { useSceneGraphStore } from './store/sceneGraphStore';

/**
 * Main application component.
 * Manages routing between agent list and agent visualization views.
 * Handles loading agent details, scenes, and scene graph state.
 */
function App() {
  const [isInitializing, setIsInitializing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const { agentId } = useParams<{ agentId?: string }>();
  const navigate = useNavigate();
  const isLoadingAgentDetailsRef = useRef<boolean>(false);

  /**
   * Load agent details and associated scenes from server.
   * Filters scenes to only those belonging to current agent.
   * Automatically selects first scene if available.
   * 
   * First clears all existing state to ensure clean loading of new agent data.
   */
  const loadAgentDetails = useCallback(async () => {
    if (!agentId) return;

    if (isLoadingAgentDetailsRef.current) {
      return;
    }

    isLoadingAgentDetailsRef.current = true;
    
    setIsInitializing(true);
    setError(null);
    
    setAgent(null);
    setScenes([]);
    setSelectedScene(null);
    
    useSceneGraphStore.getState().updateSceneGraph(null);
    
    try {
      const agentData = await getAgentById(parseInt(agentId));
      setAgent(agentData);

      const scenesData = await getScenes();
      const agentScenes = scenesData.filter(scene => scene.agent_id === parseInt(agentId));
      setScenes(agentScenes);

      if (agentScenes && agentScenes.length > 0) {
        const firstScene = agentScenes[0];
        setSelectedScene(firstScene);
      }
    } catch (err) {
      setError((err as Error).message || 'Failed to load agent details');
    } finally {
      setIsInitializing(false);
      isLoadingAgentDetailsRef.current = false;
    }
  }, [agentId, setAgent, setScenes, setSelectedScene, setIsInitializing, setError]);

  /**
   * Load agent details when agentId changes.
   * Also applies dark mode class to document body.
   */
  useEffect(() => {
    if (agentId) {
      void loadAgentDetails();
    }
    document.body.classList.add('dark');
  }, [agentId, loadAgentDetails]);

  /**
   * Refresh scene graph from server.
   * Used to manually trigger a scene graph update.
   */
  const handleResetSceneGraph = async () => {
    if (!agentId) {
      setError('No agent selected');
      return;
    }
    try {
      const { refreshSceneGraph } = useSceneGraphStore.getState();
      await refreshSceneGraph(parseInt(agentId));
    } catch (err) {
      setError((err as Error).message || 'Failed to refresh scene graph');
    }
  };

  /**
   * Refresh scenes list from server.
   * Used to update scenes list after creating a new scene.
   */
  const handleRefreshScenes = async () => {
    if (!agentId) return;
    try {
      const scenesData = await getScenes();
      const agentScenes = scenesData.filter(scene => scene.agent_id === parseInt(agentId));
      setScenes(agentScenes);
    } catch (err) {
      setError((err as Error).message || 'Failed to refresh scenes');
    }
  };

  if (isInitializing) {
    return (
      <div className="flex items-center justify-center h-screen bg-dark-bg">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner"></div>
          <div className="text-lg text-dark-text-secondary font-medium">Loading agent details...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-dark-bg">
        <div className="text-xl text-red-400 mb-4 font-medium">Error: {error}</div>
        <button
          onClick={() => void loadAgentDetails()}
          className="px-6 py-3 btn-accent rounded-lg font-medium"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!agentId) {
    return <AgentList />;
  }

  return (
    <div className="h-screen flex flex-col bg-dark-bg text-dark-text-primary">
      <div className="flex-1 p-5 bg-dark-bg overflow-hidden">
        <AgentVisualization 
          agent={agent} 
          scenes={scenes} 
          selectedScene={selectedScene} 
          agentId={parseInt(agentId)}
          onResetSceneGraph={handleResetSceneGraph}
          onSceneSelect={setSelectedScene}
          onRefreshScenes={handleRefreshScenes}
        />
      </div>
    </div>
  );
}

export default App;
