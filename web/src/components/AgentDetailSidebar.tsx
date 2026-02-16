import { useState, useEffect, useRef } from 'react';
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
import type { Agent, Scene } from '../types';
import { updateAgent, getTools, type Tool } from '../utils/api';
import { toast } from 'sonner';
import { useAgentTabStore } from '../store/agentTabStore';

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
 * Shows agent info, scenes list, tools, and skills (coming soon).
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
    const [tools, setTools] = useState<Tool[]>([]);
    const [toolsLoading, setToolsLoading] = useState(false);
    const hasFetchedToolsRef = useRef(false);
    const { openTab } = useAgentTabStore();

    /**
     * Fetch tools list on component mount.
     * Uses useRef to prevent duplicate fetches in React Strict Mode.
     */
    useEffect(() => {
        // Prevent duplicate fetches
        if (hasFetchedToolsRef.current) return;

        const fetchTools = async () => {
            hasFetchedToolsRef.current = true;
            setToolsLoading(true);
            try {
                const toolsList = await getTools();
                setTools(toolsList);
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
                                        <button
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                onOpenReactChat();
                                            }}
                                            className="p-1.5 hover:bg-sidebar-accent rounded transition-colors"
                                            aria-label="Open Chat"
                                        >
                                            <MessageSquare className="size-4" />
                                        </button>
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
                                        className="text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
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
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
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
                                                    className="text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground"
                                                >
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
                                                className="border border-dashed border-sidebar-border text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent hover:border-sidebar-primary"
                                                size="sm"
                                            >
                                                <Plus className="size-3.5" />
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
                                        className="text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
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
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Wrench className="size-4" />
                                    <span className="flex-1 text-left">Tools</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {toolsLoading ? '...' : tools.length}
                                    </span>
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {toolsLoading ? (
                                        <div className="px-2 py-3 text-xs text-muted-foreground text-center">
                                            Loading tools…
                                        </div>
                                    ) : tools.length === 0 ? (
                                        <div className="px-2 py-3 text-xs text-muted-foreground text-center">
                                            No tools available
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {tools.map((tool) => (
                                                <SidebarMenuItem key={tool.name}>
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                className="text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent pl-7"
                                                            >
                                                                <span className="truncate">{tool.name}</span>
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <p className="font-semibold">{tool.name}</p>
                                                                <p className="text-xs text-muted-foreground">
                                                                    {tool.description}
                                                                </p>
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
                                        className="text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
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
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/50 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Zap className="size-4" />
                                    <span className="flex-1 text-left">Skills</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/50 italic">
                                        Soon
                                    </span>
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden">
                                <SidebarGroupContent>
                                    <div className="px-2 py-3 text-xs text-muted-foreground text-center">
                                        Skills integration coming soon…
                                    </div>
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
                                        className="bg-sidebar-primary/10 hover:bg-sidebar-primary/20 text-sidebar-primary"
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
                            is_active: agent.is_active,
                        }
                        : undefined
                }
                onClose={() => setIsEditModalOpen(false)}
                onSave={handleEditAgent}
            />
        </>
    );
}

export default AgentDetailSidebar;
