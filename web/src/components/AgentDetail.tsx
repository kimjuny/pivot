import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { X, Wrench, Zap } from "@/lib/lucide";
import { useAgentWorkStore } from '../store/agentWorkStore';
import { useAgentTabStore } from '../store/agentTabStore';
import { SidebarProvider, SidebarInset } from '@/components/ui/sidebar';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import DraggableDialog from './DraggableDialog';
import ReactChatInterface from '@/components/ReactChatInterface';
import AgentDetailSidebar, {
  type SidebarChannel,
  type SidebarImageProviderBinding,
  type SidebarWebSearchBinding,
} from './AgentDetailSidebar';
import AgentWorkspaceToolbar from './AgentWorkspaceToolbar';
import PublishReleaseDrawer from './PublishReleaseDrawer';
import ReleaseHistoryDialog from './ReleaseHistoryDialog';
import ToolEditor from './ToolEditor';
import SkillEditor from './SkillEditor';
import {
  updateAgent,
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
import {
  buildStudioTestSnapshotPayload,
  computeStudioTestWorkspaceHash,
  type StudioTestSnapshotPayload,
} from '@/utils/agentTestSnapshot';
import { deepCopyAgent } from '../utils/compare';
import { toast } from 'sonner';
import type { Agent } from '../types';
import type { AgentTab } from '../store/agentTabStore';

interface AgentDetailProps {
  agent: Agent | null;
  agentId: number;
  onRefreshAgent: () => Promise<Agent | null>;
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
 * Falls back to shared/manual read-only for legacy tabs without metadata.
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
    parsedSource === 'agent'
      ? parsedSource
      : 'manual';
  const readOnly = tab.meta?.readOnly ?? normalizedKind === 'shared';

  return {
    kind: tab.meta?.kind ?? normalizedKind,
    source:
      tab.meta?.source === 'manual' ||
      tab.meta?.source === 'network' ||
      tab.meta?.source === 'bundle' ||
      tab.meta?.source === 'agent'
        ? tab.meta.source
        : normalizedSource,
    readOnly,
    skillName: tab.name,
  };
}

/**
 * Build a compact module-level summary for pending draft changes.
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
    originalAgent.session_idle_timeout_minutes !==
      workspaceAgent.session_idle_timeout_minutes ||
    originalAgent.sandbox_timeout_seconds !==
      workspaceAgent.sandbox_timeout_seconds ||
    originalAgent.compact_threshold_percent !==
      workspaceAgent.compact_threshold_percent ||
    originalAgent.max_iteration !== workspaceAgent.max_iteration;
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

  return changes;
}

function AgentDetail({ agent, agentId, onRefreshAgent }: AgentDetailProps) {
  const {
    originalAgent,
    workspaceAgent,
    hasUnsavedChanges,
    isSubmitting,
    initialize,
    setWorkspaceAgent,
    discardChanges,
    markAsCommitted,
    setSubmitting,
  } = useAgentWorkStore();
  const { tabs, activeTabId, setActiveTab, closeTab } = useAgentTabStore();

  const [isReactChatOpen, setIsReactChatOpen] = useState<boolean>(false);
  const [toolEditors, setToolEditors] = useState<Record<string, TabEditorState>>({});
  const [skillEditors, setSkillEditors] = useState<Record<string, TabEditorState>>({});
  const [isPublishDrawerOpen, setIsPublishDrawerOpen] = useState(false);
  const [isReleaseHistoryOpen, setIsReleaseHistoryOpen] = useState(false);
  const [draftState, setDraftState] = useState<AgentDraftState | null>(null);
  const [isLoadingDraftState, setIsLoadingDraftState] = useState(false);
  const [isPublishingRelease, setIsPublishingRelease] = useState(false);
  const [releaseNote, setReleaseNote] = useState('');
  const [studioTestSnapshotHash, setStudioTestSnapshotHash] = useState<string | null>(null);

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
  const effectiveAgent = workspaceAgent ?? agent;
  const activeReleaseRecord = useMemo(() => {
    const activeReleaseId = effectiveAgent?.active_release_id ?? null;
    if (activeReleaseId == null) {
      return null;
    }

    return (
      draftState?.release_history.find((release) => release.id === activeReleaseId) ??
      (draftState?.latest_release?.id === activeReleaseId
        ? draftState.latest_release
        : null)
    );
  }, [draftState?.latest_release, draftState?.release_history, effectiveAgent?.active_release_id]);
  const activeReleaseVersion = activeReleaseRecord?.version ?? null;
  const studioTestSnapshot = useMemo<StudioTestSnapshotPayload | null>(() => {
    if (!effectiveAgent) {
      return null;
    }

    return buildStudioTestSnapshotPayload(effectiveAgent);
  }, [effectiveAgent]);

  /**
   * Stage agent-level draft fields that should participate in Save / Publish.
   */
  const handleAgentDraftUpdate = useCallback((nextAgent: Agent) => {
    const currentAgent = workspaceAgent ?? agent;
    if (!currentAgent) {
      return;
    }

    setWorkspaceAgent({
      ...currentAgent,
      ...nextAgent,
    });
  }, [agent, setWorkspaceAgent, workspaceAgent]);

  /**
   * Reload persisted draft/release state from the backend baseline.
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

  useEffect(() => {
    let isCancelled = false;

    if (!studioTestSnapshot) {
      setStudioTestSnapshotHash(null);
      return () => {
        isCancelled = true;
      };
    }

    void computeStudioTestWorkspaceHash(studioTestSnapshot)
      .then((nextHash) => {
        if (!isCancelled) {
          setStudioTestSnapshotHash(nextHash);
        }
      })
      .catch((hashError) => {
        console.error('Failed to compute Studio test snapshot hash:', hashError);
        if (!isCancelled) {
          setStudioTestSnapshotHash(null);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [studioTestSnapshot]);

  /**
   * Keep only editor states for currently open tabs.
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
                : !descriptor.readOnly
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

  const handleSubmit = useCallback(async (options?: { silent?: boolean }): Promise<boolean> => {
    if (!workspaceAgent) {
      return false;
    }
    setSubmitting(true);

    try {
      await updateAgent(agentId, {
        name: workspaceAgent.name,
        description: workspaceAgent.description,
        llm_id: workspaceAgent.llm_id,
        session_idle_timeout_minutes: workspaceAgent.session_idle_timeout_minutes,
        sandbox_timeout_seconds: workspaceAgent.sandbox_timeout_seconds,
        compact_threshold_percent: workspaceAgent.compact_threshold_percent,
        max_iteration: workspaceAgent.max_iteration,
        is_active: workspaceAgent.is_active,
        tool_ids: workspaceAgent.tool_ids ?? null,
        skill_ids: workspaceAgent.skill_ids ?? null,
      });

      const nextDraftState = await saveAgentDraft(agentId);
      const refreshedAgent = await onRefreshAgent();

      setDraftState(nextDraftState);
      markAsCommitted(refreshedAgent ?? workspaceAgent);
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
  }, [agentId, markAsCommitted, onRefreshAgent, setSubmitting, workspaceAgent]);

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
      const refreshedAgent = await onRefreshAgent();
      if (refreshedAgent) {
        markAsCommitted(refreshedAgent);
      }
      setIsPublishDrawerOpen(false);
      setReleaseNote('');
      toast.success('Release published and activated for new sessions');
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to publish release:', error);
      toast.error(`Failed to publish release: ${error.message}`);
    } finally {
      setIsPublishingRelease(false);
    }
  }, [agentId, handleSubmit, hasUnsavedChanges, markAsCommitted, onRefreshAgent, releaseNote]);

  const handleChannelBindingsLoaded = useCallback((_bindings: SidebarChannel[]) => {
    void refreshDraftState();
  }, [refreshDraftState]);

  const handleWebSearchBindingsLoaded = useCallback((_bindings: SidebarWebSearchBinding[]) => {
    void refreshDraftState();
  }, [refreshDraftState]);

  const handleImageProviderBindingsLoaded = useCallback((_bindings: SidebarImageProviderBinding[]) => {
    void refreshDraftState();
  }, [refreshDraftState]);

  /**
   * Persist sidebar-managed binding changes into the saved draft baseline.
   */
  const handlePersistedBindingDraftChanged = useCallback(async () => {
    try {
      await saveAgentDraft(agentId);
      await refreshDraftState();
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to refresh saved draft after binding change:', error);
      toast.error(`Failed to refresh saved draft: ${error.message}`);
    }
  }, [agentId, refreshDraftState]);

  return (
    <SidebarProvider defaultOpen={true}>
      <AgentDetailSidebar
        agent={workspaceAgent ?? agent}
        onAgentDraftUpdate={handleAgentDraftUpdate}
        onChannelBindingsLoaded={handleChannelBindingsLoaded}
        onImageProviderBindingsLoaded={handleImageProviderBindingsLoaded}
        onWebSearchBindingsLoaded={handleWebSearchBindingsLoaded}
        onExtensionBindingsChanged={handlePersistedBindingDraftChanged}
        onChannelBindingsChanged={handlePersistedBindingDraftChanged}
        onImageProviderBindingsChanged={handlePersistedBindingDraftChanged}
        onWebSearchBindingsChanged={handlePersistedBindingDraftChanged}
      />

      <SidebarInset className="flex flex-col bg-background overflow-hidden">
        <div className="flex-1 relative overflow-hidden flex flex-col">
          <div className="pointer-events-none absolute right-4 top-3 z-20 flex justify-end">
            <AgentWorkspaceToolbar
              activeReleaseVersion={activeReleaseVersion}
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

          {tabs.length > 0 ? (
            <Tabs
              value={activeTabId || undefined}
              onValueChange={setActiveTab}
              className="flex-1 flex flex-col overflow-hidden"
            >
              <div className="bg-muted border-b border-border px-2 pr-72 pt-1.5 lg:pr-[27rem]">
                <TabsList className="h-auto bg-transparent p-0 gap-1 w-full justify-start items-end -mb-px">
                  {tabs.map((tab) => {
                    const TabIcon = tab.type === 'tool' || tab.type === 'function'
                      ? Wrench
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

              {tabs.map((tab) => (
                <TabsContent
                  key={tab.id}
                  value={tab.id}
                  className="flex-1 m-0 relative overflow-hidden data-[state=inactive]:hidden"
                >
                  {tab.type === 'tool' || tab.type === 'function' ? (
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
            <div className="flex-1 relative flex items-center justify-center text-muted-foreground">
              <div className="text-center space-y-2">
                <p className="text-lg font-medium">No Tab Open</p>
                <p className="text-sm">Select a tool or skill from the sidebar to get started</p>
              </div>
            </div>
          )}
        </div>
      </SidebarInset>

      <DraggableDialog
        open={isReactChatOpen}
        onOpenChange={setIsReactChatOpen}
        title={agent?.name?.trim() || 'ReAct Agent Chat'}
        size="large"
        fullscreenable
      >
        <ReactChatInterface
          agentId={agentId}
          sessionType="studio_test"
          testSnapshot={studioTestSnapshot}
          testSnapshotHash={studioTestSnapshotHash}
          agentName={effectiveAgent?.name}
          agentToolIds={effectiveAgent?.tool_ids}
          primaryLlmId={effectiveAgent?.llm_id}
          sessionIdleTimeoutMinutes={effectiveAgent?.session_idle_timeout_minutes}
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
        activeReleaseId={effectiveAgent?.active_release_id ?? null}
      />
    </SidebarProvider>
  );
}

export default AgentDetail;
