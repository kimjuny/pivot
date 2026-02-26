import { useState, useEffect, useRef, useMemo } from 'react';
import {
    Bot,
    ChevronDown,
    Layers,
    Wrench,
    Zap,
    Sparkles,
    Plus,
    X,
    MessageSquare,
    Settings2,
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
import AgentModal, { AgentFormData } from './AgentModal';
import ToolSelectorDialog from './ToolSelectorDialog';
import SkillSelectorDialog from './SkillSelectorDialog';
import type { Agent, Scene } from '../types';
import {
    updateAgent,
    getSharedTools,
    getPrivateTools,
    getSharedSkills,
    getPrivateSkills,
    type SharedTool,
    type PrivateTool,
    type SharedSkill,
    type UserSkill,
} from '../utils/api';
import { toast } from 'sonner';
import { useAgentTabStore } from '../store/agentTabStore';

/** Unified tool entry for sidebar display. */
interface SidebarTool {
    name: string;
    description: string;
    kind: 'shared' | 'private';
}

/** Unified skill entry for sidebar display. */
interface SidebarSkill {
    name: string;
    description: string;
    kind: 'shared' | 'private';
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
    onOpenBuildChat: () => void;
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
    onOpenBuildChat,
    onOpenReactChat,
    onAgentUpdate,
}: AgentDetailSidebarProps) {
    const { state, setOpen } = useSidebar();
    const [isScenesOpen, setIsScenesOpen] = useState(true);
    const [isToolsOpen, setIsToolsOpen] = useState(false);
    const [isSkillsOpen, setIsSkillsOpen] = useState(false);
    const [isEditModalOpen, setIsEditModalOpen] = useState(false);
    const [isToolSelectorOpen, setIsToolSelectorOpen] = useState(false);
    const [isSkillSelectorOpen, setIsSkillSelectorOpen] = useState(false);
    const [tools, setTools] = useState<SidebarTool[]>([]);
    const [skills, setSkills] = useState<SidebarSkill[]>([]);
    const [toolsLoading, setToolsLoading] = useState(false);
    const [skillsLoading, setSkillsLoading] = useState(false);
    // Local copy of the agent's tool_ids so it updates without a page reload
    const [localToolIds, setLocalToolIds] = useState<string | null | undefined>(agent?.tool_ids);
    // Local copy of the agent's skill_ids so it updates without a page reload
    const [localSkillIds, setLocalSkillIds] = useState<string | null | undefined>(agent?.skill_ids);
    const hasFetchedToolsRef = useRef(false);
    const hasFetchedSkillsRef = useRef(false);
    const { openTab } = useAgentTabStore();

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
                    })),
                    ...priv.map((t: PrivateTool) => ({
                        name: t.name,
                        description: '',
                        kind: 'private' as const,
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
                    })),
                    ...priv.map((s: UserSkill) => ({
                        name: s.name,
                        description: s.description,
                        kind: 'private' as const,
                    })),
                ];

                const deduped = Array.from(
                    merged.reduce((map, item) => {
                        if (!map.has(item.name)) {
                            map.set(item.name, item);
                        }
                        return map;
                    }, new Map<string, SidebarSkill>()).values()
                );
                setSkills(deduped);
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
    const handleSectionClick = (section: 'scenes' | 'tools' | 'skills') => {
        if (state === 'collapsed') {
            // Expand sidebar first
            setOpen(true);
            // Delay section state update to ensure sidebar expansion completes
            setTimeout(() => {
                setIsScenesOpen(section === 'scenes');
                setIsToolsOpen(section === 'tools');
                setIsSkillsOpen(section === 'skills');
            }, 100);
        } else {
            // In expanded mode, toggle section immediately
            setIsScenesOpen(section === 'scenes');
            setIsToolsOpen(section === 'tools');
            setIsSkillsOpen(section === 'skills');
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

    return (
        <>
            <Sidebar collapsible="icon" className="border-r border-sidebar-border">
                {/* Agent Header */}
                <SidebarHeader className="p-2">
                    <SidebarMenu>
                        <SidebarMenuItem>
                            <SidebarMenuButton
                                size="lg"
                                onClick={() => setIsEditModalOpen(true)}
                                tooltip="Edit Agent"
                                className="w-full"
                            >
                                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                                    <Bot className="size-4" />
                                </div>
                                <div className="flex flex-col gap-0.5 leading-none min-w-0 flex-1">
                                    <span className="font-semibold truncate text-sm">
                                        {agent?.name || 'Loading…'}
                                    </span>
                                    {agent?.is_active && (
                                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                            <span className="w-1.5 h-1.5 rounded-full bg-success" />
                                            Active
                                        </span>
                                    )}
                                </div>
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <div
                                            role="button"
                                            tabIndex={0}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onOpenReactChat();
                                            }}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' || e.key === ' ') {
                                                    e.stopPropagation();
                                                    onOpenReactChat();
                                                }
                                            }}
                                            className="p-1.5 hover:bg-sidebar-accent rounded transition-colors cursor-pointer"
                                            aria-label="Open Chat"
                                        >
                                            <MessageSquare className="size-4" />
                                        </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="right">
                                        <p>Chat with Agent</p>
                                    </TooltipContent>
                                </Tooltip>
                            </SidebarMenuButton>
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
                                        <SidebarMenuItem>
                                            <SidebarMenuButton
                                                onClick={onCreateScene}
                                                className="pl-3 text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                                                size="sm"
                                            >
                                                {/* Icon slot with Plus */}
                                                <span className="w-4 shrink-0 flex items-center justify-center">
                                                    <Plus className="size-3.5" />
                                                </span>
                                                <span>Add Scene</span>
                                            </SidebarMenuButton>
                                        </SidebarMenuItem>
                                    </SidebarMenu>
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>

                    {/* Tools Section (Not Implemented) */}
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
                                            {displayedTools.map((t) => (
                                                <SidebarMenuItem key={`${t.kind}-${t.name}`}>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
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
                                            ))}
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
                                            {displayedSkills.map((s) => (
                                                <SidebarMenuItem key={`${s.kind}-${s.name}`}>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                                                            >
                                                                <span className="w-4 shrink-0" />
                                                                <span className="truncate flex-1">{s.name}</span>
                                                                {s.kind === 'private' && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        me
                                                                    </span>
                                                                )}
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <div className="flex items-center gap-1.5">
                                                                    <p className="font-semibold">{s.name}</p>
                                                                    <span className="text-[10px] text-muted-foreground">
                                                                        {s.kind === 'shared' ? '· shared' : '· private'}
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
                                            ))}
                                        </SidebarMenu>
                                    )}
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>
                </SidebarContent>

                <SidebarFooter className="p-2">
                    <SidebarMenu>
                        <SidebarMenuItem>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <SidebarMenuButton
                                        onClick={onOpenBuildChat}
                                        className="bg-sidebar-primary/10 hover:bg-sidebar-primary/15 text-sidebar-primary"
                                        size="lg"
                                    >
                                        <Sparkles className="size-4" />
                                        <span className="font-medium">Build Mode</span>
                                    </SidebarMenuButton>
                                </TooltipTrigger>
                                <TooltipContent side="right">
                                    Open AI-assisted build chat
                                </TooltipContent>
                            </Tooltip>
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
        </>
    );
}

export default AgentDetailSidebar;
