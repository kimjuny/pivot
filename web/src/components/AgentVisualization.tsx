import React, { useCallback, useEffect, useState, useRef } from 'react';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  MarkerType,
  Handle,
  BezierEdge,
  Node,
  Edge,
  Connection,
  ReactFlowInstance,
  Position
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useAgentStore } from '../store/agentStore';
import ChatInterface from './ChatInterface';
import EditPanel from './EditPanel';
import { getSceneGraph } from '../utils/api';
import type { Agent, Scene, SceneGraph, SceneNode } from '../types';

interface SubsceneNodeData {
  label: string;
  type: string;
  state?: string;
  mandatory?: boolean;
  objective?: string;
}

interface SubsceneNodeProps {
  data: SubsceneNodeData;
  onClick?: () => void;
}

interface AgentVisualizationProps {
  agent: Agent | null;
  scenes: Scene[];
  selectedScene: Scene | null;
  agentId: number;
  onResetSceneGraph: () => Promise<void>;
  onSceneSelect: (scene: Scene) => void;
}

interface SelectedElement {
  type: 'node' | 'edge';
  id: string;
  data: Record<string, unknown>;
  label?: string;
}

function SubsceneNode({ data, onClick }: SubsceneNodeProps) {
  const getTypeColor = (type: string): string => {
    switch (type) {
      case 'start': return 'bg-dark-bg border-green-500 text-white';
      case 'end': return 'bg-dark-bg border-red-500 text-white';
      case 'normal': return 'bg-dark-bg border-primary text-white';
      default: return 'bg-dark-bg border-dark-border text-white';
    }
  };

  const isActive = data.state === 'active';
  const typeClasses = getTypeColor(data.type);
  const activeClass = isActive ? 'ring-2 ring-primary shadow-glow-sm' : '';

  return (
    <div
      onClick={onClick}
      className={`px-4 py-3 rounded-xl border-2 shadow-md ${typeClasses} ${activeClass} transition-all duration-200 hover:shadow-lg hover:scale-105 hover:brightness-110 cursor-pointer`}
    >
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="w-4 h-4 bg-primary hover:bg-primary/90 rounded-full border-2 border-white shadow-md"
      />
      <Handle
        type="target"
        position={Position.Left}
        id="left"
        className="w-4 h-4 bg-primary hover:bg-primary/90 rounded-full border-2 border-white shadow-md"
      />
      <div className="font-semibold text-sm truncate">{data.label}</div>
      <div className="text-xs mt-1 capitalize opacity-80">{data.type}</div>
      {isActive && <div className="text-xs text-primary font-bold mt-1.5 flex items-center">
        <span className="inline-block w-2 h-2 bg-primary rounded-full animate-pulse mr-1.5"></span>
        ACTIVE
      </div>}
    </div>
  );
}

const nodeTypes = {
  subscene: SubsceneNode,
};

const edgeTypes = {
  bezier: BezierEdge,
};

function AgentVisualization({ scenes, selectedScene, agentId, onResetSceneGraph, onSceneSelect }: AgentVisualizationProps) {
  const { sceneGraph, refreshSceneGraph } = useAgentStore();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
  const [isPreviewMode, setIsPreviewMode] = useState<boolean>(false);
  const [selectedElement, setSelectedElement] = useState<SelectedElement | null>(null);
  const [sceneGraphData, setSceneGraphData] = useState<SceneGraph | null>(null);
  const reactFlowInstanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);

  useEffect(() => {
    if (sceneGraph) {
      setSceneGraphData(sceneGraph);
    }
  }, [sceneGraph]);

  useEffect(() => {
    const resetToDefaultSceneGraph = async () => {
      if (!isPreviewMode && selectedScene) {
        try {
          const defaultGraph = await getSceneGraph(selectedScene.id);
          setSceneGraphData(defaultGraph as SceneGraph);
        } catch (error) {
          console.error('Failed to reset scene graph:', error);
        }
      }
    };
    
    void resetToDefaultSceneGraph();
  }, [isPreviewMode, selectedScene]);

  useEffect(() => {
    const loadSceneGraph = async () => {
      if (!selectedScene) {
        setSceneGraphData(null);
        return;
      }

      if (sceneGraph) {
        return;
      }

      try {
        const graphData = await getSceneGraph(selectedScene.id);
        setSceneGraphData(graphData as SceneGraph);
      } catch (error) {
        console.error('Failed to load scene graph:', error);
        setSceneGraphData(null);
      }
    };
    void loadSceneGraph();
  }, [selectedScene, sceneGraph]);

  const handleElementClick = (event: React.MouseEvent, element: Node | Edge) => {
    event.stopPropagation();
    if (element.id.startsWith('edge-')) {
      setSelectedElement({ type: 'edge', id: element.id, data: (element.data as Record<string, unknown>) || {}, label: (element.data as { label?: string }).label });
    } else {
      setSelectedElement({ type: 'node', id: element.id, data: (element.data as Record<string, unknown>) || {} });
    }
  };

  const handleNodeUpdate = (nodeId: string, updatedData: Partial<SubsceneNodeData>) => {
    setNodes((nodes) => nodes.map((node) => 
      node.id === nodeId ? { ...node, data: { ...node.data, ...updatedData } } : node
    ));
    setSelectedElement(null);
  };

  const handleEdgeUpdate = (edgeId: string, updatedData: Record<string, unknown>) => {
    setEdges((edges) => edges.map((edge) => 
      edge.id === edgeId ? { ...edge, data: { ...edge.data, ...updatedData } } : edge
    ));
    setSelectedElement(null);
  };

  const handleSave = () => {
    setSelectedElement(null);
  };

  const convertToFlowElements = useCallback((sceneGraphData: SceneGraph | null) => {
    if (!sceneGraphData || !sceneGraphData.scenes || sceneGraphData.scenes.length === 0) {
      return { nodes: [], edges: [] };
    }

    const scene = sceneGraphData.scenes[0];
    const hasSubscenesField = scene && scene.subscenes && scene.subscenes.length > 0;
    
    let subscenes: SceneNode[];
    if (hasSubscenesField) {
      subscenes = scene.subscenes || [];
    } else {
      subscenes = sceneGraphData.scenes;
    }
    
    if (!subscenes || subscenes.length === 0) {
      return { nodes: [], edges: [] };
    }

    const nodes: Node[] = [];
    const edges: Edge[] = [];
    let edgeId = 1;

    const subsceneNameToId: Record<string, string> = {};

    const startSubscenes: SceneNode[] = [];
    const normalSubscenes: SceneNode[] = [];
    const endSubscenes: SceneNode[] = [];

    subscenes.forEach((subscene) => {
      if (subscene.type === 'start') {
        startSubscenes.push(subscene);
      } else if (subscene.type === 'end') {
        endSubscenes.push(subscene);
      } else {
        normalSubscenes.push(subscene);
      }
    });

    const yPosition = 100;
    const nodeSpacing = 150;
    const xOffsets = {
      start: 100,
      normal: 300,
      end: 500
    };

    startSubscenes.forEach((subscene, index) => {
      const subsceneNodeId = `subscene-${subscene.name}`;
      nodes.push({
        id: subsceneNodeId,
        type: 'subscene',
        position: { 
          x: xOffsets.start, 
          y: yPosition + index * nodeSpacing 
        },
        data: {
          label: subscene.name || '',
          type: subscene.type,
          state: subscene.state,
          mandatory: subscene.mandatory || false,
          objective: subscene.objective || ''
        }
      });
      subsceneNameToId[subscene.name || ''] = subsceneNodeId;
    });

    normalSubscenes.forEach((subscene, index) => {
      const subsceneNodeId = `subscene-${subscene.name}`;
      nodes.push({
        id: subsceneNodeId,
        type: 'subscene',
        position: { 
          x: xOffsets.normal, 
          y: yPosition + index * nodeSpacing 
        },
        data: {
          label: subscene.name || '',
          type: subscene.type,
          state: subscene.state,
          mandatory: subscene.mandatory || false,
          objective: subscene.objective || ''
        }
      });
      subsceneNameToId[subscene.name || ''] = subsceneNodeId;
    });

    endSubscenes.forEach((subscene, index) => {
      const subsceneNodeId = `subscene-${subscene.name}`;
      nodes.push({
        id: subsceneNodeId,
        type: 'subscene',
        position: { 
          x: xOffsets.end, 
          y: yPosition + index * nodeSpacing 
        },
        data: {
          label: subscene.name || '',
          type: subscene.type,
          state: subscene.state,
          mandatory: subscene.mandatory || false,
          objective: subscene.objective || ''
        }
      });
      subsceneNameToId[subscene.name || ''] = subsceneNodeId;
    });

    subscenes.forEach((subscene) => {
      const subsceneNodeId = subsceneNameToId[subscene.name || ''];
      
      if (subscene.connections) {
        subscene.connections.forEach((connection, connIndex) => {
          const targetNodeId = subsceneNameToId[connection.to_subscene || ''];
          
          if (targetNodeId) {
            edges.push({
              id: `edge-${edgeId++}`,
              source: subsceneNodeId,
              target: targetNodeId,
              sourceHandle: 'right',
              targetHandle: 'left',
              label: connection.name,
              animated: true,
              markerEnd: { type: MarkerType.ArrowClosed },
              style: {
                stroke: '#6366f1',
                strokeWidth: 2,
                strokeOpacity: 0.8,
                strokeLinecap: 'round'
              },
              type: 'bezier',
              labelBgPadding: [8, 5],
              labelBgBorderRadius: 4,
              labelBgStyle: {
                fill: 'rgba(30, 30, 30, 0.85)',
                stroke: 'rgba(24, 91, 233, 0.3)',
                strokeWidth: 1,
                boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)'
              },
              labelStyle: {
                fontSize: 11,
                fontWeight: 500,
                fill: '#f1f5f9',
                whiteSpace: 'nowrap'
              },
              className: 'hover:stroke-opacity-100 hover:stroke-width-3 transition-all duration-200',
              data: { 
                offset: connIndex * 20,
                from_subscene: subscene.name,
                to_subscene: connection.to_subscene,
                condition: connection.condition || '',
                label: connection.name
              }
            });
          }
        });
      }
    });

    return { nodes, edges };
  }, []);

  useEffect(() => {
    if (sceneGraphData && sceneGraphData.scenes && sceneGraphData.scenes.length > 0) {
      const { nodes: newNodes, edges: newEdges } = convertToFlowElements(sceneGraphData);
      
      setNodes(newNodes);
      setEdges(newEdges);
    }
  }, [sceneGraphData, convertToFlowElements, setNodes, setEdges]);

  const onConnect = useCallback((params: Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges]);

  const onPaneClick = useCallback(() => {
    if (selectedElement) {
      setSelectedElement(null);
    }
  }, [selectedElement]);

  return (
    <div className="w-full h-full border border-dark-border rounded-xl bg-dark-bg flex flex-col card-subtle overflow-hidden">
      <div className="flex flex-1 overflow-hidden relative">
        <div 
          className={`border-r border-dark-border bg-dark-bg overflow-hidden relative ${
            isSidebarCollapsed ? 'w-0' : 'w-64'
          } transition-all duration-300 ease-in-out`}
        >
          <div 
            className={`p-4 overflow-y-auto h-full transition-opacity duration-150 ease-in-out ${
              isSidebarCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'
            }`}
          >
            <h3 className="text-md font-semibold mb-3 text-dark-text-secondary tracking-tight">Scenes</h3>
            <div className="space-y-2">
              {scenes && scenes.map((scene, index) => (
                <div 
                  key={`scene-${index}`}
                  onClick={() => onSceneSelect(scene)}
                  className={`p-3 rounded-lg cursor-pointer transition-all ${selectedScene?.name === scene.name 
                    ? 'bg-primary/20 border border-primary shadow-glow-sm' 
                    : 'bg-dark-bg-lighter border border-dark-border hover:bg-dark-border-light hover:border-dark-border'}`}
                >
                  <div className="font-medium text-dark-text-primary">{scene.name}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
        
        <div className="flex-1 overflow-hidden bg-dark-bg relative">
          <div 
            className={`absolute inset-0 transition-all duration-300 ease-in-out ${
              isPreviewMode ? 'right-96' : 'right-0'
            }`}
          >
            {isPreviewMode && (
              <div className="absolute top-4 left-4 z-10 flex items-center space-x-2 px-4 py-2 bg-primary/20 border border-primary rounded-lg shadow-glow-sm">
                <div className="relative">
                  <div className="w-2 h-2 bg-red-500 rounded-full animate-ping absolute -left-1 -top-1"></div>
                  <div className="w-2 h-2 bg-red-500 rounded-full relative"></div>
                </div>
                <span className="text-sm font-semibold text-white">Realtime Graph</span>
              </div>
            )}
            
            <div className="absolute top-4 right-4 z-10 flex space-x-2">
              <button
                onClick={() => void onResetSceneGraph()}
                className="flex items-center space-x-2 px-4 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-sm font-medium hover:bg-primary hover:border-primary hover:shadow-glow-sm transition-all duration-200"
                title="Reset to default scene graph"
              >
                <svg className="w-4 h-4 text-dark-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5a2 2 0 00-2 2v5a2 2 0 002-2V4M6 4v5a2 2 0 00-2 2v5a2 2 0 002-2V4" />
                </svg>
                <span>Reset</span>
              </button>
              <button
                onClick={() => void refreshSceneGraph()}
                className="flex items-center space-x-2 px-4 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-sm font-medium hover:bg-primary hover:border-primary hover:shadow-glow-sm transition-all duration-200"
                title="Refresh"
              >
                <svg className="w-4 h-4 text-dark-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 7m0 0C4.582 13.001 6 11.59 6 10a4 4 0 118 0c0 1.59 1.418 3 3.164 3v5M16 16l-4-4m4 4l-4 4" />
                </svg>
                <span>Refresh</span>
              </button>
              
              <button
                onClick={() => setIsPreviewMode(!isPreviewMode)}
                className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
                  isPreviewMode 
                    ? 'bg-primary text-white shadow-glow-sm' 
                    : 'bg-dark-bg-lighter border border-dark-border hover:bg-primary hover:border-primary hover:shadow-glow-sm'
                }`}
                title={isPreviewMode ? 'Exit Preview' : 'Enter Preview'}
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542 7z" />
                </svg>
                <span>Preview</span>
              </button>
              
              <button
                onClick={handleSave}
                className="flex items-center space-x-2 px-4 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-sm font-medium hover:bg-primary hover:border-primary hover:shadow-glow-sm transition-all duration-200"
                title="Save"
              >
                <svg className="w-4 h-4 text-dark-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
                </svg>
                <span>Save</span>
              </button>
            </div>
            
            <button
              onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
              className={`absolute top-1/2 -translate-y-1/2 z-10 p-2.5 rounded-lg transition-all duration-200 group ${
                isSidebarCollapsed 
                  ? 'left-2 bg-dark-bg-lighter border border-dark-border hover:bg-primary hover:border-primary hover:shadow-glow-sm' 
                  : '-left-3 bg-dark-bg border border-dark-border hover:bg-primary hover:border-primary hover:shadow-glow-sm'
              }`}
              title={isSidebarCollapsed ? 'Expand Scenes' : 'Collapse Scenes'}
            >
              <svg
                className={`w-5 h-5 text-dark-text-secondary transition-transform duration-200 ${isSidebarCollapsed ? 'rotate-180' : ''}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
                />
              </svg>
            </button>
            
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onPaneClick={onPaneClick}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              onNodeClick={(event, node) => handleElementClick(event, node)}
              onEdgeClick={(event, edge) => handleElementClick(event, edge)}
              onInit={(instance) => {
                reactFlowInstanceRef.current = instance;
              }}
            >
              <Controls />
              <MiniMap />
              <Background />
            </ReactFlow>
            
            {selectedElement && !isPreviewMode && (
              <EditPanel
                key={`${selectedElement.type}-${selectedElement.id}`}
                element={selectedElement}
                onClose={() => setSelectedElement(null)}
                onNodeChange={handleNodeUpdate}
                onEdgeChange={handleEdgeUpdate}
                onSave={handleSave}
              />
            )}
          </div>
          
          {isPreviewMode && (
            <div className="absolute top-0 right-0 h-full w-96 bg-dark-bg border-l border-dark-border transition-all duration-300 ease-in-out overflow-hidden translate-x-0 opacity-100">
              <ChatInterface agentId={agentId} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default AgentVisualization;
