import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
    Bot,
    ChevronRight,
    Layers,
    type LucideIcon,
    Server,
    Wrench,
    Zap,
    Radio,
    Plus,
    X,
    Settings2,
    PanelLeft,
    Globe,
} from "@/lib/lucide";
import { useSidebar } from '@/hooks/use-sidebar';
import {
    Sidebar,
    SidebarContent,
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
import { Skeleton } from '@/components/ui/skeleton';
import AgentModal, { AgentFormData } from './AgentModal';
import ToolSelectorDialog from './ToolSelectorDialog';
import SkillSelectorDialog from './SkillSelectorDialog';
import ChannelBindingDialog from './ChannelBindingDialog';
import ExtensionBindingDialog from './ExtensionBindingDialog';
import WebSearchBindingDialog from './WebSearchBindingDialog';
import MediaGenerationBindingDialog from './MediaGenerationBindingDialog';
import { ChannelProviderBadge } from './ChannelProviderBadge';
import ConfirmationModal from './ConfirmationModal';
import { ExtensionLogoAvatar } from './ExtensionLogoAvatar';
import { MediaProviderBadge } from './MediaProviderBadge';
import { LLMBrandAvatar } from './LLMBrandAvatar';
import { WebSearchProviderBadge } from './WebSearchProviderBadge';
import {
    formatProviderExtensionLabel,
    formatProviderVisibilityLabel,
} from '@/utils/providerMetadata';
import type { Agent } from '../types';
import {
    getUsableTools,
    getUsableSkills,
    getChannels,
    getAgentChannels,
    getAgentExtensionPackages,
    deleteAgentChannel,
    deleteAgentExtensionBinding,
    getMediaGenerationProviders,
    getAgentMediaProviderBindings,
    deleteAgentMediaProviderBinding,
    getWebSearchProviders,
    getAgentWebSearchBindings,
    deleteAgentWebSearchBinding,
    getAgentSidebarStats,
    updateAgentAccess,
    type AgentAccess,
    type AgentExtensionPackage,
    type AgentSidebarSectionStats,
    type AgentSidebarStats,
    type UsableTool,
    type SkillSource,
    type UsableSkill,
    type ChannelBinding,
    type ChannelCatalogItem,
    type MediaProviderBinding,
    type MediaProviderCatalogItem,
    type WebSearchBinding,
    type WebSearchCatalogItem,
} from '../utils/api';
import { toast } from 'sonner';
import { useAgentTabStore } from '../store/agentTabStore';

/** Unified tool entry for sidebar display. */
interface SidebarTool {
    name: string;
    description: string;
    source: 'builtin' | 'user' | 'extension';
    extensionLabel?: string | null;
    readOnly: boolean;
}

/** Unified skill entry for sidebar display. */
interface SidebarSkill {
    name: string;
    description: string;
    source: SkillSource | 'extension';
    extensionLabel?: string | null;
    creator: string | null;
    readOnly: boolean;
}

/**
 * Compact channel binding snapshot used by the sidebar and workspace status.
 */
export interface SidebarChannel {
    id: number;
    name: string;
    channelKey: string;
    providerName: string;
    providerVisibility: string;
    providerExtensionLabel: string | null;
    enabled: boolean;
    effectiveEnabled: boolean;
    disabledReason: string | null;
    transportMode: 'webhook' | 'websocket' | 'polling';
    lastHealthStatus: string | null;
}

/**
 * Compact web-search binding snapshot used by the sidebar and workspace status.
 */
export interface SidebarWebSearchBinding {
    id: number;
    providerKey: string;
    providerName: string;
    providerVisibility: string;
    providerExtensionLabel: string | null;
    enabled: boolean;
    effectiveEnabled: boolean;
    disabledReason: string | null;
    lastHealthStatus: string | null;
}

/**
 * Compact media-provider binding snapshot used by the sidebar and workspace status.
 */
export interface SidebarMediaProviderBinding {
    id: number;
    providerKey: string;
    providerName: string;
    mediaType: 'image' | 'video';
    providerVisibility: string;
    providerExtensionLabel: string | null;
    enabled: boolean;
    effectiveEnabled: boolean;
    disabledReason: string | null;
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
 */
function buildToolResourceId(tool: SidebarTool): string {
    return `${tool.source}:${tool.name}`;
}

/**
 * Build a unique resource ID for skill tabs.
 */
function buildSkillResourceId(skill: SidebarSkill): string {
    return `${skill.source}:${skill.name}`;
}

/**
 * Parses the serialized tool selection from agent.tool_ids.
 */
function parseToolIds(toolIds: string | null | undefined): Set<string> {
    if (toolIds === null || toolIds === undefined) {
        return new Set<string>();
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
 * Parses the serialized skill selection from agent.skill_ids.
 */
function parseSkillIds(skillIds: string | null | undefined): Set<string> {
    if (skillIds === null || skillIds === undefined) {
        return new Set<string>();
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

function stringifyNameSet(names: Set<string>): string {
    return JSON.stringify(Array.from(names).sort());
}

function formatSidebarCountLabel(
    stats: AgentSidebarSectionStats | null | undefined,
): string {
    if (!stats) {
        return '_ / _';
    }
    return `${stats.selected_count} / ${stats.total_count}`;
}

function withSelectedCount(
    stats: AgentSidebarSectionStats | null | undefined,
    selectedCount: number,
): AgentSidebarSectionStats | null | undefined {
    if (!stats) {
        return stats;
    }
    return {
        ...stats,
        selected_count: selectedCount,
    };
}

function SidebarSectionLeadingIcon({
    icon: Icon,
    isOpen,
}: {
    icon: LucideIcon;
    isOpen: boolean;
}) {
    return (
        <span className="pointer-events-none absolute left-2 flex size-4 items-center justify-center">
            <Icon
                className={`absolute size-4 transition-all duration-150 ${
                    isOpen
                        ? 'scale-90 opacity-0'
                        : 'scale-100 opacity-100 group-hover/section-trigger:scale-90 group-hover/section-trigger:opacity-0 group-focus-visible/section-trigger:scale-90 group-focus-visible/section-trigger:opacity-0'
                }`}
            />
            <ChevronRight
                className={`absolute size-3.5 transition-all duration-150 ${
                    isOpen
                        ? 'scale-100 rotate-90 opacity-100'
                        : 'scale-90 rotate-0 opacity-0 group-hover/section-trigger:scale-100 group-hover/section-trigger:opacity-100 group-focus-visible/section-trigger:scale-100 group-focus-visible/section-trigger:opacity-100'
                }`}
            />
        </span>
    );
}

function SidebarCountBadge({
    stats,
    animationIndex,
}: {
    stats: AgentSidebarSectionStats | null | undefined;
    animationIndex: number;
}) {
    const [animateIn, setAnimateIn] = useState(false);
    const label = formatSidebarCountLabel(stats);
    const prefersLeftToRight = animationIndex % 2 === 0;
    const transitionDelayMs = animationIndex * 24;

    useEffect(() => {
        if (!stats) {
            setAnimateIn(false);
            return;
        }
        setAnimateIn(false);
        const frame = window.requestAnimationFrame(() => {
            setAnimateIn(true);
        });
        return () => {
            window.cancelAnimationFrame(frame);
        };
    }, [label, stats]);

    return (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
            <span
                style={{
                    transitionDuration: '80ms',
                    transitionDelay: stats ? `${transitionDelayMs}ms` : '0ms',
                }}
                className={`inline-block transition-all duration-150 ${
                    stats
                        ? animateIn
                            ? 'translate-x-0 opacity-100'
                            : prefersLeftToRight
                                ? '-translate-x-2 opacity-0'
                                : 'translate-x-2 opacity-0'
                        : 'translate-x-0 opacity-100'
                }`}
            >
                {label}
            </span>
        </span>
    );
}

function SidebarItemSkeleton({
    testId,
}: {
    testId: string;
}) {
    return (
        <SidebarMenuItem data-testid={testId}>
            <div className="px-2" role="status" aria-live="polite">
                <Skeleton
                    className="h-7 w-full rounded-md bg-sidebar-accent"
                    aria-hidden="true"
                />
            </div>
        </SidebarMenuItem>
    );
}

function useDelayedLoadingVisibility(
    isLoading: boolean,
    delayMs = 500,
): boolean {
    const [shouldShow, setShouldShow] = useState(false);

    useEffect(() => {
        if (isLoading) {
            const timeout = window.setTimeout(() => {
                setShouldShow(true);
            }, delayMs);

            return () => {
                window.clearTimeout(timeout);
            };
        }

        setShouldShow(false);

        return () => {
            setShouldShow(false);
        };
    }, [delayMs, isLoading]);

    return shouldShow;
}

/**
 * Summarize extension contributions that will disappear with one binding.
 */
function formatExtensionRemovalMessage(pkg: AgentExtensionPackage | null): string {
    const installation = pkg?.selected_binding?.installation;
    if (!installation) {
        return 'Removing this extension will also remove its agent-scoped contributions.';
    }

    const summary = installation.contribution_summary;
    const counts = [
        { label: 'tools', count: summary.tools?.length ?? 0 },
        { label: 'skills', count: summary.skills?.length ?? 0 },
        { label: 'channel providers', count: summary.channel_providers?.length ?? 0 },
        { label: 'media providers', count: summary.media_providers?.length ?? 0 },
        { label: 'web search providers', count: summary.web_search_providers?.length ?? 0 },
        { label: 'hooks', count: summary.hooks?.length ?? 0 },
        { label: 'chat surfaces', count: summary.chat_surfaces?.length ?? 0 },
    ].filter((item) => item.count > 0);

    if (counts.length === 0) {
        return `Remove ${pkg.display_name} from this agent?`;
    }

    const detail = counts.map((item) => `${item.count} ${item.label}`).join(', ');
    return `Removing ${pkg.display_name} will also unload ${detail} from this agent.`;
}

interface AgentDetailSidebarProps {
    agent: Agent | null;
    activeReleaseVersion?: number | null;
    onAgentDraftUpdate?: (agent: Agent) => void;
    onChannelBindingsLoaded?: (bindings: SidebarChannel[]) => void;
    onMediaProviderBindingsLoaded?: (bindings: SidebarMediaProviderBinding[]) => void;
    onWebSearchBindingsLoaded?: (bindings: SidebarWebSearchBinding[]) => void;
    onExtensionBindingsChanged?: () => void | Promise<void>;
    onChannelBindingsChanged?: () => void | Promise<void>;
    onMediaProviderBindingsChanged?: () => void | Promise<void>;
    onWebSearchBindingsChanged?: () => void | Promise<void>;
}

/**
 * Sidebar for agent detail page.
 * Shows agent info, tools, skills, and binding state.
 * Uses shadcn sidebar components for consistent styling.
 */
function AgentDetailSidebar({
    agent,
    activeReleaseVersion = null,
    onAgentDraftUpdate,
    onChannelBindingsLoaded,
    onMediaProviderBindingsLoaded,
    onWebSearchBindingsLoaded,
    onExtensionBindingsChanged,
    onChannelBindingsChanged,
    onMediaProviderBindingsChanged,
    onWebSearchBindingsChanged,
}: AgentDetailSidebarProps) {
    const { state, setOpen } = useSidebar();
    const [isToolsOpen, setIsToolsOpen] = useState(false);
    const [isSkillsOpen, setIsSkillsOpen] = useState(false);
    const [isChannelsOpen, setIsChannelsOpen] = useState(false);
    const [isMediaProvidersOpen, setIsMediaProvidersOpen] = useState(false);
    const [isWebSearchOpen, setIsWebSearchOpen] = useState(false);
    const [isExtensionsOpen, setIsExtensionsOpen] = useState(false);
    const [isEditModalOpen, setIsEditModalOpen] = useState(false);
    const [isToolSelectorOpen, setIsToolSelectorOpen] = useState(false);
    const [isSkillSelectorOpen, setIsSkillSelectorOpen] = useState(false);
    const [isChannelDialogOpen, setIsChannelDialogOpen] = useState(false);
    const [isMediaProviderDialogOpen, setIsMediaProviderDialogOpen] = useState(false);
    const [isWebSearchDialogOpen, setIsWebSearchDialogOpen] = useState(false);
    const [isExtensionDialogOpen, setIsExtensionDialogOpen] = useState(false);
    const [isDeleteExtensionDialogOpen, setIsDeleteExtensionDialogOpen] = useState(false);
    const [editingChannel, setEditingChannel] = useState<ChannelBinding | null>(null);
    const [editingMediaProviderBinding, setEditingMediaProviderBinding] = useState<MediaProviderBinding | null>(null);
    const [editingWebSearchBinding, setEditingWebSearchBinding] = useState<WebSearchBinding | null>(null);
    const [editingExtensionPackage, setEditingExtensionPackage] = useState<AgentExtensionPackage | null>(null);
    const [deletingExtensionPackage, setDeletingExtensionPackage] = useState<AgentExtensionPackage | null>(null);
    const [tools, setTools] = useState<SidebarTool[]>([]);
    const [skills, setSkills] = useState<SidebarSkill[]>([]);
    const [channels, setChannels] = useState<SidebarChannel[]>([]);
    const [imageProviderBindings, setMediaProviderBindings] = useState<SidebarMediaProviderBinding[]>([]);
    const [webSearchBindings, setWebSearchBindings] = useState<SidebarWebSearchBinding[]>([]);
    const [extensionPackages, setExtensionPackages] = useState<AgentExtensionPackage[]>([]);
    const [channelCatalog, setChannelCatalog] = useState<ChannelCatalogItem[]>([]);
    const [imageProviderCatalog, setMediaProviderCatalog] = useState<MediaProviderCatalogItem[]>([]);
    const [webSearchCatalog, setWebSearchCatalog] = useState<WebSearchCatalogItem[]>([]);
    const [sidebarStats, setSidebarStats] = useState<AgentSidebarStats | null>(null);
    const [toolsLoading, setToolsLoading] = useState(false);
    const [skillsLoading, setSkillsLoading] = useState(false);
    const [channelsLoading, setChannelsLoading] = useState(false);
    const [imageProvidersLoading, setMediaProvidersLoading] = useState(false);
    const [webSearchLoading, setWebSearchLoading] = useState(false);
    const [extensionsLoading, setExtensionsLoading] = useState(false);
    // Local copy of the agent's tool_ids so it updates without a page reload
    const [localToolIds, setLocalToolIds] = useState<string | null | undefined>(agent?.tool_ids);
    // Local copy of the agent's skill_ids so it updates without a page reload
    const [localSkillIds, setLocalSkillIds] = useState<string | null | undefined>(agent?.skill_ids);
    const currentAgentId = agent?.id ?? null;
    const hasFetchedToolsRef = useRef(false);
    const hasFetchedSkillsRef = useRef(false);
    const hasFetchedExtensionPackagesRef = useRef(false);
    const hasFetchedChannelsRef = useRef(false);
    const hasFetchedMediaProvidersRef = useRef(false);
    const hasFetchedWebSearchRef = useRef(false);
    const latestAgentIdRef = useRef<number | null>(currentAgentId);
    const previousAgentIdRef = useRef<number | null>(currentAgentId);
    const agentChangedSinceLastRender = previousAgentIdRef.current !== currentAgentId;
    const { openTab, activeTabId } = useAgentTabStore();
    const selectedExtensionPackages = useMemo(
        () => extensionPackages.filter((pkg) => pkg.selected_binding !== null),
        [extensionPackages],
    );

    // Sync localToolIds when the agent prop changes
    useEffect(() => {
        setLocalToolIds(agent?.tool_ids);
    }, [agent?.tool_ids]);

    // Sync localSkillIds when the agent prop changes
    useEffect(() => {
        setLocalSkillIds(agent?.skill_ids);
    }, [agent?.skill_ids]);

    useEffect(() => {
        previousAgentIdRef.current = currentAgentId;
    }, [currentAgentId]);

    /**
     * Reset agent-scoped sidebar projections when the inspected agent changes.
     * Why: the detail page reuses one sidebar instance across agents, so the
     * previous agent's bindings can otherwise linger until the next fetch wins.
     */
    useEffect(() => {
        latestAgentIdRef.current = agent?.id ?? null;
        setChannels([]);
        setMediaProviderBindings([]);
        setWebSearchBindings([]);
        setExtensionPackages([]);
        setChannelCatalog([]);
        setMediaProviderCatalog([]);
        setWebSearchCatalog([]);
        setSidebarStats(null);
        setEditingChannel(null);
        setEditingMediaProviderBinding(null);
        setEditingWebSearchBinding(null);
        setEditingExtensionPackage(null);
        setDeletingExtensionPackage(null);
        setIsToolsOpen(false);
        setIsSkillsOpen(false);
        setIsExtensionsOpen(false);
        setIsChannelsOpen(false);
        setIsMediaProvidersOpen(false);
        setIsWebSearchOpen(false);
        setIsChannelDialogOpen(false);
        setIsMediaProviderDialogOpen(false);
        setIsWebSearchDialogOpen(false);
        setIsExtensionDialogOpen(false);
        setIsDeleteExtensionDialogOpen(false);
        hasFetchedExtensionPackagesRef.current = false;
        hasFetchedChannelsRef.current = false;
        hasFetchedMediaProvidersRef.current = false;
        hasFetchedWebSearchRef.current = false;
    }, [agent?.id]);

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

    /**
     * Extension tools and skills are inherited from enabled extension bindings
     * instead of being controlled by the legacy allowlists.
     */
    const extensionTools = useMemo<SidebarTool[]>(
        () => extensionPackages.flatMap((pkg) => {
            if (!pkg.selected_binding?.enabled) {
                return [];
            }
            return pkg.selected_binding.installation.contribution_items
                .filter((item) => item.type === 'tool')
                .map((item) => ({
                    name: item.name,
                    description: item.description,
                    source: 'extension' as const,
                    extensionLabel: pkg.display_name,
                    readOnly: true,
                }));
        }),
        [extensionPackages]
    );

    const extensionSkills = useMemo<SidebarSkill[]>(
        () => extensionPackages.flatMap((pkg) => {
            if (!pkg.selected_binding?.enabled) {
                return [];
            }
            return pkg.selected_binding.installation.contribution_items
                .filter((item) => item.type === 'skill')
                .map((item) => ({
                    name: item.name,
                    description: item.description,
                    source: 'extension' as const,
                    extensionLabel: pkg.display_name,
                    creator: null,
                    readOnly: true,
                }));
        }),
        [extensionPackages]
    );

    const enabledExtensionToolNameSet = useMemo(
        () => new Set(extensionTools.map((tool) => tool.name)),
        [extensionTools]
    );
    const enabledExtensionSkillNameSet = useMemo(
        () => new Set(extensionSkills.map((skill) => skill.name)),
        [extensionSkills]
    );

    const displayedTools = useMemo(() => {
        return [...tools, ...extensionTools].filter((tool) => enabledToolNameSet.has(tool.name));
    }, [tools, extensionTools, enabledToolNameSet]);

    /**
     * Sidebar should display skills that are currently configured for this
     * agent, instead of the global skill catalog.
     */
    const displayedSkills = useMemo(() => {
        return [...skills, ...extensionSkills].filter((skill) => enabledSkillNameSet.has(skill.name));
    }, [skills, extensionSkills, enabledSkillNameSet]);

    /**
     * Tools and skills are edited in the local draft first, so their selected
     * counts should reflect the draft immediately instead of waiting for the
     * persisted sidebar stats endpoint to catch up.
     */
    const effectiveSidebarStats = useMemo(() => {
        if (!sidebarStats) {
            return null;
        }
        return {
            ...sidebarStats,
            tools: withSelectedCount(sidebarStats.tools, enabledToolNameSet.size),
            skills: withSelectedCount(sidebarStats.skills, enabledSkillNameSet.size),
        };
    }, [enabledSkillNameSet, enabledToolNameSet, sidebarStats]);

    const stageToolIds = useCallback((nextToolIds: string) => {
        setLocalToolIds(nextToolIds);
        if (onAgentDraftUpdate && agent) {
            onAgentDraftUpdate({ ...agent, tool_ids: nextToolIds });
        }
    }, [agent, onAgentDraftUpdate]);

    const stageSkillIds = useCallback((nextSkillIds: string) => {
        setLocalSkillIds(nextSkillIds);
        if (onAgentDraftUpdate && agent) {
            onAgentDraftUpdate({ ...agent, skill_ids: nextSkillIds });
        }
    }, [agent, onAgentDraftUpdate]);

    const previousEnabledExtensionToolNameSetRef = useRef<Set<string>>(new Set());
    const previousEnabledExtensionSkillNameSetRef = useRef<Set<string>>(new Set());

    useEffect(() => {
        previousEnabledExtensionToolNameSetRef.current = new Set();
        previousEnabledExtensionSkillNameSetRef.current = new Set();
    }, [agent?.id]);

    useEffect(() => {
        const previousNames = previousEnabledExtensionToolNameSetRef.current;
        const nextNames = enabledExtensionToolNameSet;
        const addedNames = Array.from(nextNames).filter((name) => !previousNames.has(name));
        const removedNames = Array.from(previousNames).filter((name) => !nextNames.has(name));

        if (addedNames.length === 0 && removedNames.length === 0) {
            return;
        }

        const nextSelected = parseToolIds(localToolIds);
        addedNames.forEach((name) => nextSelected.add(name));
        removedNames.forEach((name) => nextSelected.delete(name));
        previousEnabledExtensionToolNameSetRef.current = new Set(nextNames);
        stageToolIds(stringifyNameSet(nextSelected));
    }, [enabledExtensionToolNameSet, localToolIds, stageToolIds]);

    useEffect(() => {
        const previousNames = previousEnabledExtensionSkillNameSetRef.current;
        const nextNames = enabledExtensionSkillNameSet;
        const addedNames = Array.from(nextNames).filter((name) => !previousNames.has(name));
        const removedNames = Array.from(previousNames).filter((name) => !nextNames.has(name));

        if (addedNames.length === 0 && removedNames.length === 0) {
            return;
        }

        const nextSelected = parseSkillIds(localSkillIds);
        addedNames.forEach((name) => nextSelected.add(name));
        removedNames.forEach((name) => nextSelected.delete(name));
        previousEnabledExtensionSkillNameSetRef.current = new Set(nextNames);
        stageSkillIds(stringifyNameSet(nextSelected));
    }, [enabledExtensionSkillNameSet, localSkillIds, stageSkillIds]);

    /**
     * Prefer installation-backed branding because one package card may point at
     * an older package-level snapshot while the selected binding targets the
     * concrete installed version the agent is actively using.
     */
    const getExtensionLogoUrl = useCallback(
        (pkg: AgentExtensionPackage): string | null => (
            pkg.selected_binding?.installation.logo_url
            ?? pkg.logo_url
            ?? null
        ),
        []
    );

    const webSearchLogoUrlByKey = useMemo<Record<string, string | null>>(
        () => Object.fromEntries(
            webSearchCatalog.map((item) => [
                item.manifest.key,
                item.manifest.logo_url ?? null,
            ])
        ),
        [webSearchCatalog]
    );

    /**
     * Resolve one extension-backed provider logo from the matching installed
     * package version whenever the manifest references an extension package.
     */
    const getProviderExtensionLogoUrl = useCallback(
        (
            extensionPackageId: string | null | undefined,
            extensionVersion: string | null | undefined,
        ): string | null => {
            if (!extensionPackageId) {
                return null;
            }

            const pkg = extensionPackages.find(
                (item) => item.package_id === extensionPackageId
            );
            if (!pkg) {
                return null;
            }

            if (extensionVersion) {
                const matchingVersion = pkg.versions.find(
                    (installation) => installation.version === extensionVersion
                );
                if (matchingVersion?.logo_url) {
                    return matchingVersion.logo_url;
                }

                if (pkg.selected_binding?.installation.version === extensionVersion) {
                    return getExtensionLogoUrl(pkg);
                }
            }

            return getExtensionLogoUrl(pkg);
        },
        [extensionPackages, getExtensionLogoUrl]
    );

    /**
     * Media providers do not ship dedicated provider logos today, so reuse the
     * owning extension package logo when the provider comes from an extension.
     */
    const imageProviderLogoUrlByKey = useMemo<Record<string, string | null>>(
        () => Object.fromEntries(
            imageProviderCatalog.map((item) => [
                item.manifest.key,
                getProviderExtensionLogoUrl(
                    item.manifest.extension_name,
                    item.manifest.extension_version,
                ),
            ])
        ),
        [imageProviderCatalog, getProviderExtensionLogoUrl]
    );

    /**
     * Load compact sidebar counts before any section-specific data.
     */
    const loadSidebarStats = useCallback(async () => {
        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setSidebarStats(null);
            return;
        }

        setSidebarStats(null);
        try {
            const stats = await getAgentSidebarStats(requestedAgentId);
            if (latestAgentIdRef.current !== requestedAgentId) {
                return;
            }
            setSidebarStats(stats);
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch sidebar stats:', error);
            toast.error('Failed to load sidebar statistics');
        }
    }, [agent?.id]);

    useEffect(() => {
        void loadSidebarStats();
    }, [loadSidebarStats]);

    const loadTools = useCallback(async (force = false) => {
        if (hasFetchedToolsRef.current && !force) {
            return;
        }

        setToolsLoading(true);
        try {
            const usableTools = await getUsableTools();
            const merged: SidebarTool[] = usableTools.map((tool: UsableTool) => ({
                name: tool.name,
                description: tool.description,
                source: tool.source_type === 'builtin' ? 'builtin' : 'user',
                readOnly: tool.read_only,
            }));
            hasFetchedToolsRef.current = true;
            setTools(merged);
        } catch (err) {
            hasFetchedToolsRef.current = false;
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch tools:', error);
            toast.error('Failed to load tools');
        } finally {
            setToolsLoading(false);
        }
    }, []);

    const loadSkills = useCallback(async (force = false) => {
        if (hasFetchedSkillsRef.current && !force) {
            return;
        }

        setSkillsLoading(true);
        try {
            const usableSkills = await getUsableSkills();
            const merged: SidebarSkill[] = usableSkills.map((s: UsableSkill) => ({
                name: s.name,
                description: s.description,
                source: s.source,
                creator: s.creator,
                readOnly: s.read_only,
            }));
            hasFetchedSkillsRef.current = true;
            setSkills(merged);
        } catch (err) {
            hasFetchedSkillsRef.current = false;
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch skills:', error);
            toast.error('Failed to load skills');
        } finally {
            setSkillsLoading(false);
        }
    }, []);

    const loadExtensionPackages = useCallback(async (force = false) => {
        if (hasFetchedExtensionPackagesRef.current && !force) {
            return;
        }

        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setExtensionPackages([]);
            return;
        }

        setExtensionsLoading(true);
        try {
            const packages = await getAgentExtensionPackages(requestedAgentId);
            if (latestAgentIdRef.current !== requestedAgentId) {
                return;
            }
            hasFetchedExtensionPackagesRef.current = true;
            setExtensionPackages(packages);
        } catch (err) {
            hasFetchedExtensionPackagesRef.current = false;
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch extension packages:', error);
            toast.error('Failed to load extensions');
        } finally {
            if (latestAgentIdRef.current === requestedAgentId) {
                setExtensionsLoading(false);
            }
        }
    }, [agent?.id]);

    useEffect(() => {
        if (!agent?.id) {
            return;
        }
        void loadExtensionPackages();
    }, [agent?.id, loadExtensionPackages]);

    const loadChannels = useCallback(async (force = false) => {
        if (hasFetchedChannelsRef.current && !force) {
            return;
        }

        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setChannelCatalog([]);
            setChannels([]);
            return;
        }

        setChannelsLoading(true);
        try {
            const [catalog, bindings] = await Promise.all([
                getChannels(requestedAgentId),
                getAgentChannels(requestedAgentId),
            ]);
            if (latestAgentIdRef.current !== requestedAgentId) {
                return;
            }
            const nextBindings = bindings.map((binding) => ({
                id: binding.id,
                name: binding.name,
                channelKey: binding.channel_key,
                providerName: binding.manifest.name,
                providerVisibility: binding.manifest.visibility,
                providerExtensionLabel: formatProviderExtensionLabel(
                    binding.manifest.extension_display_name,
                    binding.manifest.extension_name,
                    binding.manifest.extension_version,
                ),
                enabled: binding.enabled,
                effectiveEnabled: binding.effective_enabled ?? binding.enabled,
                disabledReason: binding.disabled_reason ?? null,
                transportMode: binding.manifest.transport_mode,
                lastHealthStatus: binding.last_health_status,
            }));
            hasFetchedChannelsRef.current = true;
            setChannelCatalog(catalog);
            setChannels(nextBindings);
            onChannelBindingsLoaded?.(nextBindings);
        } catch (err) {
            hasFetchedChannelsRef.current = false;
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch channel data:', error);
            toast.error('Failed to load channels');
        } finally {
            if (latestAgentIdRef.current === requestedAgentId) {
                setChannelsLoading(false);
            }
        }
    }, [agent?.id, onChannelBindingsLoaded]);

    const loadMediaProviderBindings = useCallback(async (force = false) => {
        if (hasFetchedMediaProvidersRef.current && !force) {
            return;
        }

        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setMediaProviderCatalog([]);
            setMediaProviderBindings([]);
            return;
        }

        setMediaProvidersLoading(true);
        try {
            const [catalog, bindings] = await Promise.all([
                getMediaGenerationProviders(requestedAgentId),
                getAgentMediaProviderBindings(requestedAgentId),
            ]);
            if (latestAgentIdRef.current !== requestedAgentId) {
                return;
            }
            const nextBindings = bindings.map((binding) => ({
                id: binding.id,
                providerKey: binding.provider_key,
                providerName: binding.manifest.name,
                mediaType: binding.manifest.media_type,
                providerVisibility: binding.manifest.visibility,
                providerExtensionLabel: formatProviderExtensionLabel(
                    binding.manifest.extension_display_name,
                    binding.manifest.extension_name,
                    binding.manifest.extension_version,
                ),
                enabled: binding.enabled,
                effectiveEnabled: binding.effective_enabled ?? binding.enabled,
                disabledReason: binding.disabled_reason ?? null,
                lastHealthStatus: binding.last_health_status,
            }));
            hasFetchedMediaProvidersRef.current = true;
            setMediaProviderCatalog(catalog);
            setMediaProviderBindings(nextBindings);
            onMediaProviderBindingsLoaded?.(nextBindings);
        } catch (err) {
            hasFetchedMediaProvidersRef.current = false;
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch media provider data:', error);
            toast.error('Failed to load media providers');
        } finally {
            if (latestAgentIdRef.current === requestedAgentId) {
                setMediaProvidersLoading(false);
            }
        }
    }, [agent?.id, onMediaProviderBindingsLoaded]);

    const loadWebSearchBindings = useCallback(async (force = false) => {
        if (hasFetchedWebSearchRef.current && !force) {
            return;
        }

        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setWebSearchCatalog([]);
            setWebSearchBindings([]);
            return;
        }

        setWebSearchLoading(true);
        try {
            const [catalog, bindings] = await Promise.all([
                getWebSearchProviders(requestedAgentId),
                getAgentWebSearchBindings(requestedAgentId),
            ]);
            if (latestAgentIdRef.current !== requestedAgentId) {
                return;
            }
            const nextBindings = bindings.map((binding) => ({
                id: binding.id,
                providerKey: binding.provider_key,
                providerName: binding.manifest.name,
                providerVisibility: binding.manifest.visibility,
                providerExtensionLabel: formatProviderExtensionLabel(
                    binding.manifest.extension_display_name,
                    binding.manifest.extension_name,
                    binding.manifest.extension_version,
                ),
                enabled: binding.enabled,
                effectiveEnabled: binding.effective_enabled ?? binding.enabled,
                disabledReason: binding.disabled_reason ?? null,
                lastHealthStatus: binding.last_health_status,
            }));
            hasFetchedWebSearchRef.current = true;
            setWebSearchCatalog(catalog);
            setWebSearchBindings(nextBindings);
            onWebSearchBindingsLoaded?.(nextBindings);
        } catch (err) {
            hasFetchedWebSearchRef.current = false;
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch web search data:', error);
            toast.error('Failed to load web search providers');
        } finally {
            if (latestAgentIdRef.current === requestedAgentId) {
                setWebSearchLoading(false);
            }
        }
    }, [agent?.id, onWebSearchBindingsLoaded]);

    useEffect(() => {
        if (!isToolsOpen || agentChangedSinceLastRender) {
            return;
        }
        void Promise.all([loadTools(), loadExtensionPackages()]);
    }, [agentChangedSinceLastRender, isToolsOpen, loadExtensionPackages, loadTools]);

    useEffect(() => {
        if (!isSkillsOpen || agentChangedSinceLastRender) {
            return;
        }
        void Promise.all([loadSkills(), loadExtensionPackages()]);
    }, [agentChangedSinceLastRender, isSkillsOpen, loadExtensionPackages, loadSkills]);

    useEffect(() => {
        if (!isExtensionsOpen || agentChangedSinceLastRender) {
            return;
        }
        void loadExtensionPackages();
    }, [agentChangedSinceLastRender, isExtensionsOpen, loadExtensionPackages]);

    useEffect(() => {
        if (!isToolSelectorOpen || agentChangedSinceLastRender) {
            return;
        }
        void loadExtensionPackages();
    }, [agentChangedSinceLastRender, isToolSelectorOpen, loadExtensionPackages]);

    useEffect(() => {
        if (!isSkillSelectorOpen || agentChangedSinceLastRender) {
            return;
        }
        void loadExtensionPackages();
    }, [agentChangedSinceLastRender, isSkillSelectorOpen, loadExtensionPackages]);

    useEffect(() => {
        if (!isChannelsOpen || agentChangedSinceLastRender) {
            return;
        }
        void loadChannels();
    }, [agentChangedSinceLastRender, isChannelsOpen, loadChannels]);

    useEffect(() => {
        if (!isMediaProvidersOpen || agentChangedSinceLastRender) {
            return;
        }
        void loadMediaProviderBindings();
    }, [agentChangedSinceLastRender, isMediaProvidersOpen, loadMediaProviderBindings]);

    useEffect(() => {
        if (!isWebSearchOpen || agentChangedSinceLastRender) {
            return;
        }
        void loadWebSearchBindings();
    }, [agentChangedSinceLastRender, isWebSearchOpen, loadWebSearchBindings]);

    const handleEditAgent = async (data: AgentFormData): Promise<void> => {
        if (!agent) {
            return Promise.resolve();
        }

        try {
            if (onAgentDraftUpdate) {
                onAgentDraftUpdate({ ...agent, ...data });
            }
            await updateAgentAccess(agent.id, {
                ...data.access,
                agent_id: agent.id,
                edit_user_ids: [],
                edit_group_ids: [],
            } satisfies AgentAccess);
            toast.success('Agent changes staged in draft');
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
    const handleSectionClick = (section: 'tools' | 'skills' | 'extensions' | 'channels' | 'imageProviders' | 'webSearch') => {
        if (state === 'collapsed') {
            // Expand sidebar first
            setOpen(true);
            // Delay section state update to ensure sidebar expansion completes
            setTimeout(() => {
                setIsToolsOpen(section === 'tools');
                setIsSkillsOpen(section === 'skills');
                setIsExtensionsOpen(section === 'extensions');
                setIsChannelsOpen(section === 'channels');
                setIsMediaProvidersOpen(section === 'imageProviders');
                setIsWebSearchOpen(section === 'webSearch');
            }, 100);
        } else {
            // In expanded mode, toggle section immediately
            setIsToolsOpen(section === 'tools');
            setIsSkillsOpen(section === 'skills');
            setIsExtensionsOpen(section === 'extensions');
            setIsChannelsOpen(section === 'channels');
            setIsMediaProvidersOpen(section === 'imageProviders');
            setIsWebSearchOpen(section === 'webSearch');
        }
    };

    /**
     * Handle tool item click.
     * Opens Monaco tool tab and carries permission metadata.
     */
    const handleToolClick = (tool: SidebarTool) => {
        if (tool.source === 'extension') {
            return;
        }
        openTab({
            type: 'tool',
            name: tool.name,
            resourceId: buildToolResourceId(tool),
            meta: {
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
        if (skill.source === 'extension') {
            return;
        }
        openTab({
            type: 'skill',
            name: skill.name,
            resourceId: buildSkillResourceId(skill),
            meta: {
                source: skill.source,
                readOnly: skill.readOnly,
            },
        });
    };

    /**
     * Open the channel binding dialog in create mode.
     */
    const handleAddChannel = async () => {
        await loadChannels();
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
            await Promise.all([
                loadChannels(true),
                loadSidebarStats(),
            ]);
            await onChannelBindingsChanged?.();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(error.message);
        }
    };

    /**
     * Open the web-search binding dialog in create mode.
     */
    const handleAddWebSearchBinding = async () => {
        await loadWebSearchBindings();
        setEditingWebSearchBinding(null);
        setIsWebSearchDialogOpen(true);
    };

    /**
     * Open the media-provider binding dialog in create mode.
     */
    const handleAddMediaProviderBinding = async () => {
        await loadMediaProviderBindings();
        setEditingMediaProviderBinding(null);
        setIsMediaProviderDialogOpen(true);
    };

    /**
     * Open the media-provider binding dialog with the latest binding payload.
     */
    const handleEditMediaProviderBinding = async (bindingId: number) => {
        if (!agent?.id) {
            return;
        }
        try {
            const bindings = await getAgentMediaProviderBindings(agent.id);
            const selectedBinding = bindings.find((binding) => binding.id === bindingId) ?? null;
            setEditingMediaProviderBinding(selectedBinding);
            setIsMediaProviderDialogOpen(true);
        } catch {
            toast.error('Failed to load media provider');
        }
    };

    /**
     * Delete one media-provider binding from the current agent.
     */
    const handleDeleteMediaProviderBinding = async (bindingId: number) => {
        try {
            await deleteAgentMediaProviderBinding(bindingId);
            toast.success('Media provider removed');
            await Promise.all([
                loadMediaProviderBindings(true),
                loadSidebarStats(),
            ]);
            await onMediaProviderBindingsChanged?.();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(error.message);
        }
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
            await Promise.all([
                loadWebSearchBindings(true),
                loadSidebarStats(),
            ]);
            await onWebSearchBindingsChanged?.();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(error.message);
        }
    };

    /**
     * Open the extension dialog in create mode.
     */
    const handleAddExtension = async () => {
        await loadExtensionPackages();
        setEditingExtensionPackage(null);
        setIsExtensionDialogOpen(true);
    };

    /**
     * Open the extension dialog for one already selected package.
     */
    const handleEditExtension = (pkg: AgentExtensionPackage) => {
        setEditingExtensionPackage(pkg);
        setIsExtensionDialogOpen(true);
    };

    /**
     * Open the destructive confirmation flow for one extension binding.
     */
    const handleRequestDeleteExtension = (pkg: AgentExtensionPackage) => {
        setDeletingExtensionPackage(pkg);
        setIsDeleteExtensionDialogOpen(true);
    };

    /**
     * Delete one extension binding from the current agent and reload children.
     */
    const handleConfirmDeleteExtension = async () => {
        const extensionInstallationId =
            deletingExtensionPackage?.selected_binding?.extension_installation_id ?? null;
        if (!agent?.id) {
            return;
        }
        if (!extensionInstallationId) {
            setIsDeleteExtensionDialogOpen(false);
            setDeletingExtensionPackage(null);
            return;
        }
        try {
            await deleteAgentExtensionBinding(agent.id, extensionInstallationId);
            toast.success('Extension removed');
            setIsDeleteExtensionDialogOpen(false);
            setDeletingExtensionPackage(null);
            await loadSidebarStats();
            await Promise.all([
                loadExtensionPackages(true),
                hasFetchedChannelsRef.current ? loadChannels(true) : Promise.resolve(),
                hasFetchedMediaProvidersRef.current
                    ? loadMediaProviderBindings(true)
                    : Promise.resolve(),
                hasFetchedWebSearchRef.current
                    ? loadWebSearchBindings(true)
                    : Promise.resolve(),
            ]);
            await onExtensionBindingsChanged?.();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(error.message);
        }
    };

    const toolsSectionLoading = toolsLoading || extensionsLoading;
    const skillsSectionLoading = skillsLoading || extensionsLoading;
    const visibleToolsSectionLoading = useDelayedLoadingVisibility(toolsSectionLoading);
    const visibleSkillsSectionLoading = useDelayedLoadingVisibility(skillsSectionLoading);
    const visibleExtensionsLoading = useDelayedLoadingVisibility(extensionsLoading);
    const visibleChannelsLoading = useDelayedLoadingVisibility(channelsLoading);
    const visibleMediaProvidersLoading = useDelayedLoadingVisibility(imageProvidersLoading);
    const visibleWebSearchLoading = useDelayedLoadingVisibility(webSearchLoading);

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
                                            <div className="flex items-center gap-1.5">
                                                <span className="truncate text-sm font-semibold">
                                                    {agent?.name || 'Loading…'}
                                                </span>
                                                <span
                                                    aria-label={agent?.serving_enabled === false ? 'Serving disabled' : 'Serving enabled'}
                                                    title={agent?.serving_enabled === false ? 'Serving disabled' : 'Serving enabled'}
                                                    className={`h-1.5 w-1.5 rounded-full ${
                                                        agent?.serving_enabled === false
                                                            ? 'bg-red-500'
                                                            : 'bg-blue-500'
                                                    }`}
                                                />
                                            </div>
                                            <span className="inline-flex w-fit items-center rounded-md bg-sidebar-accent/50 px-1.5 py-0.5 text-[10px] text-sidebar-foreground/70">
                                                {activeReleaseVersion !== null
                                                    ? `Active v${activeReleaseVersion}`
                                                    : 'not published'}
                                            </span>
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
                    <SidebarGroup className="py-0 pb-1 pt-2">
                        <SidebarGroupLabel className="h-6 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-sidebar-foreground/45">
                            Capabilities
                        </SidebarGroupLabel>
                    </SidebarGroup>

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
                                    className="group/section-trigger relative flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-foreground"
                                >
                                    <SidebarSectionLeadingIcon icon={Wrench} isOpen={isToolsOpen} />
                                    <span className="flex-1 text-left">Tools</span>
                                    {/* Count badge: shows enabled / total */}
                                    <SidebarCountBadge stats={effectiveSidebarStats?.tools} animationIndex={0} />
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
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {visibleToolsSectionLoading ? (
                                        <SidebarMenu>
                                            <SidebarItemSkeleton testId="agent-sidebar-tools-skeleton" />
                                        </SidebarMenu>
                                    ) : toolsLoading ? null : tools.length + extensionTools.length === 0 || displayedTools.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={() => setIsToolSelectorOpen(true)}
                                                disabled={!agent?.id}
                                                className="justify-center text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                            >
                                                <Plus className="size-3.5" />
                                                Add first tool
                                            </SidebarMenuButton>
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {displayedTools.map((t) => {
                                                const toolResourceId = buildToolResourceId(t);
                                                const toolTabId = `tool-${toolResourceId}`;
                                                return (
                                                <SidebarMenuItem key={`${t.source}-${t.name}`}>
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
                                                                {t.source === 'extension' && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        ext
                                                                    </span>
                                                                )}
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <div className="flex items-center gap-1.5">
                                                                    <p className="font-semibold">{t.name}</p>
                                                                    <span className="text-[10px] text-muted-foreground">
                                                                        {t.source === 'extension'
                                                                            ? `· extension · ${t.extensionLabel ?? 'unknown'}`
                                                                            : t.source === 'builtin'
                                                                              ? '· builtin'
                                                                              : '· manual'}
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
                                    className="group/section-trigger relative flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-foreground"
                                >
                                    <SidebarSectionLeadingIcon icon={Zap} isOpen={isSkillsOpen} />
                                    <span className="flex-1 text-left">Skills</span>
                                    <SidebarCountBadge stats={effectiveSidebarStats?.skills} animationIndex={1} />
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
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {visibleSkillsSectionLoading ? (
                                        <SidebarMenu>
                                            <SidebarItemSkeleton testId="agent-sidebar-skills-skeleton" />
                                        </SidebarMenu>
                                    ) : skillsLoading ? null : skills.length + extensionSkills.length === 0 || displayedSkills.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={() => setIsSkillSelectorOpen(true)}
                                                disabled={!agent?.id}
                                                className="justify-center text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                            >
                                                <Plus className="size-3.5" />
                                                Add first skill
                                            </SidebarMenuButton>
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {displayedSkills.map((s) => {
                                                const skillResourceId = buildSkillResourceId(s);
                                                const skillTabId = `skill-${skillResourceId}`;
                                                return (
                                                <SidebarMenuItem key={`${s.source}-${s.name}`}>
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
                                                                {s.source === 'extension' && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        ext
                                                                    </span>
                                                                )}
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <div className="flex items-center gap-1.5">
                                                                    <p className="font-semibold">{s.name}</p>
                                                                    <span className="text-[10px] text-muted-foreground">
                                                                        {s.source === 'extension'
                                                                            ? `· extension · ${s.extensionLabel ?? 'unknown'}`
                                                                            : s.readOnly
                                                                              ? `· read-only · ${s.creator ?? 'unknown'}`
                                                                              : '· editable'}
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

                    <SidebarGroup className="py-0 pb-1 pt-2">
                        <SidebarGroupLabel className="h-6 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-sidebar-foreground/45">
                            Connections
                        </SidebarGroupLabel>
                    </SidebarGroup>

                    {/* Channels Section */}
                    <Collapsible
                        open={isExtensionsOpen}
                        onOpenChange={setIsExtensionsOpen}
                        className="group/collapsible"
                    >
                        <SidebarGroup className="py-0">
                            <SidebarMenu className="group-data-[collapsible=icon]:flex hidden">
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        onClick={() => handleSectionClick('extensions')}
                                        tooltip="Extensions"
                                        isActive={isExtensionsOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Server className="size-4" />
                                        <span>Extensions</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('extensions')}
                                    className="group/section-trigger relative flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-foreground"
                                >
                                    <SidebarSectionLeadingIcon icon={Server} isOpen={isExtensionsOpen} />
                                    <span className="flex-1 text-left">Extensions</span>
                                    <SidebarCountBadge stats={sidebarStats?.extensions} animationIndex={2} />
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); void handleAddExtension(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); void handleAddExtension(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add extension"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add extension</TooltipContent>
                                        </Tooltip>
                                    )}
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {visibleExtensionsLoading ? (
                                        <SidebarMenu>
                                            <SidebarItemSkeleton testId="agent-sidebar-extensions-skeleton" />
                                        </SidebarMenu>
                                    ) : extensionsLoading ? null : selectedExtensionPackages.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={() => { void handleAddExtension(); }}
                                                disabled={!agent?.id}
                                                className="justify-center text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                            >
                                                <Plus className="size-3.5" />
                                                Add first extension
                                            </SidebarMenuButton>
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {selectedExtensionPackages.map((pkg) => (
                                                <SidebarMenuItem key={pkg.package_id} className="group/item">
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                onClick={() => handleEditExtension(pkg)}
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                                                            >
                                                                <ExtensionLogoAvatar
                                                                    name={pkg.display_name}
                                                                    logoUrl={getExtensionLogoUrl(pkg)}
                                                                    fallback={<Server className="size-3.5" aria-hidden="true" />}
                                                                    containerClassName="flex size-3.5 shrink-0 items-center justify-center overflow-hidden rounded-sm text-sidebar-foreground/60"
                                                                    imageClassName="size-full object-contain"
                                                                />
                                                                <span className="truncate flex-1">
                                                                    {pkg.display_name}
                                                                </span>
                                                                <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                    {pkg.selected_binding?.installation.version ?? pkg.latest_version}
                                                                </span>
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <div className="flex items-center gap-1.5">
                                                                    <p className="font-semibold">{pkg.display_name}</p>
                                                                    {pkg.has_update_available && (
                                                                        <span className="text-[10px] text-primary">
                                                                            update available
                                                                        </span>
                                                                    )}
                                                                </div>
                                                                <p className="text-xs text-muted-foreground">
                                                                    {pkg.selected_binding?.installation.version ?? 'Unbound'}
                                                                    {' · '}
                                                                    {pkg.selected_binding?.enabled ? 'enabled' : 'disabled'}
                                                                </p>
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                    {pkg.selected_binding && (
                                                        <SidebarMenuAction
                                                            showOnHover
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleRequestDeleteExtension(pkg);
                                                            }}
                                                            className="hover:bg-destructive/10 hover:text-destructive"
                                                        >
                                                            <X className="size-3.5" />
                                                            <span className="sr-only">Delete extension</span>
                                                        </SidebarMenuAction>
                                                    )}
                                                </SidebarMenuItem>
                                            ))}
                                        </SidebarMenu>
                                    )}
                                </SidebarGroupContent>
                            </CollapsibleContent>
                        </SidebarGroup>
                    </Collapsible>

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
                                    className="group/section-trigger relative flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-foreground"
                                >
                                    <SidebarSectionLeadingIcon icon={Radio} isOpen={isChannelsOpen} />
                                    <span className="flex-1 text-left">Channels</span>
                                    <SidebarCountBadge stats={sidebarStats?.channels} animationIndex={3} />
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); void handleAddChannel(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); void handleAddChannel(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add channel"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add channel</TooltipContent>
                                        </Tooltip>
                                    )}
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {visibleChannelsLoading ? (
                                        <SidebarMenu>
                                            <SidebarItemSkeleton testId="agent-sidebar-channels-skeleton" />
                                        </SidebarMenu>
                                    ) : channelsLoading ? null : channels.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={() => { void handleAddChannel(); }}
                                                disabled={!agent?.id}
                                                className="justify-center text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                            >
                                                <Plus className="size-3.5" />
                                                Add first channel
                                            </SidebarMenuButton>
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
                                                                <ChannelProviderBadge
                                                                    channelKey={channel.channelKey}
                                                                    name={channel.providerName}
                                                                    className="w-4 shrink-0 justify-center"
                                                                    textClassName="hidden"
                                                                />
                                                                <span className="truncate flex-1">{channel.name}</span>
                                                                <span className="text-[9px] px-1 rounded border border-sidebar-border/60 text-sidebar-foreground/50 shrink-0">
                                                                    {channel.providerVisibility === 'extension' ? 'ext' : 'core'}
                                                                </span>
                                                                <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                    {channel.effectiveEnabled ? 'on' : 'off'}
                                                                </span>
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <p className="font-semibold">{channel.providerName}</p>
                                                                <p className="text-xs text-muted-foreground">
                                                                    {formatProviderVisibilityLabel(channel.providerVisibility)} · {channel.transportMode} · {formatChannelStatus(channel.lastHealthStatus)}
                                                                </p>
                                                                {channel.providerExtensionLabel ? (
                                                                    <p className="text-xs text-muted-foreground">
                                                                        {channel.providerExtensionLabel}
                                                                    </p>
                                                                ) : null}
                                                                {channel.disabledReason ? (
                                                                    <p className="text-xs text-muted-foreground">
                                                                        {channel.disabledReason}
                                                                    </p>
                                                                ) : null}
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

                    {/* Media Providers Section */}
                    <Collapsible
                        open={isMediaProvidersOpen}
                        onOpenChange={setIsMediaProvidersOpen}
                        className="group/collapsible"
                    >
                        <SidebarGroup className="py-0">
                            <SidebarMenu className="group-data-[collapsible=icon]:flex hidden">
                                <SidebarMenuItem>
                                    <SidebarMenuButton
                                        onClick={() => handleSectionClick('imageProviders')}
                                        tooltip="Media"
                                        isActive={isMediaProvidersOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Layers className="size-4" />
                                        <span>Media</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('imageProviders')}
                                    className="group/section-trigger relative flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-foreground"
                                >
                                    <SidebarSectionLeadingIcon icon={Layers} isOpen={isMediaProvidersOpen} />
                                    <span className="flex-1 text-left">Media</span>
                                    <SidebarCountBadge stats={sidebarStats?.media} animationIndex={4} />
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); void handleAddMediaProviderBinding(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); void handleAddMediaProviderBinding(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add media provider"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add media provider</TooltipContent>
                                        </Tooltip>
                                    )}
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {visibleMediaProvidersLoading ? (
                                        <SidebarMenu>
                                            <SidebarItemSkeleton testId="agent-sidebar-media-skeleton" />
                                        </SidebarMenu>
                                    ) : imageProvidersLoading ? null : imageProviderBindings.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={() => { void handleAddMediaProviderBinding(); }}
                                                disabled={!agent?.id}
                                                className="justify-center text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                            >
                                                <Plus className="size-3.5" />
                                                Add first media provider
                                            </SidebarMenuButton>
                                        </div>
                                    ) : (
                                        <SidebarMenu>
                                            {imageProviderBindings.map((binding) => (
                                                <SidebarMenuItem key={binding.id} className="group/item">
                                                    <Tooltip>
                                                        <TooltipTrigger asChild>
                                                            <SidebarMenuButton
                                                                size="sm"
                                                                onClick={() => void handleEditMediaProviderBinding(binding.id)}
                                                                className="pl-3 text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                                                            >
                                                                <MediaProviderBadge
                                                                    name={binding.providerName}
                                                                    logoUrl={imageProviderLogoUrlByKey[binding.providerKey] ?? null}
                                                                    className="w-4 shrink-0 justify-center"
                                                                    textClassName="hidden"
                                                                />
                                                                <span className="truncate flex-1">{binding.providerName}</span>
                                                                <span className="text-[9px] px-1 rounded border border-sidebar-border/60 text-sidebar-foreground/50 shrink-0">
                                                                    {binding.mediaType === 'video' ? 'vid' : 'img'}
                                                                </span>
                                                                <span className="text-[9px] px-1 rounded border border-sidebar-border/60 text-sidebar-foreground/50 shrink-0">
                                                                    {binding.providerVisibility === 'extension' ? 'ext' : 'core'}
                                                                </span>
                                                                <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                    {binding.effectiveEnabled ? 'on' : 'off'}
                                                                </span>
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <p className="font-semibold">{binding.providerName}</p>
                                                                <p className="text-xs text-muted-foreground">
                                                                    {binding.mediaType} · {formatProviderVisibilityLabel(binding.providerVisibility)} · {binding.providerKey} · {formatChannelStatus(binding.lastHealthStatus)}
                                                                </p>
                                                                {binding.providerExtensionLabel ? (
                                                                    <p className="text-xs text-muted-foreground">
                                                                        {binding.providerExtensionLabel}
                                                                    </p>
                                                                ) : null}
                                                                {binding.disabledReason ? (
                                                                    <p className="text-xs text-muted-foreground">
                                                                        {binding.disabledReason}
                                                                    </p>
                                                                ) : null}
                                                            </div>
                                                        </TooltipContent>
                                                    </Tooltip>
                                                    <SidebarMenuAction
                                                        showOnHover
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            void handleDeleteMediaProviderBinding(binding.id);
                                                        }}
                                                        className="hover:bg-destructive/10 hover:text-destructive"
                                                    >
                                                        <X className="size-3.5" />
                                                        <span className="sr-only">Delete media provider</span>
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
                                    className="group/section-trigger relative flex w-full items-center gap-2 rounded-md py-1.5 pl-7 pr-2 text-xs font-medium text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-foreground"
                                >
                                    <SidebarSectionLeadingIcon icon={Globe} isOpen={isWebSearchOpen} />
                                    <span className="flex-1 text-left">Web Search</span>
                                    <SidebarCountBadge stats={sidebarStats?.web_search} animationIndex={5} />
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); void handleAddWebSearchBinding(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); void handleAddWebSearchBinding(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add web search provider"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add web search provider</TooltipContent>
                                        </Tooltip>
                                    )}
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {visibleWebSearchLoading ? (
                                        <SidebarMenu>
                                            <SidebarItemSkeleton testId="agent-sidebar-web-search-skeleton" />
                                        </SidebarMenu>
                                    ) : webSearchLoading ? null : webSearchBindings.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={() => { void handleAddWebSearchBinding(); }}
                                                disabled={!agent?.id}
                                                className="justify-center text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                                            >
                                                <Plus className="size-3.5" />
                                                Add first web search
                                            </SidebarMenuButton>
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
                                                                <WebSearchProviderBadge
                                                                    name={binding.providerName}
                                                                    logoUrl={webSearchLogoUrlByKey[binding.providerKey] ?? null}
                                                                    className="w-4 shrink-0 justify-center"
                                                                    textClassName="hidden"
                                                                />
                                                                <span className="truncate flex-1">{binding.providerName}</span>
                                                                <span className="text-[9px] px-1 rounded border border-sidebar-border/60 text-sidebar-foreground/50 shrink-0">
                                                                    {binding.providerVisibility === 'extension' ? 'ext' : 'core'}
                                                                </span>
                                                                <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                    {binding.effectiveEnabled ? 'on' : 'off'}
                                                                </span>
                                                            </SidebarMenuButton>
                                                        </TooltipTrigger>
                                                        <TooltipContent side="right" className="max-w-xs">
                                                            <div className="space-y-1">
                                                                <p className="font-semibold">{binding.providerName}</p>
                                                                <p className="text-xs text-muted-foreground">
                                                                    {formatProviderVisibilityLabel(binding.providerVisibility)} · {binding.providerKey} · {formatChannelStatus(binding.lastHealthStatus)}
                                                                </p>
                                                                {binding.providerExtensionLabel ? (
                                                                    <p className="text-xs text-muted-foreground">
                                                                        {binding.providerExtensionLabel}
                                                                    </p>
                                                                ) : null}
                                                                {binding.disabledReason ? (
                                                                    <p className="text-xs text-muted-foreground">
                                                                        {binding.disabledReason}
                                                                    </p>
                                                                ) : null}
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

                {/* Rail for collapse/expand toggle */}
                <SidebarRail />
            </Sidebar>

            {/* Edit Agent Modal */}
            <AgentModal
                isOpen={isEditModalOpen}
                mode="edit"
                agentId={agent?.id}
                creatorUserId={agent?.created_by_user_id}
                initialData={
                    agent
                        ? {
                            name: agent.name,
                            description: agent.description,
                            llm_id: agent.llm_id,
                            session_idle_timeout_minutes:
                                agent.session_idle_timeout_minutes,
                            sandbox_timeout_seconds:
                                agent.sandbox_timeout_seconds,
                            compact_threshold_percent:
                                agent.compact_threshold_percent,
                            max_iteration: agent.max_iteration,
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
                    extensionTools={extensionTools.map((tool) => ({
                        name: tool.name,
                        description: tool.description,
                        extensionLabel: tool.extensionLabel ?? null,
                    }))}
                    onSaved={stageToolIds}
                />
            )}

            {/* Skill Selector Dialog */}
            {agent?.id && (
                <SkillSelectorDialog
                    open={isSkillSelectorOpen}
                    onOpenChange={setIsSkillSelectorOpen}
                    agentId={agent.id}
                    currentSkillIds={localSkillIds}
                    extensionSkills={extensionSkills.map((skill) => ({
                        name: skill.name,
                        description: skill.description,
                        extensionLabel: skill.extensionLabel ?? null,
                    }))}
                    onSaved={stageSkillIds}
                />
            )}

            {/* Channel Binding Dialog */}
            {agent?.id && (
                <ExtensionBindingDialog
                    open={isExtensionDialogOpen}
                    onOpenChange={setIsExtensionDialogOpen}
                    agentId={agent.id}
                    packages={extensionPackages}
                    initialPackage={editingExtensionPackage}
                    onSaved={async () => {
                        await loadSidebarStats();
                        await Promise.all([
                            loadExtensionPackages(true),
                            hasFetchedChannelsRef.current ? loadChannels(true) : Promise.resolve(),
                            hasFetchedMediaProvidersRef.current
                                ? loadMediaProviderBindings(true)
                                : Promise.resolve(),
                            hasFetchedWebSearchRef.current
                                ? loadWebSearchBindings(true)
                                : Promise.resolve(),
                        ]);
                        await onExtensionBindingsChanged?.();
                    }}
                />
            )}

            {agent?.id && (
                <ChannelBindingDialog
                    open={isChannelDialogOpen}
                    onOpenChange={setIsChannelDialogOpen}
                    agentId={agent.id}
                    catalog={channelCatalog}
                    initialBinding={editingChannel}
                    onSaved={async () => {
                        await Promise.all([
                            loadChannels(true),
                            loadSidebarStats(),
                        ]);
                        await onChannelBindingsChanged?.();
                    }}
                />
            )}

            {/* Web Search Binding Dialog */}
            {agent?.id && (
                <MediaGenerationBindingDialog
                    open={isMediaProviderDialogOpen}
                    onOpenChange={setIsMediaProviderDialogOpen}
                    agentId={agent.id}
                    catalog={imageProviderCatalog}
                    configuredProviderKeys={imageProviderBindings.map((binding) => binding.providerKey)}
                    initialBinding={editingMediaProviderBinding}
                    onSaved={async () => {
                        await Promise.all([
                            loadMediaProviderBindings(true),
                            loadSidebarStats(),
                        ]);
                        await onMediaProviderBindingsChanged?.();
                    }}
                />
            )}

            {agent?.id && (
                <WebSearchBindingDialog
                    open={isWebSearchDialogOpen}
                    onOpenChange={setIsWebSearchDialogOpen}
                    agentId={agent.id}
                    catalog={webSearchCatalog}
                    configuredProviderKeys={webSearchBindings.map((binding) => binding.providerKey)}
                    initialBinding={editingWebSearchBinding}
                    onSaved={async () => {
                        await Promise.all([
                            loadWebSearchBindings(true),
                            loadSidebarStats(),
                        ]);
                        await onWebSearchBindingsChanged?.();
                    }}
                />
            )}

            <ConfirmationModal
                isOpen={isDeleteExtensionDialogOpen}
                title="Remove Extension?"
                message={formatExtensionRemovalMessage(deletingExtensionPackage)}
                confirmText="Remove"
                cancelText="Cancel"
                onConfirm={() => {
                    void handleConfirmDeleteExtension();
                }}
                onCancel={() => {
                    setIsDeleteExtensionDialogOpen(false);
                    setDeletingExtensionPackage(null);
                }}
                variant="danger"
            />
        </>
    );
}

export default AgentDetailSidebar;
