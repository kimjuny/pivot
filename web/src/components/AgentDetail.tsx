import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { X, Layers, Wrench, Zap } from "@/lib/lucide";
import { useAgentWorkStore } from '../store/agentWorkStore';
import { useAgentTabStore } from '../store/agentTabStore';
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import DraggableDialog from './DraggableDialog';
import ReactChatInterface from '@/components/ReactChatInterface';
import EditPanel from './EditPanel';
import SceneModal from './SceneModal';
import SubsceneModal from './SubsceneModal';
import ConnectionModal from './ConnectionModal';
import SubsceneNode from './SubsceneNode';
import AgentDetailSidebar, {
  type SidebarChannel,
  type SidebarWebSearchBinding,
} from './AgentDetailSidebar';
import AgentWorkspaceToolbar from './AgentWorkspaceToolbar';
import PublishReleaseDrawer from './PublishReleaseDrawer';
import ReleaseHistoryDialog from './ReleaseHistoryDialog';
import SceneContextMenu, { ContextMenuContext } from './SceneContextMenu';
import ToolEditor from './ToolEditor';
import SkillEditor from './SkillEditor';
import {
  updateAgent,
  updateAgentScenes,
  getAgentDraftState,
  getPrivateToolSource,
  publishAgentRelease,
  saveAgentDraft,
  getSharedToolSource,
  upsertPrivateTool,
  getSharedSkillSource,
  getUserSkillSource,
  upsertUserSkill,
  type SkillSource,
  type AgentDraftState,
} from '../utils/api';
import { compareSceneGraphs, deepCopyAgent, deepCopySceneGraph } from '../utils/compare';
import { toast } from 'sonner';
import type { Agent, Scene, SceneGraph, SceneNode } from '../types';
import type { AgentTab } from '../store/agentTabStore';

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
}

interface ToolTabDescriptor {
  kind: 'private' | 'shared';
  source: 'builtin' | 'user';
  readOnly: boolean;
  toolName: string;
}

interface SkillTabDescriptor {
  kind: 'private' | 'shared';
  source: SkillSource;
  readOnly: boolean;
  skillName: string;
}

interface TabEditorState {
  source: string;
  isLoading: boolean;
  isSaving: boolean;
  isLoaded: boolean;
  error: string | null;
}

/**
 * Parse tool tab metadata/resourceId into a normalized descriptor.
 * Falls back to private/user editable for legacy tabs that only carry a name.
 */
function parseToolTabDescriptor(tab: AgentTab): ToolTabDescriptor {
  const rawResourceId = String(tab.resourceId);
  const separator = rawResourceId.indexOf(':');
  const parsedKind =
    separator > -1 ? rawResourceId.slice(0, separator) : undefined;
  const normalizedKind: 'private' | 'shared' =
    parsedKind === 'shared' ? 'shared' : 'private';
  const readOnly = tab.meta?.readOnly ?? normalizedKind === 'shared';
  const source: 'builtin' | 'user' =
    tab.meta?.source === 'builtin' || tab.meta?.source === 'user'
      ? tab.meta.source
      : normalizedKind === 'shared'
        ? 'builtin'
        : 'user';

  return {
    kind: tab.meta?.kind ?? normalizedKind,
    source,
    readOnly,
    toolName: tab.name,
  };
}

/**
 * Parse skill tab metadata/resourceId into a normalized descriptor.
 * Falls back to shared/builtin read-only for legacy tabs without metadata.
 * Current tabs should always pass explicit readOnly metadata from the API.
 */
function parseSkillTabDescriptor(tab: AgentTab): SkillTabDescriptor {
  const rawResourceId = String(tab.resourceId);
  const firstSeparator = rawResourceId.indexOf(':');
  const secondSeparator =
    firstSeparator > -1 ? rawResourceId.indexOf(':', firstSeparator + 1) : -1;
  const parsedKind =
    firstSeparator > -1 ? rawResourceId.slice(0, firstSeparator) : undefined;
  const parsedSource =
    secondSeparator > -1
      ? rawResourceId.slice(firstSeparator + 1, secondSeparator)
      : undefined;
  const normalizedKind: 'private' | 'shared' =
    parsedKind === 'private' ? 'private' : 'shared';
  const normalizedSource: SkillSource =
    parsedSource === 'manual' ||
    parsedSource === 'network' ||
    parsedSource === 'bundle' ||
    parsedSource === 'builtin'
      ? parsedSource
      : normalizedKind === 'private'
        ? 'manual'
        : 'builtin';
  const readOnly = tab.meta?.readOnly ?? normalizedSource === 'builtin';

  return {
    kind: tab.meta?.kind ?? normalizedKind,
    source:
      tab.meta?.source === 'manual' ||
      tab.meta?.source === 'network' ||
      tab.meta?.source === 'bundle' ||
      tab.meta?.source === 'builtin'
        ? tab.meta.source
        : normalizedSource,
    readOnly,
    skillName: tab.name,
  };
}

/**
 * Build a compact module-level summary for pending draft changes.
 * Why: hover cards should explain what is about to be saved or published
 * without overwhelming users with raw field-level diffs.
 */
function buildDraftChangeSummary(
  originalAgent: Agent | null,
  workspaceAgent: Agent | null
): string[] {
  if (!originalAgent || !workspaceAgent) {
    return [];
  }

  const changes: string[] = [];
  const basicsChanged =
    originalAgent.name !== workspaceAgent.name ||
    originalAgent.description !== workspaceAgent.description ||
    originalAgent.is_active !== workspaceAgent.is_active;
  const runtimeChanged =
    originalAgent.llm_id !== workspaceAgent.llm_id ||
    originalAgent.skill_resolution_llm_id !== workspaceAgent.skill_resolution_llm_id ||
    originalAgent.session_idle_timeout_minutes !==
      workspaceAgent.session_idle_timeout_minutes ||
    originalAgent.sandbox_timeout_seconds !==
      workspaceAgent.sandbox_timeout_seconds ||
    originalAgent.compact_threshold_percent !==
      workspaceAgent.compact_threshold_percent;
  const toolAccessChanged = originalAgent.tool_ids !== workspaceAgent.tool_ids;
  const skillAccessChanged = originalAgent.skill_ids !== workspaceAgent.skill_ids;

  if (basicsChanged) {
    changes.push('Agent basics updated');
  }
  if (runtimeChanged) {
    changes.push('Runtime settings updated');
  }
  if (toolAccessChanged) {
    changes.push('Tool access updated');
  }
  if (skillAccessChanged) {
    changes.push('Skill access updated');
  }

  const originalScenes = originalAgent.scenes ?? [];
  const workspaceScenes = workspaceAgent.scenes ?? [];
  const originalSceneNames = new Set(originalScenes.map((scene) => scene.name ?? ''));
  const workspaceSceneNames = new Set(workspaceScenes.map((scene) => scene.name ?? ''));
  const addedScenes = workspaceScenes.filter(
    (scene) => !originalSceneNames.has(scene.name ?? '')
  ).length;
  const removedScenes = originalScenes.filter(
    (scene) => !workspaceSceneNames.has(scene.name ?? '')
  ).length;
  let updatedScenes = 0;

  for (const scene of workspaceScenes) {
    const sceneName = scene.name ?? '';
    const originalScene = originalScenes.find((item) => (item.name ?? '') === sceneName);
    if (!originalScene) {
      continue;
    }
    if (compareSceneGraphs(originalScene, scene)) {
      updatedScenes += 1;
    }
  }

  if (addedScenes > 0) {
    changes.push(`${addedScenes} scene${addedScenes > 1 ? 's' : ''} added`);
  }
  if (removedScenes > 0) {
    changes.push(`${removedScenes} scene${removedScenes > 1 ? 's' : ''} removed`);
  }
  if (updatedScenes > 0) {
    changes.push(`${updatedScenes} scene${updatedScenes > 1 ? 's' : ''} updated`);
  }

  return changes;
}

function AgentDetail({ agent, scenes, selectedScene, agentId, onSceneSelect, onRefreshScenes }: AgentDetailProps) {
  const {
    originalAgent,
    workspaceAgent,
    currentSceneId,
    hasUnsavedChanges,
    isSubmitting,
    initialize,
    setWorkspaceAgent,
    updateSceneInWorkspace,
    setCurrentSceneId,
    discardChanges,
    markAsCommitted,
    setSubmitting,
    reset
  } = useAgentWorkStore();
  const { tabs, activeTabId, setActiveTab, closeTab, replaceTabResource } = useAgentTabStore();

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [isReactChatOpen, setIsReactChatOpen] = useState<boolean>(false);
  const [selectedElement, setSelectedElement] = useState<SelectedElement | null>(null);
  const [isCreateSceneModalOpen, setIsCreateSceneModalOpen] = useState<boolean>(false);
  const [isEditSceneModalOpen, setIsEditSceneModalOpen] = useState<boolean>(false);
  const [isAddSubsceneModalOpen, setIsAddSubsceneModalOpen] = useState<boolean>(false);
  const [isAddConnectionModalOpen, setIsAddConnectionModalOpen] = useState<boolean>(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [contextMenuContext, setContextMenuContext] = useState<ContextMenuContext>('pane');
  const [contextMenuElement, setContextMenuElement] = useState<{ id: string; data?: Record<string, unknown> } | null>(null);
  const [pendingConnection, setPendingConnection] = useState<{ from: string; to: string } | null>(null);
  const [newSubscenePosition, setNewSubscenePosition] = useState<{ x: number; y: number } | null>(null);
  const [toolEditors, setToolEditors] = useState<Record<string, TabEditorState>>({});
  const [skillEditors, setSkillEditors] = useState<Record<string, TabEditorState>>({});
  const [isPublishDrawerOpen, setIsPublishDrawerOpen] = useState(false);
  const [isReleaseHistoryOpen, setIsReleaseHistoryOpen] = useState(false);
  const [draftState, setDraftState] = useState<AgentDraftState | null>(null);
  const [isLoadingDraftState, setIsLoadingDraftState] = useState(false);
  const [isPublishingRelease, setIsPublishingRelease] = useState(false);
  const [releaseNote, setReleaseNote] = useState('');
  const reactFlowInstanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);

  const workingScenes = (workspaceAgent?.scenes || []) as unknown as Scene[];
  const workingSceneGraph = workspaceAgent?.scenes?.find(s => s.id === currentSceneId) || null;
  const saveSummary = useMemo(
    () => buildDraftChangeSummary(originalAgent, workspaceAgent),
    [originalAgent, workspaceAgent]
  );
  const publishSummary = useMemo(() => {
    const combined = [...(draftState?.publish_summary ?? []), ...saveSummary];
    return Array.from(new Set(combined));
  }, [draftState?.publish_summary, saveSummary]);
  const hasPersistedPublishableChanges = draftState?.has_publishable_changes ?? false;
  const hasPublishableChanges = hasUnsavedChanges || hasPersistedPublishableChanges;

  // Detect current theme for graph styling
  const [isDarkMode, setIsDarkMode] = useState(() =>
    document.documentElement.classList.contains('dark')
  );

  /**
   * Stage agent-level draft fields that should participate in Save / Publish.
   * Why: some sidebar modules are being migrated away from immediate persistence
   * so the top toolbar can represent one coherent draft workflow.
   */
  const handleAgentDraftUpdate = useCallback((nextAgent: Agent) => {
    const currentAgent = workspaceAgent ?? agent;
    if (!currentAgent) {
      return;
    }

    setWorkspaceAgent({
      ...currentAgent,
      ...nextAgent,
      scenes: workspaceAgent?.scenes ?? currentAgent.scenes,
    });
  }, [agent, setWorkspaceAgent, workspaceAgent]);

  /**
   * Reload persisted draft/release state from the backend baseline.
   * Why: publish audit must survive page reloads instead of depending on the
   * current browser session still remembering what changed.
   */
  const refreshDraftState = useCallback(async () => {
    setIsLoadingDraftState(true);
    try {
      const nextDraftState = await getAgentDraftState(agentId);
      setDraftState(nextDraftState);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to load draft state:', error);
      toast.error(`Failed to load draft state: ${error.message}`);
    } finally {
      setIsLoadingDraftState(false);
    }
  }, [agentId]);

  // Initialize store with agent data
  useEffect(() => {
    if (agent) {
      initialize(agent);
    }
  }, [agent, initialize]);

  useEffect(() => {
    setDraftState(null);
    setReleaseNote('');
    void refreshDraftState();
  }, [agentId, refreshDraftState]);

  // Sync selectedScene with store
  useEffect(() => {
    if (selectedScene) {
      setCurrentSceneId(selectedScene.id);
    }
  }, [selectedScene, setCurrentSceneId]);

  // Sync activeTabId with currentSceneId when a scene tab is activated
  useEffect(() => {
    if (activeTabId) {
      const activeTab = tabs.find(tab => tab.id === activeTabId);
      if (activeTab && activeTab.type === 'scene' && activeTab.resourceId !== currentSceneId) {
        setCurrentSceneId(activeTab.resourceId as number);
      }
    }
  }, [activeTabId, tabs, currentSceneId, setCurrentSceneId]);

  /**
   * Keep only editor states for currently open tabs.
   * Why: avoids stale memory when users close many tool/skill tabs.
   */
  useEffect(() => {
    const openTabIds = new Set(tabs.map((tab) => tab.id));
    setToolEditors((prev) => {
      const next = Object.fromEntries(
        Object.entries(prev).filter(([tabId]) => openTabIds.has(tabId))
      );
      return Object.keys(next).length === Object.keys(prev).length ? prev : next;
    });
    setSkillEditors((prev) => {
      const next = Object.fromEntries(
        Object.entries(prev).filter(([tabId]) => openTabIds.has(tabId))
      );
      return Object.keys(next).length === Object.keys(prev).length ? prev : next;
    });
  }, [tabs]);

  /**
   * Load tool source for any newly opened tool tab.
   */
  useEffect(() => {
    tabs
      .filter((tab) => tab.type === 'tool' || tab.type === 'function')
      .forEach((tab) => {
        const existing = toolEditors[tab.id];
        if (existing?.isLoaded || existing?.isLoading) {
          return;
        }

        const descriptor = parseToolTabDescriptor(tab);
        setToolEditors((prev) => ({
          ...prev,
          [tab.id]: {
            source: prev[tab.id]?.source ?? '',
            isLoading: true,
            isSaving: false,
            isLoaded: false,
            error: null,
          },
        }));

        void (async () => {
          try {
            const result =
              descriptor.kind === 'shared'
                ? await getSharedToolSource(descriptor.toolName)
                : await getPrivateToolSource(descriptor.toolName);
            setToolEditors((prev) => ({
              ...prev,
              [tab.id]: {
                source: result.source,
                isLoading: false,
                isSaving: false,
                isLoaded: true,
                error: null,
              },
            }));
          } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            setToolEditors((prev) => ({
              ...prev,
              [tab.id]: {
                source: prev[tab.id]?.source ?? '',
                isLoading: false,
                isSaving: false,
                isLoaded: true,
                error: error.message || `Failed to load tool "${descriptor.toolName}"`,
              },
            }));
          }
        })();
      });
  }, [tabs, toolEditors]);

  /**
   * Load skill source for any newly opened skill tab.
   */
  useEffect(() => {
    tabs
      .filter((tab) => tab.type === 'skill')
      .forEach((tab) => {
        const existing = skillEditors[tab.id];
        if (existing?.isLoaded || existing?.isLoading) {
          return;
        }

        const descriptor = parseSkillTabDescriptor(tab);
        setSkillEditors((prev) => ({
          ...prev,
          [tab.id]: {
            source: prev[tab.id]?.source ?? '',
            isLoading: true,
            isSaving: false,
            isLoaded: false,
            error: null,
          },
        }));

        void (async () => {
          try {
            const result =
              descriptor.kind === 'private'
                ? await getUserSkillSource('private', descriptor.skillName)
                : !descriptor.readOnly && descriptor.source !== 'builtin'
                  ? await getUserSkillSource('shared', descriptor.skillName)
                  : await getSharedSkillSource(descriptor.skillName);
            setSkillEditors((prev) => ({
              ...prev,
              [tab.id]: {
                source: result.source,
                isLoading: false,
                isSaving: false,
                isLoaded: true,
                error: null,
              },
            }));
          } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            setSkillEditors((prev) => ({
              ...prev,
              [tab.id]: {
                source: prev[tab.id]?.source ?? '',
                isLoading: false,
                isSaving: false,
                isLoaded: true,
                error: error.message || `Failed to load skill "${descriptor.skillName}"`,
              },
            }));
          }
        })();
      });
  }, [tabs, skillEditors]);

  /**
   * Save handler for tool tabs.
   * Only private tools can be updated; shared tools remain read-only.
   */
  const handleToolTabSave = useCallback(async (tab: AgentTab, source: string) => {
    const descriptor = parseToolTabDescriptor(tab);
    if (descriptor.readOnly || descriptor.kind !== 'private') {
      toast.error('Built-in shared tools are read-only');
      return;
    }

    setToolEditors((prev) => ({
      ...prev,
      [tab.id]: {
        source,
        isLoading: false,
        isSaving: true,
        isLoaded: true,
        error: null,
      },
    }));

    try {
      await upsertPrivateTool(descriptor.toolName, source);
      toast.success(`Tool "${descriptor.toolName}" saved`);
      setToolEditors((prev) => ({
        ...prev,
        [tab.id]: {
          source,
          isLoading: false,
          isSaving: false,
          isLoaded: true,
          error: null,
        },
      }));
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      toast.error(`Failed to save tool "${descriptor.toolName}"`);
      setToolEditors((prev) => ({
        ...prev,
        [tab.id]: {
          source,
          isLoading: false,
          isSaving: false,
          isLoaded: true,
          error: error.message || `Failed to save tool "${descriptor.toolName}"`,
        },
      }));
    }
  }, []);

  /**
   * Save handler for skill tabs.
   * Editable scopes match Skills page: private + user shared only.
   */
  const handleSkillTabSave = useCallback(async (tab: AgentTab, source: string) => {
    const descriptor = parseSkillTabDescriptor(tab);
    if (descriptor.readOnly) {
      toast.error('This skill is read-only');
      return;
    }

    const saveKind = descriptor.kind === 'private' ? 'private' : 'shared';
    setSkillEditors((prev) => ({
      ...prev,
      [tab.id]: {
        source,
        isLoading: false,
        isSaving: true,
        isLoaded: true,
        error: null,
      },
    }));

    try {
      await upsertUserSkill(saveKind, descriptor.skillName, source);
      toast.success(`Skill "${descriptor.skillName}" saved`);
      setSkillEditors((prev) => ({
        ...prev,
        [tab.id]: {
          source,
          isLoading: false,
          isSaving: false,
          isLoaded: true,
          error: null,
        },
      }));
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      toast.error(`Failed to save skill "${descriptor.skillName}"`);
      setSkillEditors((prev) => ({
        ...prev,
        [tab.id]: {
          source,
          isLoading: false,
          isSaving: false,
          isLoaded: true,
          error: error.message || `Failed to save skill "${descriptor.skillName}"`,
        },
      }));
    }
  }, []);

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
    if (!currentSceneId) {
      return;
    }
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
  };

  const handleNodeContextMenu = (event: React.MouseEvent, node: Node) => {
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({
      x: event.clientX,
      y: event.clientY
    });
    setContextMenuContext('node');
    setContextMenuElement({ id: node.id, data: node.data });
  };

  const handleEdgeContextMenu = (event: React.MouseEvent, edge: Edge) => {
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({
      x: event.clientX,
      y: event.clientY
    });
    setContextMenuContext('edge');
    setContextMenuElement({ id: edge.id, data: edge.data });
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

  const currentSceneGraphData = workingSceneGraph;

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

  const handleSubmit = useCallback(async (options?: { silent?: boolean }): Promise<boolean> => {
    if (!workspaceAgent || !workspaceAgent.scenes) {
      return false;
    }
    setSubmitting(true);

    try {
      await updateAgent(agentId, {
        name: workspaceAgent.name,
        description: workspaceAgent.description,
        llm_id: workspaceAgent.llm_id,
        skill_resolution_llm_id: workspaceAgent.skill_resolution_llm_id ?? null,
        session_idle_timeout_minutes: workspaceAgent.session_idle_timeout_minutes,
        sandbox_timeout_seconds: workspaceAgent.sandbox_timeout_seconds,
        compact_threshold_percent: workspaceAgent.compact_threshold_percent,
        is_active: workspaceAgent.is_active,
        tool_ids: workspaceAgent.tool_ids ?? null,
        skill_ids: workspaceAgent.skill_ids ?? null,
      });

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
      const nextDraftState = await saveAgentDraft(agentId);

      // Diff and update tabs for any scenes that had temporary IDs
      if (workspaceAgent.scenes) {
        workspaceAgent.scenes.forEach(scene => {
          if (scene.id && scene.id < 0) {
            const updatedScene = updatedScenes.find(s => s.name === scene.name);
            if (updatedScene) {
              replaceTabResource(scene.id, updatedScene.id, 'scene');
            }
          }
        });
      }

      // 2. Mark everything as committed (update Original to match Workspace)
      // Ideally we should update originalAgent with the response from server (updatedScenes).
      // But updateAgentScenes only returns Scene[] (with updated IDs).
      // We might need to fetch full agent again to be perfectly safe, or just merge IDs.
      // For now, let's fetch full agent to be safe.

      // Notify parent to refresh
      await onRefreshScenes(); // This now fetches full agent in App.tsx

      setDraftState(nextDraftState);
      markAsCommitted();
      if (!options?.silent) {
        toast.success('Draft saved');
      }
      return true;

    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to submit changes:', error);
      toast.error(`Failed to save draft: ${error.message}`);
      return false;
    } finally {
      setSubmitting(false);
    }
  }, [agentId, markAsCommitted, onRefreshScenes, replaceTabResource, setSubmitting, workspaceAgent]);

  const handleDiscard = () => {
    discardChanges();
  };

  const handleOpenTest = () => {
    setIsReactChatOpen(true);
  };

  const handleOpenPublish = () => {
    setIsPublishDrawerOpen(true);
  };

  const handleOpenReleaseHistory = () => {
    setIsReleaseHistoryOpen(true);
  };

  const handlePublishRelease = useCallback(async () => {
    setIsPublishingRelease(true);
    try {
      if (hasUnsavedChanges) {
        const didSave = await handleSubmit({ silent: true });
        if (!didSave) {
          return;
        }
      }
      const nextDraftState = await publishAgentRelease(agentId, releaseNote);
      setDraftState(nextDraftState);
      await onRefreshScenes();
      setIsPublishDrawerOpen(false);
      setReleaseNote('');
      toast.success('Release published');
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to publish release:', error);
      toast.error(`Failed to publish release: ${error.message}`);
    } finally {
      setIsPublishingRelease(false);
    }
  }, [agentId, handleSubmit, hasUnsavedChanges, onRefreshScenes, releaseNote]);

  const handleChannelBindingsLoaded = useCallback((_bindings: SidebarChannel[]) => {
    void refreshDraftState();
  }, [refreshDraftState]);

  const handleWebSearchBindingsLoaded = useCallback((_bindings: SidebarWebSearchBinding[]) => {
    void refreshDraftState();
  }, [refreshDraftState]);

  return (
    <SidebarProvider defaultOpen={true}>
      <AgentDetailSidebar
        agent={workspaceAgent ?? agent}
        scenes={workingScenes}
        selectedScene={selectedScene}
        onSceneSelect={onSceneSelect}
        onCreateScene={handleCreateSceneModalOpen}
        onDeleteScene={handleDeleteScene}
        onAgentDraftUpdate={handleAgentDraftUpdate}
        onChannelBindingsLoaded={handleChannelBindingsLoaded}
        onWebSearchBindingsLoaded={handleWebSearchBindingsLoaded}
      />

      <SidebarInset className="flex flex-col bg-background overflow-hidden">
        {/* Main Content Area */}
        <div className="flex-1 relative overflow-hidden flex flex-col">
          <div className="pointer-events-none absolute right-4 top-3 z-20 flex justify-end">
            <AgentWorkspaceToolbar
              hasUnsavedChanges={hasUnsavedChanges}
              hasPublishableChanges={hasPublishableChanges}
              isSavingDraft={isSubmitting}
              saveSummary={saveSummary}
              publishSummary={publishSummary}
              onSaveDraft={() => void handleSubmit()}
              onDiscardChanges={handleDiscard}
              onOpenTest={handleOpenTest}
              onOpenPublish={handleOpenPublish}
              onOpenReleaseHistory={handleOpenReleaseHistory}
            />
          </div>

          {/* Tabs System */}
          {tabs.length > 0 ? (
            <Tabs
              value={activeTabId || undefined}
              onValueChange={setActiveTab}
              className="flex-1 flex flex-col overflow-hidden"
            >
              {/* Tabs List */}
              <div className="bg-muted border-b border-border px-2 pr-72 pt-1.5 lg:pr-[27rem]">
                <TabsList className="h-auto bg-transparent p-0 gap-1 w-full justify-start items-end -mb-px">
                  {tabs.map((tab) => {
                    // Get icon based on tab type (matching sidebar icons)
                    const TabIcon = tab.type === 'scene' ? Layers
                      : tab.type === 'tool' || tab.type === 'function' ? Wrench
                        : Zap;

                    return (
                      <div key={tab.id} className="relative group">
                        <TabsTrigger
                          value={tab.id}
                          className="
                            relative 
                            rounded-t-md rounded-b-none 
                            border-t border-x border-transparent 
                            px-3 py-2 pr-7 
                            text-xs font-medium 
                            text-muted-foreground
                            transition-all 
                            hover:text-foreground hover:bg-background/40
                            data-[state=active]:bg-background 
                            data-[state=active]:text-foreground 
                            data-[state=active]:border-border 
                            data-[state=active]:shadow-none
                            data-[state=active]:z-10
                            data-[state=active]:font-semibold
                          "
                        >
                          <TabIcon className="size-3.5 mr-2 shrink-0 opacity-70 group-hover:opacity-100 data-[state=active]:opacity-100" />
                          <span className="truncate max-w-[120px]">{tab.name}</span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              closeTab(tab.id);
                            }}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded-sm hover:bg-muted text-muted-foreground hover:text-foreground transition-all opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                            aria-label={`Close ${tab.name} tab`}
                          >
                            <X className="size-3" />
                          </button>
                        </TabsTrigger>
                      </div>
                    );
                  })}
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
                    <div className="absolute inset-0">
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

                      {selectedElement && (
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
                  ) : tab.type === 'tool' || tab.type === 'function' ? (
                    // Tool Monaco editor
                    <div className="relative h-full">
                      <div className="h-full">
                        {(() => {
                          const state = toolEditors[tab.id];
                          const descriptor = parseToolTabDescriptor(tab);
                          if (!state || state.isLoading) {
                            return (
                              <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                                Loading tool source…
                              </div>
                            );
                          }
                          if (state.error) {
                            return (
                              <div className="flex items-center justify-center h-full px-6">
                                <div className="text-center space-y-2">
                                  <p className="text-sm text-destructive">{state.error}</p>
                                </div>
                              </div>
                            );
                          }
                          return (
                            <ToolEditor
                              value={state.source}
                              onChange={(nextSource) => {
                                setToolEditors((prev) => ({
                                  ...prev,
                                  [tab.id]: {
                                    ...(prev[tab.id] ?? {
                                      source: '',
                                      isLoading: false,
                                      isSaving: false,
                                      isLoaded: true,
                                      error: null,
                                    }),
                                    source: nextSource,
                                  },
                                }));
                              }}
                              onSave={descriptor.readOnly ? undefined : (nextSource) => void handleToolTabSave(tab, nextSource)}
                              isSaving={state.isSaving}
                              readOnly={descriptor.readOnly}
                            />
                          );
                        })()}
                      </div>
                    </div>
                  ) : tab.type === 'skill' ? (
                    // Skill Monaco editor
                    <div className="relative h-full">
                      <div className="h-full">
                        {(() => {
                          const state = skillEditors[tab.id];
                          const descriptor = parseSkillTabDescriptor(tab);
                          if (!state || state.isLoading) {
                            return (
                              <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                                Loading skill source…
                              </div>
                            );
                          }
                          if (state.error) {
                            return (
                              <div className="flex items-center justify-center h-full px-6">
                                <div className="text-center space-y-2">
                                  <p className="text-sm text-destructive">{state.error}</p>
                                </div>
                              </div>
                            );
                          }
                          return (
                            <SkillEditor
                              value={state.source}
                              onChange={(nextSource) => {
                                setSkillEditors((prev) => ({
                                  ...prev,
                                  [tab.id]: {
                                    ...(prev[tab.id] ?? {
                                      source: '',
                                      isLoading: false,
                                      isSaving: false,
                                      isLoaded: true,
                                      error: null,
                                    }),
                                    source: nextSource,
                                  },
                                }));
                              }}
                              onSave={descriptor.readOnly ? undefined : (nextSource) => void handleSkillTabSave(tab, nextSource)}
                              isSaving={state.isSaving}
                              readOnly={descriptor.readOnly}
                            />
                          );
                        })()}
                      </div>
                    </div>
                  ) : null}
                </TabsContent>
              ))}
            </Tabs>
          ) : (
            // Empty state when no tabs are open
            <div className="flex-1 relative flex items-center justify-center text-muted-foreground">
              <div className="text-center space-y-2">
                <p className="text-lg font-medium">No Tab Open</p>
                <p className="text-sm">Select a scene, tool, or skill from the sidebar to get started</p>
              </div>
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
      </SidebarInset>

      {/* ReAct Chat Draggable Dialog */}
      <DraggableDialog
        open={isReactChatOpen}
        onOpenChange={setIsReactChatOpen}
        title={agent?.name?.trim() || 'ReAct Agent Chat'}
        size="large"
        fullscreenable
      >
        <ReactChatInterface
          agentId={agentId}
          agentName={agent?.name}
          agentToolIds={agent?.tool_ids}
          primaryLlmId={agent?.llm_id}
          sessionIdleTimeoutMinutes={agent?.session_idle_timeout_minutes}
        />
      </DraggableDialog>

      <PublishReleaseDrawer
        open={isPublishDrawerOpen}
        onOpenChange={setIsPublishDrawerOpen}
        hasUnsavedChanges={hasUnsavedChanges}
        changeSummary={publishSummary}
        latestRelease={draftState?.latest_release ?? null}
        releaseNote={releaseNote}
        onReleaseNoteChange={setReleaseNote}
        isPublishing={isPublishingRelease}
        canPublish={hasPublishableChanges}
        onPublish={handlePublishRelease}
      />
      <ReleaseHistoryDialog
        open={isReleaseHistoryOpen}
        onOpenChange={setIsReleaseHistoryOpen}
        releaseHistory={draftState?.release_history ?? []}
      />

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
