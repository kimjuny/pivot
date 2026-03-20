import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
    Bot,
    ChevronDown,
    Layers,
    Wrench,
    Zap,
    Radio,
    Plus,
    X,
    MessageSquare,
    Settings2,
    PanelLeft,
    Globe,
} from 'lucide-react';
import { useSidebar } from '@/hooks/use-sidebar';
import {
    Sidebar,
    SidebarContent,
    SidebarFooter,
    SidebarGroup,
    SidebarGroupContent,
    SidebarGroupLabel,
    SidebarHeader,
    SidebarMenu,
    SidebarMenuButton,
    SidebarMenuItem,
    SidebarMenuAction,
    SidebarSeparator,
    SidebarRail,
} from '@/components/ui/sidebar';
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@/components/ui/tooltip';
import { Button } from '@/components/ui/button';
import AgentModal, { AgentFormData } from './AgentModal';
import ToolSelectorDialog from './ToolSelectorDialog';
import SkillSelectorDialog from './SkillSelectorDialog';
import ChannelBindingDialog from './ChannelBindingDialog';
import WebSearchBindingDialog from './WebSearchBindingDialog';
import { LLMBrandAvatar } from './LLMBrandAvatar';
import type { Agent, Scene } from '../types';
import {
    updateAgent,
    getSharedTools,
    getPrivateTools,
    getSharedSkills,
    getPrivateSkills,
    getChannels,
    getAgentChannels,
    deleteAgentChannel,
    getWebSearchProviders,
    getAgentWebSearchBindings,
    deleteAgentWebSearchBinding,
    type SharedTool,
    type PrivateTool,
    type SharedSkill,
    type UserSkill,
    type ChannelBinding,
    type ChannelCatalogItem,
    type WebSearchBinding,
    type WebSearchCatalogItem,
} from '../utils/api';
import { toast } from 'sonner';
import { useAgentTabStore } from '../store/agentTabStore';

/** Unified tool entry for sidebar display. */
interface SidebarTool {
    name: string;
    description: string;
    kind: 'shared' | 'private';
    source: 'builtin' | 'user';
    readOnly: boolean;
}

/** Unified skill entry for sidebar display. */
interface SidebarSkill {
    name: string;
    description: string;
    kind: 'shared' | 'private';
    source: 'builtin' | 'user';
    creator: string | null;
    readOnly: boolean;
}

/** Unified channel binding row for sidebar display. */
interface SidebarChannel {
    id: number;
    name: string;
    channelKey: string;
    providerName: string;
    enabled: boolean;
    transportMode: 'webhook' | 'websocket' | 'polling';
    lastHealthStatus: string | null;
}

/** Unified web-search binding row for sidebar display. */
interface SidebarWebSearchBinding {
    id: number;
    providerKey: string;
    providerName: string;
    enabled: boolean;
    lastHealthStatus: string | null;
}

/**
 * Render a compact status label for channel health.
 * Why: users need to distinguish "configured but untested" from "ready" at a glance.
 */
function formatChannelStatus(status: string | null): string {
    if (!status) {
        return 'untested';
    }
    return status;
}

/**
 * Build a unique resource ID for tool tabs.
 * Why: shared/private tools can have the same name, so name alone collides.
 */
function buildToolResourceId(tool: SidebarTool): string {
    return `${tool.kind}:${tool.name}`;
}

/**
 * Build a unique resource ID for skill tabs.
 * Why: shared(user)/shared(builtin)/private may share names.
 */
function buildSkillResourceId(skill: SidebarSkill): string {
    return `${skill.kind}:${skill.source}:${skill.name}`;
}

/**
 * Parses the serialized tool allowlist from agent.tool_ids.
 *
 * Returns:
 * - null: unrestricted (all tools allowed)
 * - Set<string>: explicit enabled tool names
 */
function parseToolIds(toolIds: string | null | undefined): Set<string> | null {
    if (toolIds === null || toolIds === undefined) {
        return null;
    }

    try {
        const parsed = JSON.parse(toolIds) as unknown;
        if (!Array.isArray(parsed)) {
            return new Set<string>();
        }
        return new Set(
            parsed
                .filter((item): item is string => typeof item === 'string')
                .map((name) => name.trim())
                .filter((name) => name.length > 0)
        );
    } catch {
        return new Set<string>();
    }
}

/**
 * Parses the serialized skill allowlist from agent.skill_ids.
 *
 * Returns:
 * - null: unrestricted (all skills allowed)
 * - Set<string>: explicit enabled skill names
 */
function parseSkillIds(skillIds: string | null | undefined): Set<string> | null {
    if (skillIds === null || skillIds === undefined) {
        return null;
    }

    try {
        const parsed = JSON.parse(skillIds) as unknown;
        if (!Array.isArray(parsed)) {
            return new Set<string>();
        }
        return new Set(
            parsed
                .filter((item): item is string => typeof item === 'string')
                .map((name) => name.trim())
                .filter((name) => name.length > 0)
        );
    } catch {
        return new Set<string>();
    }
}

interface AgentDetailSidebarProps {
    agent: Agent | null;
    scenes: Scene[];
    selectedScene: Scene | null;
    onSceneSelect: (scene: Scene) => void;
    onCreateScene: () => void;
    onDeleteScene: (scene: Scene) => void;
    onOpenReactChat: () => void;
    onAgentUpdate?: (agent: Agent) => void;
}

/**
 * Sidebar for agent detail page.
 * Shows agent info, scenes list, tools, and skills.
 * Uses shadcn sidebar components for consistent styling.
 */
function AgentDetailSidebar({
    agent,
    scenes,
    selectedScene,
    onSceneSelect,
    onCreateScene,
    onDeleteScene,
    onOpenReactChat,
    onAgentUpdate,
}: AgentDetailSidebarProps) {
    const { state, setOpen } = useSidebar();
    const [isScenesOpen, setIsScenesOpen] = useState(true);
    const [isToolsOpen, setIsToolsOpen] = useState(false);
    const [isSkillsOpen, setIsSkillsOpen] = useState(false);
    const [isChannelsOpen, setIsChannelsOpen] = useState(false);
    const [isWebSearchOpen, setIsWebSearchOpen] = useState(false);
    const [isEditModalOpen, setIsEditModalOpen] = useState(false);
    const [isToolSelectorOpen, setIsToolSelectorOpen] = useState(false);
    const [isSkillSelectorOpen, setIsSkillSelectorOpen] = useState(false);
    const [isChannelDialogOpen, setIsChannelDialogOpen] = useState(false);
    const [isWebSearchDialogOpen, setIsWebSearchDialogOpen] = useState(false);
    const [editingChannel, setEditingChannel] = useState<ChannelBinding | null>(null);
    const [editingWebSearchBinding, setEditingWebSearchBinding] = useState<WebSearchBinding | null>(null);
    const [tools, setTools] = useState<SidebarTool[]>([]);
    const [skills, setSkills] = useState<SidebarSkill[]>([]);
    const [channels, setChannels] = useState<SidebarChannel[]>([]);
    const [webSearchBindings, setWebSearchBindings] = useState<SidebarWebSearchBinding[]>([]);
    const [channelCatalog, setChannelCatalog] = useState<ChannelCatalogItem[]>([]);
    const [webSearchCatalog, setWebSearchCatalog] = useState<WebSearchCatalogItem[]>([]);
    const [toolsLoading, setToolsLoading] = useState(false);
    const [skillsLoading, setSkillsLoading] = useState(false);
    const [channelsLoading, setChannelsLoading] = useState(false);
    const [webSearchLoading, setWebSearchLoading] = useState(false);
    // Local copy of the agent's tool_ids so it updates without a page reload
    const [localToolIds, setLocalToolIds] = useState<string | null | undefined>(agent?.tool_ids);
    // Local copy of the agent's skill_ids so it updates without a page reload
    const [localSkillIds, setLocalSkillIds] = useState<string | null | undefined>(agent?.skill_ids);
    const hasFetchedToolsRef = useRef(false);
    const hasFetchedSkillsRef = useRef(false);
    const hasFetchedChannelsCatalogRef = useRef(false);
    const hasFetchedWebSearchCatalogRef = useRef(false);
    const { openTab, activeTabId } = useAgentTabStore();

    // Sync localToolIds when the agent prop changes
    useEffect(() => {
        setLocalToolIds(agent?.tool_ids);
    }, [agent?.tool_ids]);

    // Sync localSkillIds when the agent prop changes
    useEffect(() => {
        setLocalSkillIds(agent?.skill_ids);
    }, [agent?.skill_ids]);

    /**
     * Sidebar should display tools that are currently configured for this agent,
     * instead of the global tool catalog, to avoid configuration mismatch.
     */
    const enabledToolNameSet = useMemo(
        () => parseToolIds(localToolIds),
        [localToolIds]
    );
    const enabledSkillNameSet = useMemo(
        () => parseSkillIds(localSkillIds),
        [localSkillIds]
    );

    const displayedTools = useMemo(() => {
        if (enabledToolNameSet === null) {
            return tools;
        }
        return tools.filter((tool) => enabledToolNameSet.has(tool.name));
    }, [tools, enabledToolNameSet]);

    const enabledCount = useMemo(() => {
        if (enabledToolNameSet === null) {
            return tools.length;
        }
        return displayedTools.length;
    }, [tools.length, displayedTools.length, enabledToolNameSet]);

    /**
     * Sidebar should display skills that are currently configured for this
     * agent, instead of the global skill catalog.
     */
    const displayedSkills = useMemo(() => {
        if (enabledSkillNameSet === null) {
            return skills;
        }
        return skills.filter((skill) => enabledSkillNameSet.has(skill.name));
    }, [skills, enabledSkillNameSet]);

    const enabledSkillCount = useMemo(() => {
        if (enabledSkillNameSet === null) {
            return skills.length;
        }
        return displayedSkills.length;
    }, [skills.length, displayedSkills.length, enabledSkillNameSet]);

    /**
     * Fetch both shared (built-in) and private (user-workspace) tools in parallel.
     * Merges them into a unified list for display.
     * Uses useRef to prevent duplicate fetches in React Strict Mode.
     */
    useEffect(() => {
        if (hasFetchedToolsRef.current) return;

        const fetchTools = async () => {
            hasFetchedToolsRef.current = true;
            setToolsLoading(true);
            try {
                const [shared, priv] = await Promise.all([
                    getSharedTools(),
                    getPrivateTools(),
                ]);
                const merged: SidebarTool[] = [
                    ...shared.map((t: SharedTool) => ({
                        name: t.name,
                        description: t.description,
                        kind: 'shared' as const,
                        source: 'builtin' as const,
                        readOnly: true,
                    })),
                    ...priv.map((t: PrivateTool) => ({
                        name: t.name,
                        description: '',
                        kind: 'private' as const,
                        source: 'user' as const,
                        readOnly: false,
                    })),
                ];
                setTools(merged);
            } catch (err) {
                const error = err instanceof Error ? err : new Error(String(err));
                console.error('Failed to fetch tools:', error);
                toast.error('Failed to load tools');
            } finally {
                setToolsLoading(false);
            }
        };

        void fetchTools();
    }, []);

    /**
     * Fetch both shared (builtin + user shared) and private user skills.
     */
    useEffect(() => {
        if (hasFetchedSkillsRef.current) return;

        const fetchSkills = async () => {
            hasFetchedSkillsRef.current = true;
            setSkillsLoading(true);
            try {
                const [shared, priv] = await Promise.all([
                    getSharedSkills(),
                    getPrivateSkills(),
                ]);
                const merged: SidebarSkill[] = [
                    ...shared.map((s: SharedSkill) => ({
                        name: s.name,
                        description: s.description,
                        kind: 'shared' as const,
                        source: s.source,
                        creator: s.creator,
                        readOnly: s.read_only,
                    })),
                    ...priv.map((s: UserSkill) => ({
                        name: s.name,
                        description: s.description,
                        kind: 'private' as const,
                        source: 'user' as const,
                        creator: s.creator,
                        readOnly: s.read_only,
                    })),
                ];
                setSkills(merged);
            } catch (err) {
                const error = err instanceof Error ? err : new Error(String(err));
                console.error('Failed to fetch skills:', error);
                toast.error('Failed to load skills');
            } finally {
                setSkillsLoading(false);
            }
        };

        void fetchSkills();
    }, []);

    /**
     * Load the built-in channel catalog once because the binding dialog reuses it
     * for schema-driven provider forms.
     */
    useEffect(() => {
        if (hasFetchedChannelsCatalogRef.current) return;

        const fetchChannelCatalog = async () => {
            hasFetchedChannelsCatalogRef.current = true;
            try {
                const catalog = await getChannels();
                setChannelCatalog(catalog);
            } catch (err) {
                const error = err instanceof Error ? err : new Error(String(err));
                console.error('Failed to fetch channel catalog:', error);
                toast.error('Failed to load channels');
            }
        };

        void fetchChannelCatalog();
    }, []);

    /**
     * Load the built-in web-search provider catalog once because the binding
     * dialog reuses it for schema-driven provider forms.
     */
    useEffect(() => {
        if (hasFetchedWebSearchCatalogRef.current) return;

        const fetchWebSearchCatalog = async () => {
            hasFetchedWebSearchCatalogRef.current = true;
            try {
                const catalog = await getWebSearchProviders();
                setWebSearchCatalog(catalog);
            } catch (err) {
                const error = err instanceof Error ? err : new Error(String(err));
                console.error('Failed to fetch web search catalog:', error);
                toast.error('Failed to load web search providers');
            }
        };

        void fetchWebSearchCatalog();
    }, []);

    /**
     * Channel bindings are agent-specific, so reload them whenever the current
     * agent changes or after any binding mutation.
     */
    const loadChannels = useCallback(async () => {
        if (!agent?.id) {
            setChannels([]);
            return;
        }

        setChannelsLoading(true);
        try {
            const bindings = await getAgentChannels(agent.id);
            setChannels(
                bindings.map((binding) => ({
                    id: binding.id,
                    name: binding.name,
                    channelKey: binding.channel_key,
                    providerName: binding.manifest.name,
                    enabled: binding.enabled,
                    transportMode: binding.manifest.transport_mode,
                    lastHealthStatus: binding.last_health_status,
                }))
            );
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch channel bindings:', error);
            toast.error('Failed to load agent channels');
        } finally {
            setChannelsLoading(false);
        }
    }, [agent?.id]);

    useEffect(() => {
        void loadChannels();
    }, [loadChannels]);

    /**
     * Web-search bindings are agent-specific, so reload them whenever the
     * current agent changes or after any binding mutation.
     */
    const loadWebSearchBindings = useCallback(async () => {
        if (!agent?.id) {
            setWebSearchBindings([]);
            return;
        }

        setWebSearchLoading(true);
        try {
            const bindings = await getAgentWebSearchBindings(agent.id);
            setWebSearchBindings(
                bindings.map((binding) => ({
                    id: binding.id,
                    providerKey: binding.provider_key,
                    providerName: binding.manifest.name,
                    enabled: binding.enabled,
                    lastHealthStatus: binding.last_health_status,
                }))
            );
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch web search bindings:', error);
            toast.error('Failed to load web search providers');
        } finally {
            setWebSearchLoading(false);
        }
    }, [agent?.id]);

    useEffect(() => {
        void loadWebSearchBindings();
    }, [loadWebSearchBindings]);

    const handleEditAgent = async (data: AgentFormData) => {
        if (!agent) return;

        try {
            const updatedAgent = await updateAgent(agent.id, data);
            if (onAgentUpdate) {
                onAgentUpdate(updatedAgent);
            }
            toast.success('Agent updated successfully');
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(`Failed to update agent: ${error.message}`);
            throw error;
        }
    };

    /**
     * Handle section icon click in collapsed mode.
     * Expands sidebar and opens the clicked section while closing others.
     */
    const handleSectionClick = (section: 'scenes' | 'tools' | 'skills' | 'channels' | 'webSearch') => {
        if (state === 'collapsed') {
            // Expand sidebar first
            setOpen(true);
            // Delay section state update to ensure sidebar expansion completes
            setTimeout(() => {
                setIsScenesOpen(section === 'scenes');
                setIsToolsOpen(section === 'tools');
                setIsSkillsOpen(section === 'skills');
                setIsChannelsOpen(section === 'channels');
                setIsWebSearchOpen(section === 'webSearch');
            }, 100);
        } else {
            // In expanded mode, toggle section immediately
            setIsScenesOpen(section === 'scenes');
            setIsToolsOpen(section === 'tools');
            setIsSkillsOpen(section === 'skills');
            setIsChannelsOpen(section === 'channels');
            setIsWebSearchOpen(section === 'webSearch');
        }
    };

    /**
     * Handle scene item click.
     * Opens a new tab for the scene and maintains backward compatibility.
     */
    const handleSceneClick = (scene: Scene) => {
        // Open tab for this scene
        openTab({
            type: 'scene',
            name: scene.name,
            resourceId: scene.id,
        });

        // Keep backward compatibility with existing logic
        onSceneSelect(scene);
    };

    /**
     * Handle tool item click.
     * Opens Monaco tool tab and carries permission metadata.
     */
    const handleToolClick = (tool: SidebarTool) => {
        openTab({
            type: 'tool',
            name: tool.name,
            resourceId: buildToolResourceId(tool),
            meta: {
                kind: tool.kind,
                source: tool.source,
                readOnly: tool.readOnly,
            },
        });
    };

    /**
     * Handle skill item click.
     * Opens Monaco skill tab and carries permission metadata.
     */
    const handleSkillClick = (skill: SidebarSkill) => {
        openTab({
            type: 'skill',
            name: skill.name,
            resourceId: buildSkillResourceId(skill),
            meta: {
                kind: skill.kind,
                source: skill.source,
                readOnly: skill.readOnly,
            },
        });
    };

    /**
     * Open the channel binding dialog in create mode.
     */
    const handleAddChannel = () => {
        setEditingChannel(null);
        setIsChannelDialogOpen(true);
    };

    /**
     * Open the channel binding dialog with the latest binding payload.
     * Why: the sidebar keeps a compact projection, so we refetch the richer row.
     */
    const handleEditChannel = async (bindingId: number) => {
        if (!agent?.id) {
            return;
        }
        try {
            const bindings = await getAgentChannels(agent.id);
            const selectedBinding = bindings.find((binding) => binding.id === bindingId) ?? null;
            setEditingChannel(selectedBinding);
            setIsChannelDialogOpen(true);
        } catch {
            toast.error('Failed to load channel binding');
        }
    };

    /**
     * Delete one channel binding from the current agent.
     */
    const handleDeleteChannel = async (bindingId: number) => {
        try {
            await deleteAgentChannel(bindingId);
            toast.success('Channel binding removed');
            await loadChannels();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(error.message);
        }
    };

    /**
     * Open the web-search binding dialog in create mode.
     */
    const handleAddWebSearchBinding = () => {
        setEditingWebSearchBinding(null);
        setIsWebSearchDialogOpen(true);
    };

    /**
     * Open the web-search binding dialog with the latest binding payload.
     */
    const handleEditWebSearchBinding = async (bindingId: number) => {
        if (!agent?.id) {
            return;
        }
        try {
            const bindings = await getAgentWebSearchBindings(agent.id);
            const selectedBinding = bindings.find((binding) => binding.id === bindingId) ?? null;
            setEditingWebSearchBinding(selectedBinding);
            setIsWebSearchDialogOpen(true);
        } catch {
            toast.error('Failed to load web search provider');
        }
    };

    /**
     * Delete one web-search binding from the current agent.
     */
    const handleDeleteWebSearchBinding = async (bindingId: number) => {
        try {
            await deleteAgentWebSearchBinding(bindingId);
            toast.success('Web search provider removed');
            await loadWebSearchBindings();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(error.message);
        }
    };

    return (
        <>
            <Sidebar collapsible="icon" className="border-r border-sidebar-border">
                {/* Agent Header */}
                <SidebarHeader className="p-2">
                    <SidebarMenu>
                        <SidebarMenuItem>
                            {state === 'collapsed' ? (
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <button
                                            type="button"
                                            onClick={() => setOpen(true)}
                                            aria-label="Expand sidebar"
                                            className="group/avatar relative flex size-8 items-center justify-center overflow-hidden rounded-lg"
                                        >
                                            <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-transparent text-sidebar-foreground transition-all group-hover/avatar:scale-95 group-hover/avatar:opacity-0">
                                                <LLMBrandAvatar
                                                    model={agent?.model_name}
                                                    containerClassName="flex size-4 items-center justify-center"
                                                    imageClassName="size-4"
                                                    fallback={<Bot className="size-4" aria-hidden="true" />}
                                                />
                                            </span>
                                            <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-transparent text-sidebar-foreground/60 opacity-0 transition-all group-hover/avatar:opacity-100 group-hover/avatar:bg-sidebar-accent group-hover/avatar:text-sidebar-foreground">
                                                <PanelLeft className="size-4" />
                                            </span>
                                        </button>
                                    </TooltipTrigger>
                                    <TooltipContent side="right">
                                        Expand sidebar
                                    </TooltipContent>
                                </Tooltip>
                            ) : (
                                <div className="flex items-center gap-1">
                                    <SidebarMenuButton
                                        size="lg"
                                        onClick={() => setIsEditModalOpen(true)}
                                        tooltip="Edit Agent"
                                        className="min-w-0 flex-1"
                                    >
                                        <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-transparent text-sidebar-foreground">
                                            <LLMBrandAvatar
                                                model={agent?.model_name}
                                                containerClassName="flex size-4 items-center justify-center"
                                                imageClassName="size-4"
                                                fallback={<Bot className="size-4" aria-hidden="true" />}
                                            />
                                        </div>
                                        <div className="flex min-w-0 flex-1 flex-col gap-0.5 leading-none">
                                            <span className="truncate text-sm font-semibold">
                                                {agent?.name || 'Loading…'}
                                            </span>
                                            {agent?.is_active && (
                                                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                                    <span className="h-1.5 w-1.5 rounded-full bg-success" />
                                                    Active
                                                </span>
                                            )}
                                        </div>
                                    </SidebarMenuButton>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="icon"
                                                onClick={() => setOpen(false)}
                                                className="h-7 w-7 shrink-0 text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                                aria-label="Collapse sidebar"
                                            >
                                                <PanelLeft className="size-4" />
                                            </Button>
                                        </TooltipTrigger>
                                        <TooltipContent side="right">
                                            Collapse sidebar
                                        </TooltipContent>
                                    </Tooltip>
                                </div>
                            )}
                        </SidebarMenuItem>
                    </SidebarMenu>
                </SidebarHeader>

                <SidebarSeparator />

                <SidebarContent className="gap-0.5 pt-2">
                    {/* Scenes Section */}
                    <Collapsible
                        open={isScenesOpen}
                        onOpenChange={setIsScenesOpen}
                        className="group/collapsible"
                    >
                        <SidebarGroup className="py-0">
                            {/* Icon button for collapsed mode */}
                            <SidebarMenu className="group-data-[collapsible=icon]:flex hidden">
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        onClick={() => handleSectionClick('scenes')}
                                        tooltip="Scenes"
                                        isActive={isScenesOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Layers className="size-4" />
                                        <span>Scenes</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            {/* Full header for expanded mode */}
                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('scenes')}
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Layers className="size-4" />
                                    <span className="flex-1 text-left">Scenes</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {scenes.length}
                                    </span>
                                    <Tooltip>
                                        <TooltipTrigger asChild>
                                            <div
                                                role="button"
                                                tabIndex={0}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onCreateScene();
                                                }}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter' || e.key === ' ') {
                                                        e.stopPropagation();
                                                        onCreateScene();
                                                    }
                                                }}
                                                className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                aria-label="Add scene"
                                            >
                                                <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                            </div>
                                        </TooltipTrigger>
                                        <TooltipContent side="right">Add scene</TooltipContent>
                                    </Tooltip>
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    <SidebarMenu>
                                        {scenes.map((scene) => (
                                            <SidebarMenuItem key={scene.id} className="group/item">
                                                <SidebarMenuButton
                                                    isActive={selectedScene?.id === scene.id}
                                                    onClick={() => handleSceneClick(scene)}
                                                    tooltip={scene.name}
                                                    size="sm"
                                                    className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                                >
                                                    {/* Reserved icon slot */}
                                                    <span className="w-4 shrink-0" />
                                                    <span className="truncate">{scene.name}</span>
                                                </SidebarMenuButton>
                                                <SidebarMenuAction
                                                    showOnHover
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        onDeleteScene(scene);
                                                    }}
                                                    className="hover:bg-destructive/10 hover:text-destructive"
                                                >
                                                    <X className="size-3.5" />
                                                    <span className="sr-only">Delete scene</span>
                                                </SidebarMenuAction>
                                            </SidebarMenuItem>
                                        ))}
                                    </SidebarMenu>
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>

                    {/* Tools Section */}
                    <Collapsible
                        open={isToolsOpen}
                        onOpenChange={setIsToolsOpen}
                        className="group/collapsible"
                    >
                        <SidebarGroup className="py-0">
                            {/* Icon button for collapsed mode */}
                            <SidebarMenu className="group-data-[collapsible=icon]:flex hidden">
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        onClick={() => handleSectionClick('tools')}
                                        tooltip="Tools"
                                        isActive={isToolsOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Wrench className="size-4" />
                                        <span>Tools</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            {/* Full header for expanded mode */}
                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('tools')}
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Wrench className="size-4" />
                                    <span className="flex-1 text-left">Tools</span>
                                    {/* Count badge: shows enabled / total */}
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {toolsLoading ? '…' : enabledCount}
                                        {' / '}
                                        {toolsLoading ? '…' : tools.length}
                                    </span>
                                    {/* Configure button */}
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); setIsToolSelectorOpen(true); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); setIsToolSelectorOpen(true); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Configure tools"
                                                >
                                                    <Settings2 className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Configure tools</TooltipContent>
                                        </Tooltip>
                                    )}
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {toolsLoading ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            Loading tools…
                                        </div>
                                    ) : tools.length === 0 ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            No tools available
                                        </div>
                                    ) : displayedTools.length === 0 ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            No tools configured for this agent
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {displayedTools.map((t) => {
                                                const toolResourceId = buildToolResourceId(t);
                                                const toolTabId = `tool-${toolResourceId}`;
                                                return (
                                                <SidebarMenuItem key={`${t.kind}-${t.source}-${t.name}`}>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                onClick={() => handleToolClick(t)}
                                                                isActive={activeTabId === toolTabId}
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                                            >
                                                                {/* Reserved icon slot */}
                                                                <span className="w-4 shrink-0" />
                                                                <span className="truncate flex-1">{t.name}</span>
                                                                {/* Private badge */}
                                                                {t.kind === 'private' && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        me
                                                                    </span>
                                                                )}
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <div className="flex items-center gap-1.5">
                                                                    <p className="font-semibold">{t.name}</p>
                                                                    <span className="text-[10px] text-muted-foreground">
                                                                        {t.kind === 'shared' ? '· shared' : '· private'}
                                                                    </span>
                                                                </div>
                                                                {t.description && (
                                                                    <p className="text-xs text-muted-foreground whitespace-pre-wrap break-words">
                                                                        {t.description}
                                                                    </p>
                                                                )}
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                </SidebarMenuItem>
                                                );
                                            })}
                                        </SidebarMenu>
                                    )}
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>

                    {/* Skills Section */}
                    <Collapsible
                        open={isSkillsOpen}
                        onOpenChange={setIsSkillsOpen}
                        className="group/collapsible"
                    >
                        <SidebarGroup className="py-0">
                            {/* Icon button for collapsed mode */}
                            <SidebarMenu className="group-data-[collapsible=icon]:flex hidden">
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        onClick={() => handleSectionClick('skills')}
                                        tooltip="Skills"
                                        isActive={isSkillsOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Zap className="size-4" />
                                        <span>Skills</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            {/* Full header for expanded mode */}
                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('skills')}
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Zap className="size-4" />
                                    <span className="flex-1 text-left">Skills</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {skillsLoading ? '…' : enabledSkillCount}
                                        {' / '}
                                        {skillsLoading ? '…' : skills.length}
                                    </span>
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); setIsSkillSelectorOpen(true); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); setIsSkillSelectorOpen(true); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Configure skills"
                                                >
                                                    <Settings2 className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Configure skills</TooltipContent>
                                        </Tooltip>
                                    )}
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {skillsLoading ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            Loading skills…
                                        </div>
                                    ) : skills.length === 0 ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            No skills available
                                        </div>
                                    ) : displayedSkills.length === 0 ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            No skills configured for this agent
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {displayedSkills.map((s) => {
                                                const skillResourceId = buildSkillResourceId(s);
                                                const skillTabId = `skill-${skillResourceId}`;
                                                return (
                                                <SidebarMenuItem key={`${s.kind}-${s.source}-${s.name}`}>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                onClick={() => handleSkillClick(s)}
                                                                isActive={activeTabId === skillTabId}
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                                            >
                                                                <span className="w-4 shrink-0" />
                                                                <span className="truncate flex-1">{s.name}</span>
                                                                {s.kind === 'private' && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        me
                                                                    </span>
                                                                )}
                                                                {s.kind === 'shared' && !s.readOnly && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        you
                                                                    </span>
                                                                )}
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <div className="flex items-center gap-1.5">
                                                                    <p className="font-semibold">{s.name}</p>
                                                                    <span className="text-[10px] text-muted-foreground">
                                                                        {s.kind === 'shared'
                                                                            ? s.source === 'builtin'
                                                                                ? '· shared · builtin'
                                                                                : s.readOnly
                                                                                  ? `· shared · ${s.creator ?? 'unknown'}`
                                                                                  : '· shared · you'
                                                                            : '· private'}
                                                                    </span>
                                                                </div>
                                                                {s.description && (
                                                                    <p className="text-xs text-muted-foreground whitespace-pre-wrap break-words">
                                                                        {s.description}
                                                                    </p>
                                                                )}
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                </SidebarMenuItem>
                                                );
                                            })}
                                        </SidebarMenu>
                                    )}
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>

                    {/* Channels Section */}
                    <Collapsible
                        open={isChannelsOpen}
                        onOpenChange={setIsChannelsOpen}
                        className="group/collapsible"
                    >
                        <SidebarGroup className="py-0">
                            <SidebarMenu className="group-data-[collapsible=icon]:flex hidden">
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        onClick={() => handleSectionClick('channels')}
                                        tooltip="Channels"
                                        isActive={isChannelsOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Radio className="size-4" />
                                        <span>Channels</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('channels')}
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Radio className="size-4" />
                                    <span className="flex-1 text-left">Channels</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {channelsLoading ? '…' : channels.length}
                                    </span>
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); handleAddChannel(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); handleAddChannel(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add channel"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add channel</TooltipContent>
                                        </Tooltip>
                                    )}
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {channelsLoading ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            Loading channels…
                                        </div>
                                    ) : channels.length === 0 ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            No channels configured for this agent
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {channels.map((channel) => (
                                                <SidebarMenuItem key={channel.id} className="group/item">
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                onClick={() => void handleEditChannel(channel.id)}
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                                                            >
                                                                <span className="w-4 shrink-0" />
                                                                <span className="truncate flex-1">{channel.name}</span>
                                                                <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                    {channel.enabled ? 'on' : 'off'}
                                                                </span>
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <p className="font-semibold">{channel.providerName}</p>
                                                                <p className="text-xs text-muted-foreground">
                                                                    {channel.transportMode} · {formatChannelStatus(channel.lastHealthStatus)}
                                                                </p>
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                    <SidebarMenuAction
                                                        showOnHover
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            void handleDeleteChannel(channel.id);
                                                        }}
                                                        className="hover:bg-destructive/10 hover:text-destructive"
                                                    >
                                                        <X className="size-3.5" />
                                                        <span className="sr-only">Delete channel</span>
                                                    </SidebarMenuAction>
                                                </SidebarMenuItem>
                                            ))}
                                        </SidebarMenu>
                                    )}
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>

                    {/* Web Search Section */}
                    <Collapsible
                        open={isWebSearchOpen}
                        onOpenChange={setIsWebSearchOpen}
                        className="group/collapsible"
                    >
                        <SidebarGroup className="py-0">
                            <SidebarMenu className="group-data-[collapsible=icon]:flex hidden">
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        onClick={() => handleSectionClick('webSearch')}
                                        tooltip="Web Search"
                                        isActive={isWebSearchOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Globe className="size-4" />
                                        <span>Web Search</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('webSearch')}
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Globe className="size-4" />
                                    <span className="flex-1 text-left">Web Search</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {webSearchLoading ? '…' : webSearchBindings.length}
                                    </span>
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); handleAddWebSearchBinding(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); handleAddWebSearchBinding(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add web search provider"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add web search provider</TooltipContent>
                                        </Tooltip>
                                    )}
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {webSearchLoading ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            Loading web search providers…
                                        </div>
                                    ) : webSearchBindings.length === 0 ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            No web search providers configured for this agent
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {webSearchBindings.map((binding) => (
                                                <SidebarMenuItem key={binding.id} className="group/item">
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                onClick={() => void handleEditWebSearchBinding(binding.id)}
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                                                            >
                                                                <span className="w-4 shrink-0" />
                                                                <span className="truncate flex-1">{binding.providerName}</span>
                                                                <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                    {binding.enabled ? 'on' : 'off'}
                                                                </span>
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <p className="font-semibold">{binding.providerName}</p>
                                                                <p className="text-xs text-muted-foreground">
                                                                    {binding.providerKey} · {formatChannelStatus(binding.lastHealthStatus)}
                                                                </p>
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                    <SidebarMenuAction
                                                        showOnHover
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            void handleDeleteWebSearchBinding(binding.id);
                                                        }}
                                                        className="hover:bg-destructive/10 hover:text-destructive"
                                                    >
                                                        <X className="size-3.5" />
                                                        <span className="sr-only">Delete web search provider</span>
                                                    </SidebarMenuAction>
                                                </SidebarMenuItem>
                                            ))}
                                        </SidebarMenu>
                                    )}
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>
                </SidebarContent>

                <SidebarSeparator />

                <SidebarFooter className="p-2">
                    <SidebarMenu>
                        <SidebarMenuItem>
                            <SidebarMenuButton
                                onClick={onOpenReactChat}
                                tooltip="Chat with Agent"
                                size="lg"
                                className={
                                    state === 'collapsed'
                                        ? 'justify-center bg-sidebar-primary/10 text-sidebar-primary hover:bg-sidebar-primary/15 hover:text-sidebar-primary'
                                        : 'bg-sidebar-primary/10 text-sidebar-primary hover:bg-sidebar-primary/15 hover:text-sidebar-primary'
                                }
                            >
                                <MessageSquare className="size-4" />
                                {state !== 'collapsed' && (
                                    <span className="font-medium">Chat with Agent</span>
                                )}
                            </SidebarMenuButton>
                        </SidebarMenuItem>
                    </SidebarMenu>
                </SidebarFooter>

                {/* Rail for collapse/expand toggle */}
                <SidebarRail />
            </Sidebar>

            {/* Edit Agent Modal */}
            <AgentModal
                isOpen={isEditModalOpen}
                mode="edit"
                initialData={
                    agent
                        ? {
                            name: agent.name,
                            description: agent.description,
                            llm_id: agent.llm_id,
                            skill_resolution_llm_id: agent.skill_resolution_llm_id ?? null,
                            session_idle_timeout_minutes:
                                agent.session_idle_timeout_minutes,
                            compact_threshold_percent:
                                agent.compact_threshold_percent,
                            is_active: agent.is_active,
                        }
                        : undefined
                }
                onClose={() => setIsEditModalOpen(false)}
                onSave={handleEditAgent}
            />

            {/* Tool Selector Dialog */}
            {agent?.id && (
                <ToolSelectorDialog
                    open={isToolSelectorOpen}
                    onOpenChange={setIsToolSelectorOpen}
                    agentId={agent.id}
                    currentToolIds={localToolIds}
                    onSaved={(newToolIds) => {
                        setLocalToolIds(newToolIds);
                        if (onAgentUpdate && agent) {
                            onAgentUpdate({ ...agent, tool_ids: newToolIds });
                        }
                    }}
                />
            )}

            {/* Skill Selector Dialog */}
            {agent?.id && (
                <SkillSelectorDialog
                    open={isSkillSelectorOpen}
                    onOpenChange={setIsSkillSelectorOpen}
                    agentId={agent.id}
                    currentSkillIds={localSkillIds}
                    onSaved={(newSkillIds) => {
                        setLocalSkillIds(newSkillIds);
                        if (onAgentUpdate && agent) {
                            onAgentUpdate({ ...agent, skill_ids: newSkillIds });
                        }
                    }}
                />
            )}

            {/* Channel Binding Dialog */}
            {agent?.id && (
                <ChannelBindingDialog
                    open={isChannelDialogOpen}
                    onOpenChange={setIsChannelDialogOpen}
                    agentId={agent.id}
                    catalog={channelCatalog}
                    initialBinding={editingChannel}
                    onSaved={async () => {
                        await loadChannels();
                    }}
                />
            )}

            {/* Web Search Binding Dialog */}
            {agent?.id && (
                <WebSearchBindingDialog
                    open={isWebSearchDialogOpen}
                    onOpenChange={setIsWebSearchDialogOpen}
                    agentId={agent.id}
                    catalog={webSearchCatalog}
                    configuredProviderKeys={webSearchBindings.map((binding) => binding.providerKey)}
                    initialBinding={editingWebSearchBinding}
                    onSaved={async () => {
                        await loadWebSearchBindings();
                    }}
                />
            )}
        </>
    );
}

export default AgentDetailSidebar;
