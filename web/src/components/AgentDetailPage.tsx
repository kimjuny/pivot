import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import AgentDetail from './AgentDetail';
import Navigation from './Navigation';
import { getAgentById, AuthError } from '../utils/api';
import type { Agent, Scene } from '../types';
import { useSceneGraphStore } from '../store/sceneGraphStore';
import { useAgentTabStore } from '../store/agentTabStore';
import { isTokenValid } from '../contexts/AuthContext';

/**
 * Agent Detail Page component.
 * Handles loading agent details and renders the AgentDetail component.
 * Redirects to login if not authenticated.
 */
function AgentDetailPage() {
  const [isInitializing, setIsInitializing] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const isLoadingAgentDetailsRef = useRef<boolean>(false);

  /**
   * Load agent details and associated scenes from server.
   */
  const loadAgentDetails = useCallback(async () => {
    if (!agentId) return;

    // Check authentication first
    if (!isTokenValid()) {
      navigate('/', { replace: true });
      return;
    }

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

      // Use scenes directly from agent data
      const agentScenes = (agentData.scenes || []) as unknown as Scene[];
      setScenes(agentScenes);

      if (agentScenes && agentScenes.length > 0) {
        const firstScene = agentScenes[0];
        setSelectedScene(firstScene);
      }
    } catch (err) {
      // Redirect to login for auth errors
      if (err instanceof AuthError) {
        navigate('/', { replace: true });
        return;
      }
      setError((err as Error).message || 'Failed to load agent details');
    } finally {
      setIsInitializing(false);
      isLoadingAgentDetailsRef.current = false;
    }
  }, [agentId, navigate]);

  /**
   * Load agent details when agentId changes.
   */
  useEffect(() => {
    void loadAgentDetails();
  }, [agentId, loadAgentDetails]);

  /**
   * Clear tab store when leaving the page or switching to a different agent.
   * This prevents tabs from previous agent appearing when viewing a new agent.
   */
  useEffect(() => {
    return () => {
      useAgentTabStore.getState().closeAllTabs();
    };
  }, [agentId]);

  /**
   * Open a tab for the first scene when the page loads with scenes available.
   * This ensures users see content immediately instead of an empty state.
   */
  useEffect(() => {
    if (selectedScene && !isInitializing) {
      useAgentTabStore.getState().openTab({
        type: 'scene',
        name: selectedScene.name,
        resourceId: selectedScene.id,
      });
    }
  }, [selectedScene, isInitializing]);

  /**
   * Refresh scenes list from server.
   */
  const handleRefreshScenes = async () => {
    if (!agentId) return;
    try {
      const agentData = await getAgentById(parseInt(agentId));
      setAgent(agentData);
      setScenes((agentData.scenes || []) as unknown as Scene[]);
    } catch (err) {
      if (!(err instanceof AuthError)) {
        setError((err as Error).message || 'Failed to refresh scenes');
      }
    }
  };

  // Loading state
  if (isInitializing) {
    return (
      <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
        <Navigation />
        <div className="flex-1 flex items-center justify-center">
          <div className="flex flex-col items-center space-y-4">
            <div className="spinner"></div>
            <div className="text-lg text-muted-foreground font-medium">Loading agent details…</div>
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
        <Navigation />
        <div className="flex-1 flex flex-col items-center justify-center">
          <div className="text-xl text-destructive mb-4 font-medium">Error: {error}</div>
          <button
            onClick={() => void loadAgentDetails()}
            className="px-6 py-3 btn-accent rounded-lg font-medium"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Agent not found
  if (!agent) {
    return (
      <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
        <Navigation />
        <div className="flex-1 flex flex-col items-center justify-center">
          <div className="text-xl text-muted-foreground mb-4 font-medium">Agent not found</div>
          <button
            onClick={() => navigate('/agents')}
            className="px-6 py-3 btn-accent rounded-lg font-medium"
          >
            Back to Agents
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-background text-foreground overflow-hidden">
      <Navigation />
      <div className="flex-1 min-h-0 bg-background overflow-hidden">
        <AgentDetail
          agent={agent}
          scenes={scenes}
          selectedScene={selectedScene}
          agentId={parseInt(agentId!)}
          onResetSceneGraph={async () => {}}
          onSceneSelect={setSelectedScene}
          onRefreshScenes={handleRefreshScenes}
          onAgentUpdate={setAgent}
        />
      </div>
    </div>
  );
}

export default AgentDetailPage;
