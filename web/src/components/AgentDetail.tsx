import React, { useCallback, useEffect, useState, useRef } from 'react';
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  BezierEdge,
  Node,
  Edge,
  Connection,
  ReactFlowInstance
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { X } from 'lucide-react';
import { usePreviewChatStore } from '../store/previewChatStore';
import { useAgentWorkStore } from '../store/agentWorkStore';
import { useBuildChatStore } from '../store/buildChatStore';
import { useAgentTabStore } from '../store/agentTabStore';
import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import DraggableDialog from './DraggableDialog';
import BuildChatInterface from './BuildChatInterface';
import PreviewChatInterface from './PreviewChatInterface';
import ReactChatInterface from './ReactChatInterface';
import EditPanel from './EditPanel';
import SceneModal from './SceneModal';
import SubsceneModal from './SubsceneModal';
import ConnectionModal from './ConnectionModal';
import SubsceneNode from './SubsceneNode';
import AgentDetailSidebar from './AgentDetailSidebar';
import ControlButtons from './ControlButtons';
import SceneContextMenu, { ContextMenuContext } from './SceneContextMenu';
import SubmitArea from './SubmitArea';
import { updateAgentScenes } from '../utils/api';
import { deepCopyAgent, deepCopySceneGraph } from '../utils/compare';
import type { Agent, Scene, SceneGraph, SceneNode } from '../types';

const nodeTypes = {
  subscene: SubsceneNode,
};

const edgeTypes = {
  bezier: BezierEdge,
};

interface SelectedElement {
  type: 'node' | 'edge';
  id: string;
  data: Record<string, unknown>;
  label?: string;
  clickPosition?: { x: number; y: number };
}

interface AgentDetailProps {
  agent: Agent | null;
  scenes: Scene[];
  selectedScene: Scene | null;
  agentId: number;
  onResetSceneGraph: () => Promise<void>;
  onSceneSelect: (scene: Scene) => void;
  onRefreshScenes: () => Promise<void>;
  onAgentUpdate?: (agent: Agent) => void;
}

function AgentDetail({ agent, scenes, selectedScene, agentId, onSceneSelect, onRefreshScenes, onAgentUpdate }: AgentDetailProps) {
  const { chatHistory } = usePreviewChatStore();
  const {
    workspaceAgent,
    previewAgent,
    currentSceneId,
    hasUnsavedChanges,
    isSubmitting,
    initialize,
    setWorkspaceAgent,
    updateSceneInWorkspace,
    setCurrentSceneId,
    enterPreviewMode,
    discardChanges,
    markAsCommitted,
    setSubmitting,
    reset
  } = useAgentWorkStore();
  const { reset: resetBuildChat } = useBuildChatStore();
  const { tabs, activeTabId, setActiveTab, closeTab } = useAgentTabStore();

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isBuildChatOpen, setIsBuildChatOpen] = useState<boolean>(false);
  const [isReactChatOpen, setIsReactChatOpen] = useState<boolean>(false);
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [selectedElement, setSelectedElement] = useState<SelectedElement | null>(null);
  // Removed: previewModeSceneGraphData - now using previewAgent from store
  const [isCreateSceneModalOpen, setIsCreateSceneModalOpen] = useState<boolean>(false);
  const [isEditSceneModalOpen, setIsEditSceneModalOpen] = useState<boolean>(false);
  const [isAddSubsceneModalOpen, setIsAddSubsceneModalOpen] = useState<boolean>(false);
  const [isAddConnectionModalOpen, setIsAddConnectionModalOpen] = useState<boolean>(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [contextMenuContext, setContextMenuContext] = useState<ContextMenuContext>('pane');
  const [contextMenuElement, setContextMenuElement] = useState<{ id: string; data?: Record<string, unknown> } | null>(null);
  const [pendingConnection, setPendingConnection] = useState<{ from: string; to: string } | null>(null);
  const [newSubscenePosition, setNewSubscenePosition] = useState<{ x: number; y: number } | null>(null);
  const reactFlowInstanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);

  // Derived state: workspaceAgent for edit mode, previewAgent for preview mode
  const workingScenes = (workspaceAgent?.scenes || []) as unknown as Scene[];
  const workingSceneGraph = workspaceAgent?.scenes?.find(s => s.id === currentSceneId) || null;
  const previewSceneGraph = previewAgent?.scenes?.find(s => s.id === currentSceneId) || null;

  // Detect current theme for graph styling
  const [isDarkMode, setIsDarkMode] = useState(() =>
    document.documentElement.classList.contains('dark')
  );

  // Initialize store with agent data
  useEffect(() => {
    if (agent) {
      initialize(agent);
    }
  }, [agent, initialize]);

  // Sync selectedScene with store
  useEffect(() => {
    if (selectedScene) {
      setCurrentSceneId(selectedScene.id);
    }
  }, [selectedScene, setCurrentSceneId]);

  // Monitor theme changes
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDarkMode(document.documentElement.classList.contains('dark'));
    });

    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });

    return () => observer.disconnect();
  }, []);

  const handleCreateSceneModalOpen = () => {
    setIsCreateSceneModalOpen(true);
  };

  const handleCreateScene = async (sceneData: {
    name: string;
    description?: string;
  }) => {
    if (!workspaceAgent) return;

    const newSceneId = -Date.now();
    const newScene: SceneGraph = {
      id: newSceneId,
      name: sceneData.name,
      description: sceneData.description || '',
      agent_id: agentId,
      subscenes: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };

    const newAgent = deepCopyAgent(workspaceAgent);
    if (newAgent) {
      newAgent.scenes = [...(newAgent.scenes || []), newScene];
      setWorkspaceAgent(newAgent);
    }

    setIsCreateSceneModalOpen(false);
    onSceneSelect(newScene as unknown as Scene);
    await Promise.resolve();
  };

  const handleEditScene = async (sceneData: {
    name: string;
    description?: string;
  }) => {
    if (!workspaceAgent || !selectedScene) return;

    const newAgent = deepCopyAgent(workspaceAgent);
    if (newAgent && newAgent.scenes) {
      const sceneIndex = newAgent.scenes.findIndex(s => s.id === selectedScene.id);
      if (sceneIndex !== -1) {
        const scene = newAgent.scenes[sceneIndex] as unknown as SceneGraph;
        scene.name = sceneData.name;
        scene.description = sceneData.description || '';
        scene.updated_at = new Date().toISOString();
        setWorkspaceAgent(newAgent);
      }
    }

    setIsEditSceneModalOpen(false);
    await Promise.resolve();
  };

  const handleDeleteScene = (sceneToDelete: Scene) => {
    if (!workspaceAgent) return;

    const newAgent = deepCopyAgent(workspaceAgent);
    if (newAgent && newAgent.scenes) {
      newAgent.scenes = newAgent.scenes.filter(s => s.id !== sceneToDelete.id);
      setWorkspaceAgent(newAgent);

      // If the deleted scene was selected, clear selection
      if (currentSceneId === sceneToDelete.id) {
        const remainingScenes = newAgent.scenes;
        if (remainingScenes.length > 0) {
          onSceneSelect(remainingScenes[0] as unknown as Scene);
        } else {
          // Handle no scenes left
          setCurrentSceneId(null);
        }
      }
    }
  };

  const handleAddSubscene = (formData: { name: string; type: 'start' | 'normal' | 'end'; mandatory: boolean; objective: string }) => {
    setIsAddSubsceneModalOpen(false);
    setContextMenu(null);
    if (workingSceneGraph && currentSceneId) {
      const newGraph = deepCopySceneGraph(workingSceneGraph);
      if (!newGraph) return;

      const newSubsceneName = formData.name || `subscene-${Date.now()}`;
      const newSubsceneData = {
        id: newSubsceneName, // Frontend uses name as ID often, or string ID
        name: formData.name,
        type: formData.type,
        state: 'inactive' as const,
        position: { x: 300, y: 100 },
        data: {
          label: formData.name,
          type: formData.type,
          state: 'inactive',
          description: '',
          mandatory: formData.mandatory,
          objective: formData.objective
        },
        connections: [],
        subscenes: []
      };

      // Push directly to subscenes array (flattened structure)
      newGraph.subscenes.push(newSubsceneData as unknown as SceneNode);

      updateSceneInWorkspace(currentSceneId, newGraph);
    }
  };

  const handleAddConnection = (formData: { name: string; condition: string; from_subscene: string; to_subscene: string }) => {
    setIsAddConnectionModalOpen(false);
    setPendingConnection(null);
    if (workingSceneGraph && pendingConnection && currentSceneId) {
      const newGraph = deepCopySceneGraph(workingSceneGraph);
      if (!newGraph) return;

      const fromSubscene = newGraph.subscenes.find(s => s.name === pendingConnection.from);
      if (!fromSubscene) return;

      const newConnection = {
        id: Date.now(),
        name: formData.name,
        condition: formData.condition,
        from_subscene: pendingConnection.from,
        to_subscene: pendingConnection.to,
        scene_id: currentSceneId,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
      };

      fromSubscene.connections = fromSubscene.connections || [];
      fromSubscene.connections.push(newConnection);

      updateSceneInWorkspace(currentSceneId, newGraph);
    }
  };

  const handleContextMenu = (event: React.MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    if (mode === 'edit' && currentSceneId) {
      try {
        const reactFlowBounds = (event.currentTarget as HTMLElement).getBoundingClientRect();
        const flowPosition = {
          x: event.clientX - reactFlowBounds.left,
          y: event.clientY - reactFlowBounds.top
        };
        setContextMenu({
          x: event.clientX,
          y: event.clientY
        });
        setNewSubscenePosition({ x: flowPosition.x, y: flowPosition.y });
        setContextMenuContext('pane');
        setContextMenuElement(null);
      } catch (err) {
        const error = err instanceof Error ? err : new Error(String(err));
        console.error('Failed to calculate position:', error);
        setContextMenu({
          x: event.clientX,
          y: event.clientY
        });
        setNewSubscenePosition({ x: 0, y: 0 });
        setContextMenuContext('pane');
        setContextMenuElement(null);
      }
    }
  };

  const handleNodeContextMenu = (event: React.MouseEvent, node: Node) => {
    event.preventDefault();
    event.stopPropagation();
    if (mode === 'edit') {
      setContextMenu({
        x: event.clientX,
        y: event.clientY
      });
      setContextMenuContext('node');
      setContextMenuElement({ id: node.id, data: node.data });
    }
  };

  const handleEdgeContextMenu = (event: React.MouseEvent, edge: Edge) => {
    event.preventDefault();
    event.stopPropagation();
    if (mode === 'edit') {
      setContextMenu({
        x: event.clientX,
        y: event.clientY
      });
      setContextMenuContext('edge');
      setContextMenuElement({ id: edge.id, data: edge.data });
    }
  };

  const handleContextMenuClose = () => {
    setContextMenu(null);
  };

  const handleAddSubsceneFromMenu = () => {
    setContextMenu(null);
    setIsAddSubsceneModalOpen(true);
  };

  const handleRemoveNode = (nodeId: string) => {
    if (!workingSceneGraph || !currentSceneId) return;

    const newGraph = deepCopySceneGraph(workingSceneGraph);
    if (!newGraph) return;

    const subsceneName = nodeId.replace('subscene-', '');

    // Remove subscene from subscenes array
    newGraph.subscenes = newGraph.subscenes.filter(s => s.name !== subsceneName);

    // Remove all connections pointing to/from this subscene
    newGraph.subscenes.forEach(subscene => {
      if (subscene.connections) {
        subscene.connections = subscene.connections.filter(c =>
          c.to_subscene !== subsceneName && c.from_subscene !== subsceneName
        );
      }
    });

    updateSceneInWorkspace(currentSceneId, newGraph);
    setContextMenu(null);
  };

  const handleRemoveEdge = (edgeId: string) => {
    if (!workingSceneGraph || !currentSceneId) return;

    const newGraph = deepCopySceneGraph(workingSceneGraph);
    if (!newGraph) return;

    const edgeData = contextMenuElement?.data;
    if (!edgeData) return;

    const fromSubsceneName = edgeData.from_subscene;
    const toSubsceneName = edgeData.to_subscene;

    const fromSubscene = newGraph.subscenes.find(s => s.name === fromSubsceneName);
    if (fromSubscene && fromSubscene.connections) {
      fromSubscene.connections = fromSubscene.connections.filter(c =>
        c.to_subscene !== toSubsceneName
      );
    }

    updateSceneInWorkspace(currentSceneId, newGraph);
    setContextMenu(null);
  };

  useEffect(() => {
    const handleClickOutside = () => {
      if (contextMenu) {
        setContextMenu(null);
      }
    };

    if (contextMenu) {
      document.addEventListener('click', handleClickOutside);
      return () => {
        document.removeEventListener('click', handleClickOutside);
      };
    }
  }, [contextMenu]);

  // Critical: Read from the correct state based on mode
  // - Preview mode: Read from previewAgent (updated via SSE events)
  // - Edit mode: Read from workspaceAgent (user's working copy)
  const currentSceneGraphData = mode === 'preview' ? previewSceneGraph : workingSceneGraph;

  const handleElementClick = (event: React.MouseEvent, element: Node | Edge) => {
    event.stopPropagation();
    const clickPosition = { x: event.clientX, y: event.clientY };
    if (element.id.startsWith('edge-')) {
      setSelectedElement({ type: 'edge', id: element.id, data: (element.data as Record<string, unknown>) || {}, label: (element.data as { label?: string }).label, clickPosition });
    } else {
      setSelectedElement({ type: 'node', id: element.id, data: (element.data as Record<string, unknown>) || {}, clickPosition });
    }
  };

  const handleNodeUpdate = (nodeId: string, formData: { name: string; type: 'start' | 'normal' | 'end'; mandatory: boolean; objective: string }) => {
    if (!workingSceneGraph || !currentSceneId) return;

    const newGraph = deepCopySceneGraph(workingSceneGraph);
    if (!newGraph) return;

    const subsceneName = nodeId.replace('subscene-', '');
    const subscene = newGraph.subscenes.find(s => s.name === subsceneName);

    if (subscene) {
      subscene.name = formData.name;
      subscene.type = formData.type;
      subscene.mandatory = formData.mandatory;
      subscene.objective = formData.objective;

      updateSceneInWorkspace(currentSceneId, newGraph);
    }

    setNodes((nodes) => nodes.map((node) =>
      node.id === nodeId ? { ...node, data: { ...node.data, label: formData.name, type: formData.type, mandatory: formData.mandatory, objective: formData.objective } } : node
    ));
  };

  const handleEdgeUpdate = (edgeId: string, formData: { name: string; condition: string; from_subscene: string; to_subscene: string }) => {
    if (!workingSceneGraph || !currentSceneId) return;

    const newGraph = deepCopySceneGraph(workingSceneGraph);
    if (!newGraph) return;

    const fromSubsceneName = formData.from_subscene;
    const toSubsceneName = formData.to_subscene;

    const fromSubscene = newGraph.subscenes.find(s => s.name === fromSubsceneName);
    if (fromSubscene && fromSubscene.connections) {
      const connection = fromSubscene.connections.find(c => c.to_subscene === toSubsceneName);
      if (connection) {
        connection.name = formData.name;
        connection.condition = formData.condition;

        updateSceneInWorkspace(currentSceneId, newGraph);
      }
    }

    setEdges((edges) => edges.map((edge) => {
      const edgeData = edge.data;
      return edge.id === edgeId ? { ...edge, data: { ...(edgeData || {}), label: formData.name, condition: formData.condition } } : edge;
    }));
  };

  const convertToFlowElements = useCallback((sceneGraphData: SceneGraph | null) => {
    // Cast to any to handle potential legacy/agent structure during transition
    // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-assignment
    const data = sceneGraphData as any;
    if (!data) {
      return { nodes: [], edges: [] };
    }

    let subscenes: SceneNode[] = [];

    // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
    if (data.subscenes && data.subscenes.length > 0) {
      // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access
      subscenes = data.subscenes;
      // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
    } else if (data.scenes && data.scenes.length > 0) {
      // Handle Agent structure (list of scenes)
      // eslint-disable-next-line @typescript-eslint/no-unsafe-member-access
      if (data.scenes[0].subscenes) {
        // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access
        subscenes = data.scenes[0].subscenes;
      } else {
        // Handle legacy where scenes = subscenes
        // eslint-disable-next-line @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access
        subscenes = data.scenes;
      }
    }

    if (!subscenes || subscenes.length === 0) {
      return { nodes: [], edges: [] };
    }

    const nodes: Node[] = [];
    const edges: Edge[] = [];
    let edgeId = 1;

    const subsceneNameToId: Record<string, string> = {};

    const startSubscenes: typeof subscenes = [];
    const normalSubscenes: typeof subscenes = [];
    const endSubscenes: typeof subscenes = [];

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

    const processSubscene = (subscene: typeof subscenes[0], index: number, offset: number) => {
      const subsceneNodeId = `subscene-${subscene.name}`;
      nodes.push({
        id: subsceneNodeId,
        type: 'subscene',
        position: {
          x: offset,
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
    };

    startSubscenes.forEach((s, i) => processSubscene(s, i, xOffsets.start));
    normalSubscenes.forEach((s, i) => processSubscene(s, i, xOffsets.normal));
    endSubscenes.forEach((s, i) => processSubscene(s, i, xOffsets.end));

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
                stroke: isDarkMode ? '#6366f1' : '#818cf8',
                strokeWidth: 2,
                strokeOpacity: isDarkMode ? 0.8 : 0.6,
                strokeLinecap: 'round'
              },
              type: 'bezier',
              labelBgPadding: [8, 5],
              labelBgBorderRadius: 4,
              labelBgStyle: {
                fill: isDarkMode ? 'rgba(30, 30, 30, 0.85)' : 'rgba(255, 255, 255, 0.9)',
                stroke: isDarkMode ? 'rgba(24, 91, 233, 0.3)' : 'rgba(99, 102, 241, 0.3)',
                strokeWidth: 1,
                boxShadow: isDarkMode ? '0 2px 8px rgba(0, 0, 0, 0.3)' : '0 2px 8px rgba(0, 0, 0, 0.1)'
              },
              labelStyle: {
                fontSize: 11,
                fontWeight: 500,
                fill: isDarkMode ? '#f1f5f9' : '#1e293b',
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
  }, [isDarkMode]);

  useEffect(() => {
    if (currentSceneGraphData) {
      const { nodes: newNodes, edges: newEdges } = convertToFlowElements(currentSceneGraphData);
      setNodes(newNodes);
      setEdges(newEdges);
    } else {
      setNodes([]);
      setEdges([]);
    }
  }, [currentSceneGraphData, convertToFlowElements, setNodes, setEdges]);

  const handleModeChange = (newMode: 'edit' | 'preview') => {
    setMode(newMode);

    if (newMode === 'preview') {
      // Copy workspaceAgent to previewAgent in store
      enterPreviewMode();
    }
    // When exiting preview, graph automatically reverts to workspaceAgent
  };

  const onConnect = useCallback((params: Connection) => {
    const fromSubscene = params.source.replace('subscene-', '');
    const toSubscene = params.target.replace('subscene-', '');

    if (params.sourceHandle === 'right' && params.targetHandle === 'left') {
      setPendingConnection({ from: fromSubscene, to: toSubscene });
      setIsAddConnectionModalOpen(true);
    } else {
      console.warn('Invalid connection: Only right-handle to left-handle connections are allowed');
    }
  }, []);

  const onPaneClick = useCallback(() => {
    if (selectedElement) {
      setSelectedElement(null);
    }
    if (contextMenu) {
      setContextMenu(null);
    }
  }, [selectedElement, contextMenu]);

  const handleSubmit = async () => {
    if (!workspaceAgent || !workspaceAgent.scenes) return;
    setSubmitting(true);

    try {
      // Construct payload for all scenes
      const scenesPayload = workspaceAgent.scenes.map(scene => {
        return {
          name: scene.name || '',
          description: scene.description || undefined,
          graph: scene.subscenes.map((subscene) => ({
            name: subscene.name || subscene.data?.label || '',
            type: subscene.type || subscene.data?.type || 'normal',
            state: subscene.state || subscene.data?.state || 'inactive',
            description: subscene.data?.description || '',
            mandatory: subscene.mandatory ?? subscene.data?.mandatory ?? false,
            objective: subscene.objective ?? subscene.data?.objective ?? '',
            connections: subscene.connections?.map((conn) => ({
              name: conn.name || '',
              condition: conn.condition,
              to_subscene: conn.to_subscene
            })) || []
          }))
        };
      });

      // 1. Single API Call to sync everything
      const updatedScenes = await updateAgentScenes(agentId, scenesPayload);

      // 2. Mark everything as committed (update Original to match Workspace)
      // Ideally we should update originalAgent with the response from server (updatedScenes).
      // But updateAgentScenes only returns Scene[] (with updated IDs).
      // We might need to fetch full agent again to be perfectly safe, or just merge IDs.
      // For now, let's fetch full agent to be safe.

      // Notify parent to refresh
      await onRefreshScenes(); // This now fetches full agent in App.tsx

      // We don't strictly need to call markAsCommitted here if onRefreshScenes triggers initialization.
      // But markAsCommitted clears the dirty flag.
      markAsCommitted();

    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to submit changes:', error);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDiscard = () => {
    discardChanges();
  };

  return (
    <SidebarProvider defaultOpen={true}>
      <AgentDetailSidebar
        agent={agent}
        scenes={workingScenes}
        selectedScene={selectedScene}
        onSceneSelect={onSceneSelect}
        onCreateScene={handleCreateSceneModalOpen}
        onDeleteScene={handleDeleteScene}
        onOpenBuildChat={() => setIsBuildChatOpen(true)}
        onOpenReactChat={() => setIsReactChatOpen(true)}
        onAgentUpdate={onAgentUpdate}
      />

      <SidebarInset className="flex flex-col bg-background overflow-hidden">
        {/* Main Content Area */}
        <div className="flex-1 relative overflow-hidden flex flex-col">
          {/* Sidebar Trigger Button - Floating */}
          <div className="absolute top-3 left-3 z-10">
            <SidebarTrigger />
          </div>

          {mode === 'preview' && (
            <div className="absolute top-3 left-14 z-10 flex items-center gap-2 px-3 py-1.5 bg-primary/20 border border-primary rounded-lg">
              <div className="relative">
                <div className="w-2 h-2 bg-danger rounded-full animate-ping absolute" />
                <div className="w-2 h-2 bg-danger rounded-full relative" />
              </div>
              <span className="text-xs font-medium text-foreground">Realtime Graph</span>
            </div>
          )}

          <ControlButtons
            mode={mode}
            onModeChange={handleModeChange}
          />

          {/* Tabs System */}
          {tabs.length > 0 ? (
            <Tabs
              value={activeTabId || undefined}
              onValueChange={setActiveTab}
              className="flex-1 flex flex-col overflow-hidden"
            >
              {/* Tabs List */}
              <div className="border-b border-border bg-muted/30 px-3 pt-14">
                <TabsList className="h-auto bg-transparent p-0 gap-1">
                  {tabs.map((tab) => (
                    <div key={tab.id} className="relative group">
                      <TabsTrigger
                        value={tab.id}
                        className="relative rounded-t-md rounded-b-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-background data-[state=inactive]:bg-transparent px-4 py-2 text-sm font-medium transition-all hover:bg-background/50"
                      >
                        <span className="mr-6">{tab.name}</span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            closeTab(tab.id);
                          }}
                          className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded hover:bg-muted transition-colors opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                          aria-label={`Close ${tab.name} tab`}
                        >
                          <X className="size-3.5" />
                        </button>
                      </TabsTrigger>
                    </div>
                  ))}
                </TabsList>
              </div>

              {/* Tab Content Areas */}
              {tabs.map((tab) => (
                <TabsContent
                  key={tab.id}
                  value={tab.id}
                  className="flex-1 m-0 relative overflow-hidden data-[state=inactive]:hidden"
                >
                  {tab.type === 'scene' ? (
                    // Scene content with ReactFlow graph
                    <div
                      className={`absolute inset-0 transition-all duration-300 ease-in-out ${mode === 'preview' ? 'right-96' : 'right-0'
                        }`}
                    >
                      <ReactFlow
                        nodes={nodes}
                        edges={edges}
                        onNodesChange={onNodesChange}
                        onEdgesChange={onEdgesChange}
                        onConnect={onConnect}
                        onPaneClick={onPaneClick}
                        onNodeClick={(event, node) => handleElementClick(event, node)}
                        onEdgeClick={(event, edge) => handleElementClick(event, edge)}
                        onContextMenu={handleContextMenu}
                        onNodeContextMenu={handleNodeContextMenu}
                        onEdgeContextMenu={handleEdgeContextMenu}
                        nodeTypes={nodeTypes}
                        edgeTypes={edgeTypes}
                        fitView
                        fitViewOptions={{ padding: 0.2, maxZoom: 0.9 }}
                        onInit={(instance) => {
                          reactFlowInstanceRef.current = instance;
                        }}
                      >
                        <Controls />
                        <MiniMap />
                        <Background />
                      </ReactFlow>

                      {selectedElement && mode === 'edit' && (
                        <EditPanel
                          key={`${selectedElement.type}-${selectedElement.id}`}
                          element={selectedElement}
                          sceneId={currentSceneId}
                          onClose={() => setSelectedElement(null)}
                          onNodeUpdate={handleNodeUpdate}
                          onEdgeUpdate={handleEdgeUpdate}
                        />
                      )}
                    </div>
                  ) : tab.type === 'function' ? (
                    // Function editor placeholder
                    <div className="flex items-center justify-center h-full text-muted-foreground">
                      <div className="text-center space-y-2">
                        <p className="text-lg font-medium">Function Editor</p>
                        <p className="text-sm">Coming soon…</p>
                      </div>
                    </div>
                  ) : tab.type === 'skill' ? (
                    // Skill editor placeholder
                    <div className="flex items-center justify-center h-full text-muted-foreground">
                      <div className="text-center space-y-2">
                        <p className="text-lg font-medium">Skill Editor</p>
                        <p className="text-sm">Coming soon…</p>
                      </div>
                    </div>
                  ) : null}
                </TabsContent>
              ))}
            </Tabs>
          ) : (
            // Empty state when no tabs are open
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              <div className="text-center space-y-2">
                <p className="text-lg font-medium">No Tab Open</p>
                <p className="text-sm">Select a scene, function, or skill from the sidebar to get started</p>
              </div>
            </div>
          )}

          {/* Preview Chat Panel */}
          {mode === 'preview' && (
            <div className="absolute top-0 right-0 h-full w-96 bg-background border-l border-border transition-all duration-300 ease-in-out overflow-hidden">
              <PreviewChatInterface agentId={agentId} />
            </div>
          )}

          {/* Context Menu */}
          <SceneContextMenu
            position={contextMenu}
            context={contextMenuContext}
            element={contextMenuElement || undefined}
            onAddSubscene={handleAddSubsceneFromMenu}
            onRemoveNode={handleRemoveNode}
            onRemoveEdge={handleRemoveEdge}
          />
        </div>

        {/* Submit Area */}
        {mode === 'edit' && (
          <SubmitArea
            hasUnsavedChanges={hasUnsavedChanges}
            isSubmitting={isSubmitting}
            onSubmit={handleSubmit}
            onDiscard={handleDiscard}
          />
        )}
      </SidebarInset>

      {/* Build Chat Draggable Dialog */}
      <DraggableDialog
        open={isBuildChatOpen}
        onOpenChange={setIsBuildChatOpen}
        title="Build Assistant"
      >
        <BuildChatInterface agentId={agentId} />
      </DraggableDialog>

      {/* ReAct Chat Draggable Dialog */}
      <DraggableDialog
        open={isReactChatOpen}
        onOpenChange={setIsReactChatOpen}
        title="ReAct Agent Chat"
      >
        <ReactChatInterface agentId={agentId} />
      </DraggableDialog>

      {/* Scene Modal */}
      <SceneModal
        isOpen={isCreateSceneModalOpen}
        mode="create"
        onClose={() => setIsCreateSceneModalOpen(false)}
        onSave={handleCreateScene}
      />

      {/* Subscene Modal */}
      <SubsceneModal
        isOpen={isAddSubsceneModalOpen}
        mode="add"
        sceneId={currentSceneId}
        onClose={() => setIsAddSubsceneModalOpen(false)}
        onSave={handleAddSubscene}
      />

      {/* Connection Modal */}
      <ConnectionModal
        isOpen={isAddConnectionModalOpen}
        mode="add"
        sceneId={currentSceneId}
        initialData={pendingConnection ? {
          from_subscene: pendingConnection.from,
          to_subscene: pendingConnection.to
        } : undefined}
        onClose={() => setIsAddConnectionModalOpen(false)}
        onSave={handleAddConnection}
      />
    </SidebarProvider>
  );
}

export default AgentDetail;
