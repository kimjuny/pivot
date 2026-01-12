import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import AgentList from './components/AgentList';
import AgentVisualization from './components/AgentVisualization';
import { useAgentStore } from './store/agentStore';
import { getAgentById, getScenes } from './utils/api';
import type { Agent, Scene } from './types';

function App() {
  const { agentState, initializeAgent, sceneGraph, refreshSceneGraph } = useAgentStore();
  const [isInitializing, setIsInitializing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [agent, setAgent] = useState<Agent | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null);
  const { agentId } = useParams<{ agentId?: string }>();
  const navigate = useNavigate();

  useEffect(() => {
    if (agentId) {
      loadAgentDetails();
    }
    document.body.classList.add('dark');
  }, [agentId]);

  const loadAgentDetails = async () => {
    if (!agentId) return;
    
    setIsInitializing(true);
    setError(null);
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
      const error = err as Error;
      setError(error.message);
    } finally {
      setIsInitializing(false);
    }
  };

  const handleResetSceneGraph = async () => {
    try {
      await refreshSceneGraph();
    } catch (err) {
      const error = err as Error;
      setError(error.message);
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
          onClick={loadAgentDetails}
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
        />
      </div>
    </div>
  );
}

export default App;
