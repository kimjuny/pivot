import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
    Bot,
    ChevronDown,
    Layers,
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
    getSharedTools,
    getPrivateTools,
    getSharedSkills,
    getPrivateSkills,
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
    type AgentExtensionPackage,
    type SharedTool,
    type PrivateTool,
    type SkillSource,
    type SharedSkill,
    type UserSkill,
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
    kind: 'shared' | 'private';
    source: 'builtin' | 'user' | 'extension';
    extensionLabel?: string | null;
    readOnly: boolean;
}

/** Unified skill entry for sidebar display. */
interface SidebarSkill {
    name: string;
    description: string;
    kind: 'shared' | 'private';
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
 * Why: shared/private tools can have the same name, so name alone collides.
 */
function buildToolResourceId(tool: SidebarTool): string {
    return `${tool.kind}:${tool.name}`;
}

/**
 * Build a unique resource ID for skill tabs.
 * Why: shared/private descriptors may share names across saved UI tabs.
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
    const [isToolsOpen, setIsToolsOpen] = useState(true);
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
    const hasFetchedToolsRef = useRef(false);
    const hasFetchedSkillsRef = useRef(false);
    const latestAgentIdRef = useRef<number | null>(agent?.id ?? null);
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
        setEditingChannel(null);
        setEditingMediaProviderBinding(null);
        setEditingWebSearchBinding(null);
        setEditingExtensionPackage(null);
        setDeletingExtensionPackage(null);
        setIsChannelDialogOpen(false);
        setIsMediaProviderDialogOpen(false);
        setIsWebSearchDialogOpen(false);
        setIsExtensionDialogOpen(false);
        setIsDeleteExtensionDialogOpen(false);
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
                    kind: 'shared' as const,
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
                    kind: 'shared' as const,
                    source: 'extension' as const,
                    extensionLabel: pkg.display_name,
                    creator: null,
                    readOnly: true,
                }));
        }),
        [extensionPackages]
    );

    const displayedTools = useMemo(() => {
        const baseTools = enabledToolNameSet === null
            ? tools
            : tools.filter((tool) => enabledToolNameSet.has(tool.name));
        if (enabledToolNameSet === null) {
            return [...baseTools, ...extensionTools];
        }
        return [...baseTools, ...extensionTools];
    }, [tools, extensionTools, enabledToolNameSet]);

    const enabledCount = useMemo(() => {
        if (enabledToolNameSet === null) {
            return tools.length + extensionTools.length;
        }
        return displayedTools.length;
    }, [tools.length, extensionTools.length, displayedTools.length, enabledToolNameSet]);

    /**
     * Sidebar should display skills that are currently configured for this
     * agent, instead of the global skill catalog.
     */
    const displayedSkills = useMemo(() => {
        const baseSkills = enabledSkillNameSet === null
            ? skills
            : skills.filter((skill) => enabledSkillNameSet.has(skill.name));
        if (enabledSkillNameSet === null) {
            return [...baseSkills, ...extensionSkills];
        }
        return [...baseSkills, ...extensionSkills];
    }, [skills, extensionSkills, enabledSkillNameSet]);

    const enabledSkillCount = useMemo(() => {
        if (enabledSkillNameSet === null) {
            return skills.length + extensionSkills.length;
        }
        return displayedSkills.length;
    }, [skills.length, extensionSkills.length, displayedSkills.length, enabledSkillNameSet]);

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
     * Fetch both shared and private user skills.
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
                        source: s.source,
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
     * Agent-scoped provider catalogs depend on which extensions are installed
     * and enabled for the current agent, so reload them with the agent context.
     */
    const loadChannelCatalog = useCallback(async () => {
        const requestedAgentId = agent?.id;
        try {
            const catalog = await getChannels(requestedAgentId);
            if (latestAgentIdRef.current !== (requestedAgentId ?? null)) {
                return;
            }
            setChannelCatalog(catalog);
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch channel catalog:', error);
            toast.error('Failed to load channels');
        }
    }, [agent?.id]);

    const loadMediaProviderCatalog = useCallback(async () => {
        const requestedAgentId = agent?.id;
        try {
            const catalog = await getMediaGenerationProviders(requestedAgentId);
            if (latestAgentIdRef.current !== (requestedAgentId ?? null)) {
                return;
            }
            setMediaProviderCatalog(catalog);
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch media provider catalog:', error);
            toast.error('Failed to load media providers');
        }
    }, [agent?.id]);

    const loadWebSearchCatalog = useCallback(async () => {
        const requestedAgentId = agent?.id;
        try {
            const catalog = await getWebSearchProviders(requestedAgentId);
            if (latestAgentIdRef.current !== (requestedAgentId ?? null)) {
                return;
            }
            setWebSearchCatalog(catalog);
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch web search catalog:', error);
            toast.error('Failed to load web search providers');
        }
    }, [agent?.id]);

    useEffect(() => {
        void loadChannelCatalog();
    }, [loadChannelCatalog]);

    useEffect(() => {
        void loadMediaProviderCatalog();
    }, [loadMediaProviderCatalog]);

    useEffect(() => {
        void loadWebSearchCatalog();
    }, [loadWebSearchCatalog]);

    /**
     * Channel bindings are agent-specific, so reload them whenever the current
     * agent changes or after any binding mutation.
     */
    const loadChannels = useCallback(async () => {
        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setChannels([]);
            return;
        }

        setChannelsLoading(true);
        try {
            const bindings = await getAgentChannels(requestedAgentId);
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
            setChannels(nextBindings);
            onChannelBindingsLoaded?.(nextBindings);
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch channel bindings:', error);
            toast.error('Failed to load agent channels');
        } finally {
            if (latestAgentIdRef.current === requestedAgentId) {
                setChannelsLoading(false);
            }
        }
    }, [agent?.id, onChannelBindingsLoaded]);

    useEffect(() => {
        void loadChannels();
    }, [loadChannels]);

    /**
     * Media-provider bindings are agent-specific, so reload them whenever the
     * current agent changes or after any binding mutation.
     */
    const loadMediaProviderBindings = useCallback(async () => {
        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setMediaProviderBindings([]);
            return;
        }

        setMediaProvidersLoading(true);
        try {
            const bindings = await getAgentMediaProviderBindings(requestedAgentId);
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
            setMediaProviderBindings(nextBindings);
            onMediaProviderBindingsLoaded?.(nextBindings);
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch media provider bindings:', error);
            toast.error('Failed to load media providers');
        } finally {
            if (latestAgentIdRef.current === requestedAgentId) {
                setMediaProvidersLoading(false);
            }
        }
    }, [agent?.id, onMediaProviderBindingsLoaded]);

    useEffect(() => {
        void loadMediaProviderBindings();
    }, [loadMediaProviderBindings]);

    /**
     * Web-search bindings are agent-specific, so reload them whenever the
     * current agent changes or after any binding mutation.
     */
    const loadWebSearchBindings = useCallback(async () => {
        const requestedAgentId = agent?.id ?? null;
        if (!requestedAgentId) {
            setWebSearchBindings([]);
            return;
        }

        setWebSearchLoading(true);
        try {
            const bindings = await getAgentWebSearchBindings(requestedAgentId);
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
            setWebSearchBindings(nextBindings);
            onWebSearchBindingsLoaded?.(nextBindings);
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            console.error('Failed to fetch web search bindings:', error);
            toast.error('Failed to load web search providers');
        } finally {
            if (latestAgentIdRef.current === requestedAgentId) {
                setWebSearchLoading(false);
            }
        }
    }, [agent?.id, onWebSearchBindingsLoaded]);

    useEffect(() => {
        void loadWebSearchBindings();
    }, [loadWebSearchBindings]);

    const handleEditAgent = (data: AgentFormData): Promise<void> => {
        if (!agent) {
            return Promise.resolve();
        }

        try {
            if (onAgentDraftUpdate) {
                onAgentDraftUpdate({ ...agent, ...data });
            }
            toast.success('Agent changes staged in draft');
            return Promise.resolve();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(`Failed to update agent: ${error.message}`);
            return Promise.reject(error);
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
        if (skill.source === 'extension') {
            return;
        }
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
            await onChannelBindingsChanged?.();
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
     * Open the media-provider binding dialog in create mode.
     */
    const handleAddMediaProviderBinding = () => {
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
            await loadMediaProviderBindings();
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
            await loadWebSearchBindings();
            await onWebSearchBindingsChanged?.();
        } catch (err) {
            const error = err instanceof Error ? err : new Error(String(err));
            toast.error(error.message);
        }
    };

    /**
     * Extension bindings are package-scoped selections, so reload them whenever
     * the current agent changes or after any extension mutation.
     */
    const loadExtensionPackages = useCallback(async () => {
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
            setExtensionPackages(packages);
        } catch (err) {
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
        void loadExtensionPackages();
    }, [loadExtensionPackages]);

    /**
     * Open the extension dialog in create mode.
     */
    const handleAddExtension = () => {
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
            await loadExtensionPackages();
            await Promise.all([
                loadChannelCatalog(),
                loadMediaProviderCatalog(),
                loadWebSearchCatalog(),
                loadChannels(),
                loadMediaProviderBindings(),
                loadWebSearchBindings(),
            ]);
            await onExtensionBindingsChanged?.();
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
                                            <span className="flex items-center gap-1 text-xs text-muted-foreground">
                                                <span
                                                    className={`h-1.5 w-1.5 rounded-full ${
                                                        agent?.serving_enabled === false
                                                            ? 'bg-amber-500'
                                                            : 'bg-success'
                                                    }`}
                                                />
                                                {agent?.serving_enabled === false ? 'Disabled' : 'Enabled'}
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
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Wrench className="size-4" />
                                    <span className="flex-1 text-left">Tools</span>
                                    {/* Count badge: shows enabled / total */}
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {toolsLoading ? '…' : enabledCount}
                                        {' / '}
                                        {toolsLoading ? '…' : tools.length + extensionTools.length}
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
                                    ) : tools.length + extensionTools.length === 0 || displayedTools.length === 0 ? (
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
                                                                {t.kind === 'private' && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        me
                                                                    </span>
                                                                )}
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
                                                                            : t.kind === 'shared'
                                                                              ? '· shared'
                                                                              : '· private'}
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
                                        {skillsLoading ? '…' : skills.length + extensionSkills.length}
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
                                    ) : skills.length + extensionSkills.length === 0 || displayedSkills.length === 0 ? (
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
                                                                {s.source === 'extension' && (
                                                                    <span className="text-[9px] px-1 rounded bg-sidebar-accent/60 text-sidebar-foreground/50 ml-1 shrink-0">
                                                                        ext
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
                                                                        {s.source === 'extension'
                                                                            ? `· extension · ${s.extensionLabel ?? 'unknown'}`
                                                                            : s.kind === 'shared'
                                                                            ? s.readOnly
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
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Server className="size-4" />
                                    <span className="flex-1 text-left">Extensions</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {extensionsLoading ? '…' : selectedExtensionPackages.length}
                                    </span>
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); handleAddExtension(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); handleAddExtension(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add extension"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add extension</TooltipContent>
                                        </Tooltip>
                                    )}
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {extensionsLoading ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            Loading extensions…
                                        </div>
                                    ) : selectedExtensionPackages.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={handleAddExtension}
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
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={handleAddChannel}
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
                                        tooltip="Media Providers"
                                        isActive={isMediaProvidersOpen}
                                        className="text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent data-[active=true]:text-sidebar-foreground data-[active=true]:bg-sidebar-accent"
                                    >
                                        <Layers className="size-4" />
                                        <span>Media Providers</span>
                                    </SidebarMenuButton>
                                </SidebarMenuItem>
                            </SidebarMenu>

                            <SidebarGroupLabel asChild className="group-data-[collapsible=icon]:hidden">
                                <CollapsibleTrigger
                                    onClick={() => handleSectionClick('imageProviders')}
                                    className="flex w-full items-center gap-2 px-2 py-1.5 text-xs font-medium text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent rounded-md transition-colors data-[state=open]:text-sidebar-foreground data-[state=open]:bg-sidebar-accent"
                                >
                                    <Layers className="size-4" />
                                    <span className="flex-1 text-left">Media Providers</span>
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-sidebar-accent/50 text-sidebar-foreground/70">
                                        {imageProvidersLoading ? '…' : imageProviderBindings.length}
                                    </span>
                                    {agent?.id && (
                                        <Tooltip>
                                            <TooltipTrigger asChild>
                                                <div
                                                    role="button"
                                                    tabIndex={0}
                                                    onClick={(e) => { e.stopPropagation(); handleAddMediaProviderBinding(); }}
                                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.stopPropagation(); handleAddMediaProviderBinding(); } }}
                                                    className="p-0.5 rounded hover:bg-sidebar-accent transition-colors cursor-pointer"
                                                    aria-label="Add media provider"
                                                >
                                                    <Plus className="size-3 text-sidebar-foreground/50 hover:text-sidebar-foreground" />
                                                </div>
                                            </TooltipTrigger>
                                            <TooltipContent side="right">Add media provider</TooltipContent>
                                        </Tooltip>
                                    )}
                                    <ChevronDown className="size-3.5 transition-transform group-data-[state=open]/collapsible:rotate-180" />
                                </CollapsibleTrigger>
                            </SidebarGroupLabel>
                            <CollapsibleContent className="group-data-[collapsible=icon]:hidden pt-1">
                                <SidebarGroupContent>
                                    {imageProvidersLoading ? (
                                        <div className="px-2 py-3 text-xs text-sidebar-foreground/50 text-center">
                                            Loading media providers…
                                        </div>
                                    ) : imageProviderBindings.length === 0 ? (
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={handleAddMediaProviderBinding}
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
                                        <div className="mx-2 my-1 rounded-md border border-dashed border-sidebar-border">
                                            <SidebarMenuButton
                                                size="sm"
                                                onClick={handleAddWebSearchBinding}
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
                    onSaved={(newToolIds) => {
                        setLocalToolIds(newToolIds);
                        if (onAgentDraftUpdate && agent) {
                            onAgentDraftUpdate({ ...agent, tool_ids: newToolIds });
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
                        if (onAgentDraftUpdate && agent) {
                            onAgentDraftUpdate({ ...agent, skill_ids: newSkillIds });
                        }
                    }}
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
                        await loadExtensionPackages();
                        await Promise.all([
                            loadChannelCatalog(),
                            loadMediaProviderCatalog(),
                            loadWebSearchCatalog(),
                            loadChannels(),
                            loadMediaProviderBindings(),
                            loadWebSearchBindings(),
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
                        await loadChannels();
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
                        await loadMediaProviderBindings();
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
                        await loadWebSearchBindings();
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
