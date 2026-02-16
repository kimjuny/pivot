import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import AgentList from './components/AgentList';
import AgentDetail from './components/AgentDetail';
import Navigation from './components/Navigation';
import LoginModal from './components/LoginModal';
import { getAgentById } from './utils/api';
import type { Agent, Scene } from './types';
import { useSceneGraphStore } from './store/sceneGraphStore';

/**
 * Main application component.
 * Manages routing between agent list and agent visualization views.
 * Handles loading agent details, scenes, and scene graph state.
 * Manages login modal state for authentication.
 */
function App() {
  const [isInitializing, setIsInitializing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const [isLoginModalOpen, setIsLoginModalOpen] = useState<boolean>(false);
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

      // Use scenes directly from agent data (mapped from subscenes alias)
      const agentScenes = (agentData.scenes || []) as unknown as Scene[];
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
  }, [agentId]);

  /**
   * Load agent details when agentId changes.
   */
  useEffect(() => {
    if (agentId) {
      void loadAgentDetails();
    }
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
      // Refresh full agent details to get scenes
      const agentData = await getAgentById(parseInt(agentId));
      setAgent(agentData);
      setScenes((agentData.scenes || []) as unknown as Scene[]);
    } catch (err) {
      setError((err as Error).message || 'Failed to refresh scenes');
    }
  };

  if (isInitializing) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner"></div>
          <div className="text-lg text-muted-foreground font-medium">Loading agent details…</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-background">
        <div className="text-xl text-danger mb-4 font-medium">Error: {error}</div>
        <button
          onClick={() => void loadAgentDetails()}
          className="px-6 py-3 btn-accent rounded-lg font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!agentId) {
    return (
      <div className="min-h-screen bg-background text-foreground">
        <Navigation onLoginClick={() => setIsLoginModalOpen(true)} />
        <AgentList />
        <LoginModal open={isLoginModalOpen} onOpenChange={setIsLoginModalOpen} />
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <Navigation onLoginClick={() => setIsLoginModalOpen(true)} />
      <div className="flex-1 min-h-0 bg-background overflow-hidden">
        <AgentDetail
          agent={agent}
          scenes={scenes}
          selectedScene={selectedScene}
          agentId={parseInt(agentId)}
          onResetSceneGraph={handleResetSceneGraph}
          onSceneSelect={setSelectedScene}
          onRefreshScenes={handleRefreshScenes}
          onAgentUpdate={setAgent}
        />
      </div>
      <LoginModal open={isLoginModalOpen} onOpenChange={setIsLoginModalOpen} />
    </div>
  );
}

export default App;
