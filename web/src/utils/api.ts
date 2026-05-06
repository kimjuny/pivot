import type { Agent, LLM, LLMUsable } from '../types';
import { getAuthToken, isTokenValid, AUTH_EXPIRED_EVENT } from '../contexts/auth-core';
import type {
  ChatSessionType,
  StudioTestSnapshotPayload,
} from "@/utils/agentTestSnapshot";

/**
 * Runtime API base URL override.
 * Set by the desktop adapter to run configured at build time.
 */
let runtimeApiBaseUrl: string | null = null;

/**
 * Override the API base URL at runtime.
 *
 * @param url - Full API base URL including the /api path segment
 *   (e.g. "https://pivot.example.com/api").
 */
export function setApiBaseUrl(url: string): void {
  runtimeApiBaseUrl = url;
}

/**
 * Resolve the current API base URL.
 *
 * - **Dev mode**: always returns `/api` so requests go through the Vite proxy
 *   (avoids CORS entirely for both web and desktop dev servers).
 * - **Prod mode**: prefers a runtime override (set by the Tauri desktop shell
 *   after the user configures the backend URL), then falls back to the
 *   build-time env var, then to `http://localhost:8003/api`.
 *
 * @returns The active API base URL string.
 */
export function getApiBaseUrl(): string {
  if (import.meta.env.DEV) return '/api';
  if (runtimeApiBaseUrl) return runtimeApiBaseUrl;
  return import.meta.env.VITE_API_BASE_URL || 'http://localhost:8003/api';
}

// ---------------------------------------------------------------------------
// Pluggable HTTP client
// ---------------------------------------------------------------------------

/**
 * The fetch implementation used by all API helpers.
 *
 * Defaults to the global `fetch`.  The Tauri desktop shell overrides it at
 * startup via {@link setHttpClient} so that requests are routed through the
 * native Rust HTTP plugin instead of the WebView network stack.
 */
let _fetch: typeof fetch = fetch;

/**
 * Replace the fetch implementation.
 *
 * Called once by the Tauri desktop bootstrap before React mounts.
 */
export function setHttpClient(client: typeof fetch): void {
  _fetch = client;
}

/**
 * Send an HTTP request through the currently configured client.
 *
 * Every API helper in this module (and across the codebase) should call this
 * instead of the bare `fetch` so that the Tauri HTTP plugin can intercept
 * requests when running inside the desktop shell.
 */
export function httpClient(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  return _fetch(input, init);
}

/**
 * Configuration options for API requests.
 */
interface RequestOptions {
  /** Additional headers to include in request */
  headers?: Record<string, string>;
  /** HTTP method (GET, POST, DELETE, etc.) */
  method?: string;
  /** Request body */
  body?: BodyInit | null;
  /** Whether to skip adding auth header (for login endpoint) */
  skipAuth?: boolean;
  /** Whether to skip token validation check */
  skipTokenCheck?: boolean;
}

/**
 * Supported image upload source labels.
 */
export type FileUploadSource = 'local' | 'clipboard';

/**
 * Immutable published release metadata for one agent.
 */
export interface AgentReleaseRecord {
  /** Stable backend identifier for the release row. */
  id: number;
  /** Agent-scoped release version number. */
  version: number;
  /** Optional human-written release note. */
  release_note: string | null;
  /** Audit summary rendered from the published snapshot diff. */
  change_summary: string[];
  /** Username that published this release, if known. */
  published_by: string | null;
  /** UTC timestamp when the release was created. */
  created_at: string;
}

/**
 * Persisted saved-draft metadata for one agent.
 */
export interface AgentSavedDraftInfo {
  /** UTC timestamp of the latest saved draft baseline. */
  saved_at: string;
  /** Username that last updated the saved draft, if known. */
  saved_by: string | null;
  /** Stable content hash for the normalized saved-draft snapshot. */
  snapshot_hash: string;
}

/**
 * Combined draft/release state used by the Studio toolbar and publish dialog.
 */
export interface AgentDraftState {
  /** Saved-draft metadata for the current agent. */
  saved_draft: AgentSavedDraftInfo;
  /** Latest published release, if one exists. */
  latest_release: AgentReleaseRecord | null;
  /** Whether the saved draft differs from the latest release. */
  has_publishable_changes: boolean;
  /** Summary lines describing what the next publish would contain. */
  publish_summary: string[];
  /** Most recent release records for the publish dialog. */
  release_history: AgentReleaseRecord[];
}

export interface AgentAccess {
  agent_id: number;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface AgentAccessUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface AgentAccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface AgentAccessOptions {
  users: AgentAccessUserOption[];
  groups: AgentAccessGroupOption[];
}

/**
 * Resolved storage profile state exposed by the backend.
 */
export interface StorageStatus {
  /** The profile requested by configuration or environment. */
  requested_profile: string;
  /** The profile currently active after health checks and fallback. */
  active_profile: string;
  /** Resolved object storage backend implementation name. */
  object_storage_backend: string;
  /** Resolved POSIX workspace backend implementation name. */
  posix_workspace_backend: string;
  /** Optional fallback reason when the requested profile could not be used. */
  fallback_reason: string | null;
  /** Backend-container-visible workspace root. */
  backend_workspace_root: string;
  /** External POSIX entrypoint configured for SeaweedFS-style profiles. */
  external_posix_root: string | null;
  /** Host-visible POSIX entrypoint that should expose the SeaweedFS mount. */
  external_host_posix_root: string | null;
  /** Whether the backend can currently see the configured external POSIX root. */
  external_posix_root_exists: boolean;
  /** Whether the backend can currently reach the external filer endpoint. */
  external_filer_reachable: boolean | null;
  /** Whether the configured POSIX root exposes the same namespace as the filer. */
  external_namespace_shared: boolean | null;
  /** Human-readable readiness summary for external storage diagnostics. */
  external_readiness_reason: string | null;
}

/** Error class for authentication-related errors */
export class AuthError extends Error {
  constructor(message: string = 'Authentication required') {
    super(message);
    this.name = 'AuthError';
  }
}

/**
 * Make an API request to backend server.
 * Handles common request/response logic including error handling.
 * Automatically includes auth token if available.
 * Validates token before making requests (unless skipTokenCheck is true).
 *
 * @param endpoint - API endpoint path (e.g., '/agents')
 * @param options - Request configuration options
 * @returns Promise resolving to response data
 * @throws AuthError if token is invalid or request returns 401
 * @throws Error if request fails or returns non-OK status
 */
export const apiRequest = async (endpoint: string, options: RequestOptions = {}): Promise<unknown> => {
  const url = `${getApiBaseUrl()}${endpoint}`;
  const isMultipartBody = options.body instanceof FormData;

  const headers: Record<string, string> = {
    ...options.headers,
  };
  if (!isMultipartBody && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  // Add auth header if token exists and not explicitly skipped
  if (!options.skipAuth) {
    // Check token validity before making request
    if (!options.skipTokenCheck && !isTokenValid()) {
      // Dispatch auth expired event
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Token expired or invalid. Please log in again.');
    }

    const token = getAuthToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  const config: RequestInit = {
    headers,
    ...options,
  };

  try {
    const response = await httpClient(url, config);

    // Handle 401 Unauthorized - token expired or invalid
    if (response.status === 401) {
      // Dispatch auth expired event
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    if (response.status === 204) {
      return null;
    }

    return await response.json();
  } catch (error) {
    console.error(`API request failed for ${url}:`, error);
    throw error;
  }
};

/**
 * Send one multipart form-data request to the backend.
 *
 * Why: extension bundle import and file uploads should reuse the same auth and
 * error handling path without forcing a JSON content type.
 *
 * @param endpoint - API endpoint path (e.g. '/extensions/installations/import/bundle')
 * @param formData - Multipart payload to submit
 * @returns Promise resolving to parsed JSON response data
 */
export const apiRequestFormData = async (
  endpoint: string,
  formData: FormData,
): Promise<unknown> => {
  return apiRequest(endpoint, {
    method: 'POST',
    body: formData,
  });
};

/**
 * Fetch all agents from server.
 * 
 * @returns Promise resolving to array of Agent objects
 */
export const getAgents = async (): Promise<Agent[]> => {
  return apiRequest('/agents') as Promise<Agent[]>;
};

/**
 * Fetch the resolved storage profile state for diagnostics and warning banners.
 *
 * @returns Promise resolving to the currently active storage status.
 */
export const getStorageStatus = async (): Promise<StorageStatus> => {
  return apiRequest('/system/storage-status') as Promise<StorageStatus>;
};

/**
 * Create a new agent.
 * 
 * @param agentData - Agent creation data
 * @returns Promise resolving to created Agent object
 */
export const createAgent = async (agentData: {
  name: string;
  description?: string;
  llm_id: number;
  session_idle_timeout_minutes?: number;
  sandbox_timeout_seconds?: number;
  compact_threshold_percent?: number;
  max_iteration?: number;
  is_active?: boolean;
  use_scope?: 'all' | 'selected';
  use_user_ids?: number[];
  use_group_ids?: number[];
}): Promise<Agent> => {
  return apiRequest('/agents', {
    method: 'POST',
    body: JSON.stringify(agentData),
  }) as Promise<Agent>;
};

/**
 * Update whether an agent is currently available to end users.
 *
 * @param agentId - Stable agent identifier
 * @param servingEnabled - Whether end users can currently use this agent
 * @returns Promise resolving to updated Agent object
 */
export const updateAgentServing = async (
  agentId: number,
  servingEnabled: boolean,
): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}/serving`, {
    method: 'PATCH',
    body: JSON.stringify({ serving_enabled: servingEnabled }),
  }) as Promise<Agent>;
};

export const getAgentAccess = async (agentId: number): Promise<AgentAccess> => {
  return apiRequest(`/agents/${agentId}/access`) as Promise<AgentAccess>;
};

export const getAgentAccessOptions = async (
  agentId: number,
): Promise<AgentAccessOptions> => {
  return apiRequest(`/agents/${agentId}/access-options`) as Promise<AgentAccessOptions>;
};

export const getAgentCreateAccessOptions = async (): Promise<AgentAccessOptions> => {
  return apiRequest('/agents/access-options') as Promise<AgentAccessOptions>;
};

export const updateAgentAccess = async (
  agentId: number,
  access: AgentAccess,
): Promise<AgentAccess> => {
  return apiRequest(`/agents/${agentId}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<AgentAccess>;
};

/**
 * Fetch a specific agent by ID.
 * 
 * @param agentId - Unique identifier of the agent
 * @returns Promise resolving to Agent object
 */
export const getAgentById = async (agentId: number): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}`) as Promise<Agent>;
};

/**
 * Delete an agent by ID.
 * 
 * @param agentId - Unique identifier of agent to delete
 * @returns Promise resolving when agent is deleted
 */
export const deleteAgent = async (agentId: number): Promise<void> => {
  await apiRequest(`/agents/${agentId}`, {
    method: 'DELETE',
  });
};

/**
 * Update an agent.
 * 
 * @param agentId - Unique identifier of agent
 * @param agentData - Agent update data
 * @returns Promise resolving to updated Agent object
 */
export const updateAgent = async (
  agentId: number,
  agentData: {
    name?: string;
    description?: string;
    llm_id?: number;
    session_idle_timeout_minutes?: number;
    sandbox_timeout_seconds?: number;
    compact_threshold_percent?: number;
    max_iteration?: number;
    is_active?: boolean;
    tool_ids?: string | null;
    skill_ids?: string | null;
  }
): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify(agentData),
  }) as Promise<Agent>;
};

/**
 * Fetch persisted draft/release state for one agent.
 *
 * @param agentId - Unique identifier of the agent
 * @returns Promise resolving to the toolbar draft/release state
 */
export const getAgentDraftState = async (agentId: number): Promise<AgentDraftState> => {
  return apiRequest(`/agents/${agentId}/draft-state`) as Promise<AgentDraftState>;
};

/**
 * Persist the current normalized backend state as the saved draft baseline.
 *
 * @param agentId - Unique identifier of the agent
 * @returns Promise resolving to the refreshed draft/release state
 */
export const saveAgentDraft = async (agentId: number): Promise<AgentDraftState> => {
  return apiRequest(`/agents/${agentId}/drafts/save`, {
    method: 'POST',
  }) as Promise<AgentDraftState>;
};

/**
 * Publish the current saved draft as the next immutable release.
 *
 * @param agentId - Unique identifier of the agent
 * @param releaseNote - Optional release note captured during publish
 * @returns Promise resolving to the refreshed draft/release state
 */
export const publishAgentRelease = async (
  agentId: number,
  releaseNote: string
): Promise<AgentDraftState> => {
  return apiRequest(`/agents/${agentId}/releases`, {
    method: 'POST',
    body: JSON.stringify({ release_note: releaseNote.trim() || null }),
  }) as Promise<AgentDraftState>;
};

/**
 * Update the tool allowlist for an agent.
 *
 * @param agentId - Agent ID
 * @param toolNames - Array of allowed tool names. Pass null to remove all
 *   restrictions (agent can use every tool).
 * @returns Promise resolving to the updated Agent
 */
export const updateAgentToolIds = async (
  agentId: number,
  toolNames: string[] | null
): Promise<Agent> => {
  const tool_ids = toolNames === null ? null : JSON.stringify(toolNames);
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify({ tool_ids }),
  }) as Promise<Agent>;
};

/**
 * Update the skill allowlist for an agent.
 *
 * @param agentId - Agent ID
 * @param skillNames - Array of allowed skill names. Pass null to remove all
 *   restrictions (agent can use every skill).
 * @returns Promise resolving to the updated Agent
 */
export const updateAgentSkillIds = async (
  agentId: number,
  skillNames: string[] | null
): Promise<Agent> => {
  const skill_ids = skillNames === null ? null : JSON.stringify(skillNames);
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify({ skill_ids }),
  }) as Promise<Agent>;
};

// ---------------------------------------------------------------------------
// Channels API
// ---------------------------------------------------------------------------

/**
 * One schema-driven field used by the channel binding form.
 */
export interface ChannelConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'secret' | 'textarea' | 'boolean';
  required: boolean;
  placeholder?: string | null;
  description?: string | null;
}

/**
 * Declarative manifest for one built-in channel provider.
 */
export interface ChannelManifest {
  key: string;
  name: string;
  description: string;
  icon: string;
  docs_url: string;
  transport_mode: 'webhook' | 'websocket' | 'polling';
  visibility: string;
  status: string;
  extension_name?: string | null;
  extension_version?: string | null;
  extension_display_name?: string | null;
  capabilities: string[];
  auth_schema: ChannelConfigField[];
  config_schema: ChannelConfigField[];
  setup_steps: string[];
}

/**
 * Endpoint details shown during channel setup.
 */
export interface ChannelEndpointInfo {
  label: string;
  method: string;
  url: string;
  description: string;
}

/**
 * Channel catalog row returned by the backend.
 */
export interface ChannelCatalogItem {
  manifest: ChannelManifest;
}

/**
 * Configured channel binding returned for an agent.
 */
export interface ChannelBinding {
  id: number;
  agent_id: number;
  channel_key: string;
  name: string;
  enabled: boolean;
  effective_enabled?: boolean;
  disabled_reason?: string | null;
  auth_config: Record<string, string>;
  runtime_config: Record<string, unknown>;
  manifest: ChannelManifest;
  endpoint_infos: ChannelEndpointInfo[];
  last_health_status: string | null;
  last_health_message: string | null;
  last_health_check_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Public status payload for a channel link token.
 */
export interface ChannelLinkStatus {
  token: string;
  status: string;
  provider_name: string;
  binding_name: string;
  agent_id: number;
  external_user_id: string;
  external_conversation_id: string | null;
  expires_at: string;
  used_at: string | null;
}

/**
 * Fetch the built-in channel catalog.
 */
export const getChannels = async (agentId?: number): Promise<ChannelCatalogItem[]> => {
  const query = typeof agentId === 'number' ? `?agent_id=${agentId}` : '';
  return apiRequest(`/channels${query}`) as Promise<ChannelCatalogItem[]>;
};

/**
 * Fetch a single channel manifest by key.
 */
export const getChannel = async (channelKey: string): Promise<ChannelCatalogItem> => {
  return apiRequest(`/channels/${encodeURIComponent(channelKey)}`) as Promise<ChannelCatalogItem>;
};

/**
 * Fetch all channel bindings configured for one agent.
 */
export const getAgentChannels = async (agentId: number): Promise<ChannelBinding[]> => {
  return apiRequest(`/agents/${agentId}/channels`) as Promise<ChannelBinding[]>;
};

/**
 * Create a new channel binding for an agent.
 */
export const createAgentChannel = async (
  agentId: number,
  payload: {
    channel_key: string;
    name: string;
    enabled?: boolean;
    auth_config: Record<string, unknown>;
    runtime_config: Record<string, unknown>;
  }
): Promise<ChannelBinding> => {
  return apiRequest(`/agents/${agentId}/channels`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ChannelBinding>;
};

/**
 * Update one configured channel binding.
 */
export const updateAgentChannel = async (
  bindingId: number,
  payload: {
    name?: string;
    enabled?: boolean;
    auth_config?: Record<string, unknown>;
    runtime_config?: Record<string, unknown>;
  }
): Promise<ChannelBinding> => {
  return apiRequest(`/agent-channels/${bindingId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }) as Promise<ChannelBinding>;
};

/**
 * Delete one configured channel binding.
 */
export const deleteAgentChannel = async (bindingId: number): Promise<void> => {
  await apiRequest(`/agent-channels/${bindingId}`, {
    method: 'DELETE',
  });
};

/**
 * Run one binding health check.
 */
export const testAgentChannel = async (
  bindingId: number
): Promise<{ result: { ok: boolean; status: string; message: string; endpoint_infos: ChannelEndpointInfo[] } }> => {
  return apiRequest(`/agent-channels/${bindingId}/test`, {
    method: 'POST',
  }) as Promise<{ result: { ok: boolean; status: string; message: string; endpoint_infos: ChannelEndpointInfo[] } }>;
};

/**
 * Run one provider health check against unsaved channel form values.
 */
export const testChannelDraft = async (
  channelKey: string,
  payload: {
    auth_config: Record<string, unknown>;
    runtime_config: Record<string, unknown>;
  }
): Promise<{ result: { ok: boolean; status: string; message: string; endpoint_infos: ChannelEndpointInfo[] } }> => {
  return apiRequest(`/channels/${encodeURIComponent(channelKey)}/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<{ result: { ok: boolean; status: string; message: string; endpoint_infos: ChannelEndpointInfo[] } }>;
};

/**
 * Manually poll one polling-based channel binding once.
 */
export const pollAgentChannel = async (
  bindingId: number
): Promise<{ fetched: number; next_offset: number | null; replies: Array<{ conversation_id: string; external_user_id: string | null; reply: string }> }> => {
  return apiRequest(`/agent-channels/${bindingId}/poll`, {
    method: 'POST',
  }) as Promise<{ fetched: number; next_offset: number | null; replies: Array<{ conversation_id: string; external_user_id: string | null; reply: string }> }>;
};

/**
 * Fetch the public status for a channel linking token.
 */
export const getChannelLinkStatus = async (
  token: string
): Promise<ChannelLinkStatus> => {
  return apiRequest(`/channel-link/${encodeURIComponent(token)}`, {
    skipAuth: true,
    skipTokenCheck: true,
  }) as Promise<ChannelLinkStatus>;
};

/**
 * Complete a channel link token using the current authenticated user.
 */
export const completeChannelLink = async (
  token: string
): Promise<{ status: string; message: string; pivot_user_id: number; workspace_owner: string; linked_at: string }> => {
  return apiRequest(`/channel-link/${encodeURIComponent(token)}/complete`, {
    method: 'POST',
  }) as Promise<{ status: string; message: string; pivot_user_id: number; workspace_owner: string; linked_at: string }>;
};

// ---------------------------------------------------------------------------
// Web Search API
// ---------------------------------------------------------------------------

/**
 * One schema-driven field used by the web-search provider binding form.
 */
export interface WebSearchConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'secret' | 'textarea' | 'boolean';
  required: boolean;
  placeholder?: string | null;
  description?: string | null;
}

/**
 * Declarative manifest for one built-in web-search provider.
 */
export interface WebSearchProviderManifest {
  key: string;
  name: string;
  description: string;
  docs_url: string;
  logo_url?: string | null;
  visibility: string;
  status: string;
  extension_name?: string | null;
  extension_version?: string | null;
  extension_display_name?: string | null;
  auth_schema: WebSearchConfigField[];
  config_schema: WebSearchConfigField[];
  setup_steps: string[];
  supported_parameters: string[];
}

/**
 * Web-search provider catalog row returned by the backend.
 */
export interface WebSearchCatalogItem {
  manifest: WebSearchProviderManifest;
}

/**
 * Configured web-search binding returned for an agent.
 */
export interface WebSearchBinding {
  id: number;
  agent_id: number;
  provider_key: string;
  enabled: boolean;
  effective_enabled?: boolean;
  disabled_reason?: string | null;
  auth_config: Record<string, string>;
  runtime_config: Record<string, unknown>;
  manifest: WebSearchProviderManifest;
  last_health_status: string | null;
  last_health_message: string | null;
  last_health_check_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * One schema-driven field used by the media-generation provider binding form.
 */
export interface MediaProviderConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'secret' | 'textarea' | 'boolean';
  required: boolean;
  placeholder?: string | null;
  default_value?: string | number | boolean | null;
  description?: string | null;
}

/**
 * Declarative manifest for one media-generation provider.
 */
export interface MediaProviderManifest {
  key: string;
  name: string;
  media_type: 'image' | 'video';
  description: string;
  docs_url: string;
  visibility: string;
  status: string;
  extension_name?: string | null;
  extension_version?: string | null;
  extension_display_name?: string | null;
  auth_schema: MediaProviderConfigField[];
  config_schema: MediaProviderConfigField[];
  setup_steps: string[];
  supported_operations: string[];
  supported_parameters: string[];
  capability_flags: Record<string, boolean>;
}

/**
 * Media-generation provider catalog row returned by the backend.
 */
export interface MediaProviderCatalogItem {
  manifest: MediaProviderManifest;
}

/**
 * Configured media-generation provider binding returned for an agent.
 */
export interface MediaProviderBinding {
  id: number;
  agent_id: number;
  provider_key: string;
  enabled: boolean;
  effective_enabled?: boolean;
  disabled_reason?: string | null;
  auth_config: Record<string, string>;
  runtime_config: Record<string, unknown>;
  manifest: MediaProviderManifest;
  last_health_status: string | null;
  last_health_message: string | null;
  last_health_check_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Fetch the built-in web-search provider catalog.
 */
export const getWebSearchProviders = async (agentId?: number): Promise<WebSearchCatalogItem[]> => {
  const query = typeof agentId === 'number' ? `?agent_id=${agentId}` : '';
  return apiRequest(`/web-search/providers${query}`) as Promise<WebSearchCatalogItem[]>;
};

/**
 * Fetch all web-search bindings configured for one agent.
 */
export const getAgentWebSearchBindings = async (agentId: number): Promise<WebSearchBinding[]> => {
  return apiRequest(`/agents/${agentId}/web-search`) as Promise<WebSearchBinding[]>;
};

/**
 * Create a new web-search provider binding for an agent.
 */
export const createAgentWebSearchBinding = async (
  agentId: number,
  payload: {
    provider_key: string;
    enabled?: boolean;
    auth_config: Record<string, unknown>;
    runtime_config: Record<string, unknown>;
  }
): Promise<WebSearchBinding> => {
  return apiRequest(`/agents/${agentId}/web-search`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<WebSearchBinding>;
};

/**
 * Update one configured web-search provider binding.
 */
export const updateAgentWebSearchBinding = async (
  bindingId: number,
  payload: {
    enabled?: boolean;
    auth_config?: Record<string, unknown>;
    runtime_config?: Record<string, unknown>;
  }
): Promise<WebSearchBinding> => {
  return apiRequest(`/agent-web-search/${bindingId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }) as Promise<WebSearchBinding>;
};

/**
 * Delete one configured web-search provider binding.
 */
export const deleteAgentWebSearchBinding = async (bindingId: number): Promise<void> => {
  await apiRequest(`/agent-web-search/${bindingId}`, {
    method: 'DELETE',
  });
};

/**
 * Run one saved web-search provider health check.
 */
export const testAgentWebSearchBinding = async (
  bindingId: number
): Promise<{ result: { ok: boolean; status: string; message: string } }> => {
  return apiRequest(`/agent-web-search/${bindingId}/test`, {
    method: 'POST',
  }) as Promise<{ result: { ok: boolean; status: string; message: string } }>;
};

/**
 * Run one provider health check against unsaved web-search form values.
 */
export const testWebSearchProviderDraft = async (
  providerKey: string,
  payload: {
    auth_config: Record<string, unknown>;
    runtime_config: Record<string, unknown>;
  }
): Promise<{ result: { ok: boolean; status: string; message: string } }> => {
  return apiRequest(`/web-search/providers/${encodeURIComponent(providerKey)}/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<{ result: { ok: boolean; status: string; message: string } }>;
};

/**
 * Fetch the installed media-generation provider catalog.
 */
export const getMediaGenerationProviders = async (agentId?: number): Promise<MediaProviderCatalogItem[]> => {
  const query = typeof agentId === 'number' ? `?agent_id=${agentId}` : '';
  return apiRequest(`/media-generation/providers${query}`) as Promise<MediaProviderCatalogItem[]>;
};

/**
 * Fetch all media-generation provider bindings configured for one agent.
 */
export const getAgentMediaProviderBindings = async (agentId: number): Promise<MediaProviderBinding[]> => {
  return apiRequest(`/agents/${agentId}/media-providers`) as Promise<MediaProviderBinding[]>;
};

/**
 * Create a new media-generation provider binding for an agent.
 */
export const createAgentMediaProviderBinding = async (
  agentId: number,
  payload: {
    provider_key: string;
    enabled?: boolean;
    auth_config: Record<string, unknown>;
    runtime_config: Record<string, unknown>;
  }
): Promise<MediaProviderBinding> => {
  return apiRequest(`/agents/${agentId}/media-providers`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<MediaProviderBinding>;
};

/**
 * Update one configured media-generation provider binding.
 */
export const updateAgentMediaProviderBinding = async (
  bindingId: number,
  payload: {
    enabled?: boolean;
    auth_config?: Record<string, unknown>;
    runtime_config?: Record<string, unknown>;
  }
): Promise<MediaProviderBinding> => {
  return apiRequest(`/agent-media-providers/${bindingId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }) as Promise<MediaProviderBinding>;
};

/**
 * Delete one configured media-generation provider binding.
 */
export const deleteAgentMediaProviderBinding = async (bindingId: number): Promise<void> => {
  await apiRequest(`/agent-media-providers/${bindingId}`, {
    method: 'DELETE',
  });
};

/**
 * Run one saved media-generation provider health check.
 */
export const testAgentMediaProviderBinding = async (
  bindingId: number
): Promise<{ result: { ok: boolean; status: string; message: string } }> => {
  return apiRequest(`/agent-media-providers/${bindingId}/test`, {
    method: 'POST',
  }) as Promise<{ result: { ok: boolean; status: string; message: string } }>;
};

/**
 * Run one provider health check against unsaved media-provider form values.
 */
export const testMediaProviderDraft = async (
  providerKey: string,
  payload: {
    auth_config: Record<string, unknown>;
    runtime_config: Record<string, unknown>;
  }
): Promise<{ result: { ok: boolean; status: string; message: string } }> => {
  return apiRequest(`/media-generation/providers/${encodeURIComponent(providerKey)}/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<{ result: { ok: boolean; status: string; message: string } }>;
};

// ---------------------------------------------------------------------------
// Extensions API
// ---------------------------------------------------------------------------

/**
 * Installed extension version metadata returned by the backend.
 */
export interface ExtensionInstallation {
  /** Normalized contribution names declared by this installed version. */
  contribution_summary: ExtensionContributionSummary;
  /** Operator-facing contribution entries declared by this installed version. */
  contribution_items: ExtensionContributionItem[];
  /** Persisted references that currently rely on this installation. */
  reference_summary: ExtensionReferenceSummary | null;
  /** Stable installation row id. */
  id: number;
  /** Stable package scope such as `acme`. */
  scope: string;
  /** Stable package name within the scope. */
  name: string;
  /** Canonical npm-style package id such as `@acme/providers`. */
  package_id: string;
  /** Installed package version. */
  version: string;
  /** Human-readable package title. */
  display_name: string;
  /** Package summary shown in Studio. */
  description: string;
  /** Optional package logo served by the backend. */
  logo_url: string | null;
  /** Stable manifest hash for pinning and replay. */
  manifest_hash: string;
  /** Storage backend used for the persisted package artifact. */
  artifact_storage_backend: string;
  /** Object-style key for the persisted package artifact. */
  artifact_key: string;
  /** Stable digest of the persisted package artifact bytes. */
  artifact_digest: string;
  /** Persisted package artifact size in bytes. */
  artifact_size_bytes: number;
  /** Absolute install root on disk. */
  install_root: string;
  /** Installation source such as `manual` or `bundle`. */
  source: string;
  /** Trust state such as `trusted_local` or `verified`. */
  trust_status: string;
  /** Trust provenance such as `local_import` or `official_hub`. */
  trust_source: string;
  /** Verified Hub scope when this installation came from the official Hub. */
  hub_scope: string | null;
  /** Canonical Hub package id when installed from the official Hub. */
  hub_package_id: string | null;
  /** Stable Hub-side package version identifier. */
  hub_package_version_id: string | null;
  /** Verified artifact digest returned by the official Hub. */
  hub_artifact_digest: string | null;
  /** Username that installed the package, if known. */
  installed_by: string | null;
  /** User id that owns this installation's edit grant. */
  creator_id: number | null;
  /** Resource use scope for Studio-side extension visibility. */
  use_scope: 'all' | 'selected';
  /** Whether the current user can view/use but not edit this installation. */
  read_only: boolean;
  /** Whether this installed version declares setup fields. */
  has_installation_configuration: boolean;
  /** Installation lifecycle status. Expected values currently include active and disabled. */
  status: string;
  /** UTC timestamp when the installation was created. */
  created_at: string;
  /** UTC timestamp when the installation last changed. */
  updated_at: string;
}

/**
 * Normalized contribution names declared by one extension version.
 */
export interface ExtensionContributionSummary {
  /** Optional lightweight tool names bundled in this version. */
  tools: string[];
  /** Optional lightweight skill names bundled in this version. */
  skills: string[];
  /** Lifecycle hook labels declared by this version. */
  hooks: string[];
  /** Chat surface keys declared by this version. */
  chat_surfaces?: string[];
  /** Channel provider keys contributed by this version. */
  channel_providers: string[];
  /** Image-generation provider keys contributed by this version. */
  media_providers?: string[];
  /** Web-search provider keys contributed by this version. */
  web_search_providers: string[];
}

/**
 * One operator-facing capability contributed by an extension package.
 */
export interface ExtensionContributionItem {
  /** Stable contribution type such as `hook`, `tool`, or `skill`. */
  type: string;
  /** Stable manifest key when the contribution declares one. */
  key?: string | null;
  /** Human-readable item name shown in detail views. */
  name: string;
  /** Plain-language description of what the item does. */
  description: string;
  /** Optional surface minimum width in pixels declared by the manifest. */
  min_width?: number | null;
}

/**
 * One manifest-declared extension configuration field.
 */
export interface ExtensionConfigurationField {
  /** Stable configuration key. */
  key: string;
  /** Operator-facing field label. */
  label: string;
  /** Field type such as `string`, `secret`, `number`, or `boolean`. */
  type: string;
  /** Human-readable help text for this field. */
  description: string;
  /** Whether the field must be provided. */
  required: boolean;
  /** Optional default value declared by the manifest. */
  default: unknown;
  /** Optional input placeholder. */
  placeholder: string;
}

/**
 * One configuration schema section for installation or binding scope.
 */
export interface ExtensionConfigurationSection {
  /** Fields declared for this scope. */
  fields: ExtensionConfigurationField[];
}

/**
 * Full normalized configuration schema declared by an extension package.
 */
export interface ExtensionConfigurationSchema {
  /** Setup fields configured once per installed version. */
  installation: ExtensionConfigurationSection;
  /** Future agent-level binding fields. */
  binding: ExtensionConfigurationSection;
}

/**
 * Grouped package view used by the global Extensions page.
 */
export interface ExtensionPackage {
  /** Stable package scope. */
  scope: string;
  /** Stable package name within the scope. */
  name: string;
  /** Canonical npm-style package id. */
  package_id: string;
  /** Human-readable package title. */
  display_name: string;
  /** Package summary. */
  description: string;
  /** Optional package logo resolved from the newest available installation. */
  logo_url: string | null;
  /** Root-level README rendered in the package detail overview, if present. */
  readme_markdown: string;
  /** Highest available installed version. */
  latest_version: string;
  /** Count of active installed versions. */
  active_version_count: number;
  /** Count of disabled installed versions. */
  disabled_version_count: number;
  /** Installed versions ordered newest-first. */
  versions: ExtensionInstallation[];
}

/**
 * Persisted reference counts that block physical uninstall.
 */
export interface ExtensionReferenceSummary {
  /** Direct agent-extension bindings referencing this installation. */
  extension_binding_count: number;
  /** Agent channel bindings using providers from this installation. */
  channel_binding_count: number;
  /** Agent media-provider bindings using providers from this installation. */
  media_provider_binding_count?: number;
  /** Agent web-search bindings using providers from this installation. */
  web_search_binding_count: number;
  /** Agent binding rows referencing this installation. */
  binding_count: number;
  /** Published releases that pin this installation. */
  release_count: number;
  /** Studio test snapshots that pin this installation. */
  test_snapshot_count: number;
  /** Saved drafts that pin this installation. */
  saved_draft_count: number;
}

/**
 * Trust preview shown before a local extension is installed.
 */
export interface ExtensionImportPreview {
  /** Stable package scope such as `acme`. */
  scope: string;
  /** Stable package name within the scope. */
  name: string;
  /** Canonical npm-style package id. */
  package_id: string;
  /** Package version declared in `manifest.json`. */
  version: string;
  /** Human-readable package title shown in the trust dialog. */
  display_name: string;
  /** Package summary from the manifest. */
  description: string;
  /** Import source such as `bundle`. */
  source: string;
  /** Pre-install trust state, expected to be `unverified` for local imports. */
  trust_status: string;
  /** Trust provenance such as `local_import`. */
  trust_source: string;
  /** Stable manifest hash for audit and pinning previews. */
  manifest_hash: string;
  /** Normalized contribution names discovered during preview. */
  contribution_summary: ExtensionContributionSummary;
  /** Operator-facing contribution entries discovered during preview. */
  contribution_items: ExtensionContributionItem[];
  /** Raw declared permissions from the manifest. */
  permissions: Record<string, unknown>;
  /** Existing installation row using the same package id and version, if any. */
  existing_installation_id: number | null;
  /** Lifecycle status of the existing installation, if any. */
  existing_installation_status: string | null;
  /** Whether the uploaded bundle is byte-for-byte identical to the installed version. */
  identical_to_installed: boolean;
  /** Whether replacing the installed version is allowed after explicit confirmation. */
  requires_overwrite_confirmation: boolean;
  /** Human-readable reason when overwrite is blocked. */
  overwrite_blocked_reason: string;
  /** Existing references that still rely on the installed version, if any. */
  existing_reference_summary: ExtensionReferenceSummary | null;
}

/**
 * Result returned after uninstalling one extension version.
 */
export interface ExtensionUninstallResult {
  /** Whether the uninstall was physical or logical. */
  mode: string;
  /** Reference counts observed during uninstall. */
  references: ExtensionReferenceSummary;
  /** Updated installation row when the uninstall was logical. */
  installation: ExtensionInstallation | null;
}

/**
 * Append-only packaged hook execution record exposed to Studio.
 */
export interface ExtensionHookExecution {
  /** Stable execution log id. */
  id: number;
  /** Owning session id when the task belongs to a session. */
  session_id: string | null;
  /** Owning task id. */
  task_id: string;
  /** Current trace id when the execution happened inside a recursion. */
  trace_id: string | null;
  /** Iteration index associated with the hook invocation. */
  iteration: number;
  /** Agent that executed the hook bundle. */
  agent_id: number;
  /** Pinned release id when the runtime was release-backed. */
  release_id: number | null;
  /** Canonical package id such as `@acme/providers`. */
  extension_package_id: string;
  /** Installed extension version. */
  extension_version: string;
  /** Lifecycle event name such as `task.before_start`. */
  hook_event: string;
  /** Exported callable name inside the hook module. */
  hook_callable: string;
  /** Execution status such as `succeeded` or `failed`. */
  status: string;
  /** Historical hook input recorded for replay. */
  hook_context: Record<string, unknown> | null;
  /** Structured effects returned by the hook, when available. */
  effects: Array<Record<string, unknown>> | null;
  /** Structured error payload, when available. */
  error: Record<string, unknown> | null;
  /** UTC timestamp when execution started. */
  started_at: string;
  /** UTC timestamp when execution finished. */
  finished_at: string;
  /** Total wall-clock execution time in milliseconds. */
  duration_ms: number;
}

/**
 * Safe replay result for one historical hook execution.
 */
export interface ExtensionHookReplayResult {
  /** Replayed execution record id. */
  execution_id: number;
  /** Canonical package id that was replayed. */
  extension_package_id: string;
  /** Extension version used during replay. */
  extension_version: string;
  /** Lifecycle event name that was replayed. */
  hook_event: string;
  /** Exported callable replayed from the hook module. */
  hook_callable: string;
  /** Replay status such as `succeeded` or `failed`. */
  status: string;
  /** Normalized replay effects, if replay succeeded. */
  effects: Array<Record<string, unknown>> | null;
  /** Structured replay error, if replay failed. */
  error: Record<string, unknown> | null;
  /** UTC timestamp when replay finished. */
  replayed_at: string;
}

/**
 * Configuration schema and current values for one installed extension version.
 */
export interface ExtensionInstallationConfigurationState {
  /** Stable installation row id. */
  installation_id: number;
  /** Canonical npm-style package id. */
  package_id: string;
  /** Installed extension version. */
  version: string;
  /** Declared configuration schema for installation and binding scopes. */
  configuration_schema: ExtensionConfigurationSchema;
  /** Current installation-scoped values. */
  config: Record<string, unknown>;
}

export interface ExtensionInstallationAccess {
  installation_id: number;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface ExtensionInstallationAccessUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface ExtensionInstallationAccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface ExtensionInstallationAccessOptions {
  users: ExtensionInstallationAccessUserOption[];
  groups: ExtensionInstallationAccessGroupOption[];
}

/**
 * Agent-scoped extension binding row.
 */
export interface AgentExtensionBinding {
  /** Stable binding row id. */
  id: number;
  /** Agent that owns this binding. */
  agent_id: number;
  /** Installed extension version referenced by the binding. */
  extension_installation_id: number;
  /** Whether the extension is enabled for the agent. */
  enabled: boolean;
  /** Lower numbers resolve earlier in the runtime bundle. */
  priority: number;
  /** Agent-local extension config payload. */
  config: Record<string, unknown>;
  /** UTC timestamp when the binding was created. */
  created_at: string;
  /** UTC timestamp when the binding last changed. */
  updated_at: string;
  /** Installation metadata for the selected version. */
  installation: ExtensionInstallation;
}

/**
 * Package-level extension view tailored for one agent.
 */
export interface AgentExtensionPackage {
  /** Stable package scope. */
  scope: string;
  /** Stable package name within the scope. */
  name: string;
  /** Canonical npm-style package id. */
  package_id: string;
  /** Human-readable package title. */
  display_name: string;
  /** Package summary. */
  description: string;
  /** Optional package logo resolved from the installed package. */
  logo_url: string | null;
  /** Highest installed version available for this package. */
  latest_version: string;
  /** Count of active installed versions. */
  active_version_count: number;
  /** Count of disabled installed versions. */
  disabled_version_count: number;
  /** Whether the selected version lags behind the newest installed version. */
  has_update_available: boolean;
  /** Current agent selection for this package, if any. */
  selected_binding: AgentExtensionBinding | null;
  /** Installed versions ordered newest-first. */
  versions: ExtensionInstallation[];
}

/**
 * Fetch the installed extension packages grouped by package name.
 */
export const getExtensionPackages = async (): Promise<ExtensionPackage[]> => {
  return apiRequest('/extensions/packages') as Promise<ExtensionPackage[]>;
};

/**
 * Preview one extension package folder bundle before installation.
 *
 * @param files - Files returned by a directory picker input.
 * @returns Promise resolving to the trust preview shown before install.
 */
export const previewExtensionBundle = async (
  files: File[],
): Promise<ExtensionImportPreview> => {
  if (files.length === 0) {
    throw new Error('Choose an extension folder before importing.');
  }

  const bundleName =
    files[0]?.webkitRelativePath.split('/')[0]?.trim() || files[0]?.name || 'extension-bundle';
  const formData = new FormData();
  formData.append('bundle_name', bundleName);
  files.forEach((file) => {
    formData.append('files', file);
    formData.append('relative_paths', file.webkitRelativePath || file.name);
  });

  return apiRequestFormData(
    '/extensions/installations/import/bundle/preview',
    formData,
  ) as Promise<ExtensionImportPreview>;
};

/**
 * Import one extension package folder bundle selected from the local machine.
 *
 * @param files - Files returned by a directory picker input.
 * @param options - Explicit trust confirmation collected from the operator.
 * @returns Promise resolving to the installed extension version.
 */
export const importExtensionBundle = async (
  files: File[],
  options: { trustConfirmed: boolean; overwriteConfirmed?: boolean },
): Promise<ExtensionInstallation> => {
  if (files.length === 0) {
    throw new Error('Choose an extension folder before importing.');
  }

  const bundleName =
    files[0]?.webkitRelativePath.split('/')[0]?.trim() || files[0]?.name || 'extension-bundle';
  const formData = new FormData();
  formData.append('bundle_name', bundleName);
  formData.append('trust_confirmed', options.trustConfirmed ? 'true' : 'false');
  formData.append('overwrite_confirmed', options.overwriteConfirmed ? 'true' : 'false');
  files.forEach((file) => {
    formData.append('files', file);
    formData.append('relative_paths', file.webkitRelativePath || file.name);
  });

  return apiRequestFormData(
    '/extensions/installations/import/bundle',
    formData,
  ) as Promise<ExtensionInstallation>;
};

/**
 * Enable or disable one installed extension version.
 */
export const updateExtensionInstallationStatus = async (
  installationId: number,
  status: 'active' | 'disabled',
): Promise<ExtensionInstallation> => {
  return apiRequest(`/extensions/installations/${installationId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  }) as Promise<ExtensionInstallation>;
};

/**
 * Fetch persisted reference counts for one installed extension version.
 */
export const getExtensionInstallationReferences = async (
  installationId: number,
): Promise<ExtensionReferenceSummary> => {
  return apiRequest(
    `/extensions/installations/${installationId}/references`,
  ) as Promise<ExtensionReferenceSummary>;
};

/**
 * Uninstall one installed extension version.
 */
export const uninstallExtensionInstallation = async (
  installationId: number,
): Promise<ExtensionUninstallResult> => {
  return apiRequest(`/extensions/installations/${installationId}`, {
    method: 'DELETE',
  }) as Promise<ExtensionUninstallResult>;
};

export const getExtensionInstallationAccess = async (
  installationId: number,
): Promise<ExtensionInstallationAccess> => {
  return apiRequest(
    `/extensions/installations/${installationId}/access`,
  ) as Promise<ExtensionInstallationAccess>;
};

export const getExtensionInstallationAccessOptions = async (
  installationId: number,
): Promise<ExtensionInstallationAccessOptions> => {
  return apiRequest(
    `/extensions/installations/${installationId}/access-options`,
  ) as Promise<ExtensionInstallationAccessOptions>;
};

export const updateExtensionInstallationAccess = async (
  installationId: number,
  access: Omit<ExtensionInstallationAccess, 'installation_id'>,
): Promise<ExtensionInstallationAccess> => {
  return apiRequest(`/extensions/installations/${installationId}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<ExtensionInstallationAccess>;
};

/**
 * Fetch setup schema and current installation-scoped values for one version.
 */
export const getExtensionInstallationConfiguration = async (
  installationId: number,
): Promise<ExtensionInstallationConfigurationState> => {
  return apiRequest(
    `/extensions/installations/${installationId}/configuration`,
  ) as Promise<ExtensionInstallationConfigurationState>;
};

/**
 * Save installation-scoped setup values for one version.
 */
export const updateExtensionInstallationConfiguration = async (
  installationId: number,
  config: Record<string, unknown>,
): Promise<ExtensionInstallationConfigurationState> => {
  return apiRequest(`/extensions/installations/${installationId}/configuration`, {
    method: 'PUT',
    body: JSON.stringify({ config }),
  }) as Promise<ExtensionInstallationConfigurationState>;
};

/**
 * Fetch recent packaged hook execution logs.
 */
export const getExtensionHookExecutions = async (filters?: {
  sessionId?: string;
  taskId?: string;
  traceId?: string;
  iteration?: number;
  extensionPackageId?: string;
  hookEvent?: string;
  limit?: number;
}): Promise<ExtensionHookExecution[]> => {
  const params = new URLSearchParams();
  if (filters?.sessionId) {
    params.set('session_id', filters.sessionId);
  }
  if (filters?.taskId) {
    params.set('task_id', filters.taskId);
  }
  if (filters?.traceId) {
    params.set('trace_id', filters.traceId);
  }
  if (typeof filters?.iteration === 'number') {
    params.set('iteration', String(filters.iteration));
  }
  if (filters?.extensionPackageId) {
    params.set('extension_package_id', filters.extensionPackageId);
  }
  if (filters?.hookEvent) {
    params.set('hook_event', filters.hookEvent);
  }
  if (typeof filters?.limit === 'number') {
    params.set('limit', String(filters.limit));
  }
  const query = params.toString();
  return apiRequest(
    `/extensions/hook-executions${query ? `?${query}` : ''}`,
  ) as Promise<ExtensionHookExecution[]>;
};

/**
 * Safely replay one historical packaged hook execution.
 */
export const replayExtensionHookExecution = async (
  executionId: number,
): Promise<ExtensionHookReplayResult> => {
  return apiRequest(`/extensions/hook-executions/${executionId}/replay`, {
    method: 'POST',
  }) as Promise<ExtensionHookReplayResult>;
};

/**
 * Fetch package-level extension choices for one agent.
 */
export const getAgentExtensionPackages = async (
  agentId: number,
): Promise<AgentExtensionPackage[]> => {
  return apiRequest(
    `/agents/${agentId}/extensions/packages`,
  ) as Promise<AgentExtensionPackage[]>;
};

/**
 * Create or update one extension binding for an agent.
 */
export const upsertAgentExtensionBinding = async (
  agentId: number,
  extensionInstallationId: number,
  payload: {
    enabled?: boolean;
    priority?: number;
    config?: Record<string, unknown>;
  },
): Promise<AgentExtensionBinding> => {
  return apiRequest(
    `/agents/${agentId}/extensions/${extensionInstallationId}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
  ) as Promise<AgentExtensionBinding>;
};

/**
 * Replace the full extension binding set for one agent.
 */
export const replaceAgentExtensionBindings = async (
  agentId: number,
  bindings: Array<{
    extension_installation_id: number;
    enabled: boolean;
    priority: number;
    config: Record<string, unknown>;
  }>,
): Promise<AgentExtensionBinding[]> => {
  return apiRequest(`/agents/${agentId}/extensions`, {
    method: 'PUT',
    body: JSON.stringify({ bindings }),
  }) as Promise<AgentExtensionBinding[]>;
};

/**
 * Delete one extension binding from an agent.
 */
export const deleteAgentExtensionBinding = async (
  agentId: number,
  extensionInstallationId: number,
): Promise<void> => {
  await apiRequest(`/agents/${agentId}/extensions/${extensionInstallationId}`, {
    method: 'DELETE',
  });
};

/**
 * Get all available LLM models.
 * 
 * @returns Promise resolving to list of available model names
 */
export const getModels = async (): Promise<string[]> => {
  const response = await apiRequest('/models') as { models: string[]; count: number };
  return response.models;
};

/**
 * Tool metadata interface.
 */
export interface Tool {
  /** Tool name */
  name: string;
  /** Tool description */
  description: string;
  /** Tool parameters schema */
  parameters: {
    type: string;
    properties: Record<string, unknown>;
    required?: string[];
  };
}

/**
 * Get all registered tools.
 * 
 * @returns Promise resolving to list of tool metadata
 */
export const getTools = async (): Promise<Tool[]> => {
  return apiRequest('/tools') as Promise<Tool[]>;
};

/**
 * Fetch all LLMs from server.
 * 
 * @returns Promise resolving to array of LLM objects
 */
export const getLLMs = async (): Promise<LLM[]> => {
  return apiRequest('/llms') as Promise<LLM[]>;
};

/**
 * Fetch LLM options the current Studio user can select when configuring agents.
 * The response intentionally excludes provider secrets and endpoint settings.
 */
export const getUsableLLMs = async (): Promise<LLMUsable[]> => {
  return apiRequest('/llms/usable') as Promise<LLMUsable[]>;
};

/**
 * Create a new LLM.
 * 
 * @param llmData - LLM creation data
 * @returns Promise resolving to created LLM object
 */
export const createLLM = async (llmData: {
  name: string;
  endpoint: string;
  model: string;
  api_key: string;
  protocol?: string;
  cache_policy?: string;
  thinking_policy?: string;
  thinking_effort?: string | null;
  thinking_budget_tokens?: number | null;
  streaming?: boolean;
  image_input?: boolean;
  image_output?: boolean;
  max_context?: number;
  extra_config?: string;
  use_scope?: 'all' | 'selected';
  use_user_ids?: number[];
  use_group_ids?: number[];
  edit_user_ids?: number[];
  edit_group_ids?: number[];
}): Promise<LLM> => {
  return apiRequest('/llms', {
    method: 'POST',
    body: JSON.stringify(llmData),
  }) as Promise<LLM>;
};

/**
 * Fetch a specific LLM by ID.
 * 
 * @param llmId - Unique identifier of the LLM
 * @returns Promise resolving to LLM object
 */
export const getLLMById = async (llmId: number): Promise<LLM> => {
  return apiRequest(`/llms/${llmId}`) as Promise<LLM>;
};

export interface LLMAccess {
  llm_id: number;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface LLMAccessUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface LLMAccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface LLMAccessOptions {
  users: LLMAccessUserOption[];
  groups: LLMAccessGroupOption[];
}

export const getLLMAccess = async (llmId: number): Promise<LLMAccess> => {
  return apiRequest(`/llms/${llmId}/access`) as Promise<LLMAccess>;
};

export const getLLMAccessOptions = async (
  llmId: number,
): Promise<LLMAccessOptions> => {
  return apiRequest(`/llms/${llmId}/access-options`) as Promise<LLMAccessOptions>;
};

export const getLLMCreateAccessOptions = async (): Promise<LLMAccessOptions> => {
  return apiRequest('/llms/access-options') as Promise<LLMAccessOptions>;
};

export const updateLLMAccess = async (
  llmId: number,
  access: Omit<LLMAccess, 'llm_id'>,
): Promise<LLMAccess> => {
  return apiRequest(`/llms/${llmId}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_user_ids: access.use_user_ids,
      use_scope: access.use_scope,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<LLMAccess>;
};

/**
 * Update an LLM.
 * 
 * @param llmId - Unique identifier of LLM
 * @param llmData - LLM update data
 * @returns Promise resolving to updated LLM object
 */
export const updateLLM = async (
  llmId: number,
  llmData: {
    name?: string;
    endpoint?: string;
    model?: string;
    api_key?: string;
    protocol?: string;
    cache_policy?: string;
    thinking_policy?: string;
    thinking_effort?: string | null;
    thinking_budget_tokens?: number | null;
    streaming?: boolean;
    image_input?: boolean;
    image_output?: boolean;
    max_context?: number;
    extra_config?: string;
  }
): Promise<LLM> => {
  return apiRequest(`/llms/${llmId}`, {
    method: 'PUT',
    body: JSON.stringify(llmData),
  }) as Promise<LLM>;
};

/**
 * Delete an LLM by ID.
 *
 * @param llmId - Unique identifier of LLM to delete
 * @returns Promise resolving when LLM is deleted
 */
export const deleteLLM = async (llmId: number): Promise<void> => {
  await apiRequest(`/llms/${llmId}`, {
    method: 'DELETE',
  });
};

// ============================================
// Session API Functions
// ============================================

/**
 * Project record from API.
 */
export interface ProjectResponse {
  id: number;
  project_id: string;
  agent_id: number;
  name: string;
  description: string | null;
  workspace_id: string;
  can_edit: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectAccess {
  project_id: string;
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface ProjectAccessUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface ProjectAccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface ProjectAccessOptions {
  users: ProjectAccessUserOption[];
  groups: ProjectAccessGroupOption[];
}

/**
 * Project list response from API.
 */
export interface ProjectListResponse {
  projects: ProjectResponse[];
  total: number;
}

/**
 * Session list item from API.
 */
export interface SessionListItem {
  session_id: string;
  agent_id: number;
  type?: ChatSessionType;
  release_id?: number | null;
  project_id?: string | null;
  workspace_id?: string | null;
  workspace_scope?: "session_private" | "project_shared" | null;
  test_workspace_hash?: string | null;
  status: string;
  runtime_status?: "idle" | "running" | "waiting_input";
  title: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Session list response from API.
 */
export interface SessionListResponse {
  sessions: SessionListItem[];
  total: number;
}

/**
 * Session response from API.
 */
export interface SessionResponse {
  id: number;
  session_id: string;
  agent_id: number;
  type?: ChatSessionType;
  release_id?: number | null;
  project_id?: string | null;
  workspace_id?: string | null;
  workspace_scope?: "session_private" | "project_shared" | null;
  test_workspace_hash?: string | null;
  user: string;
  status: string;
  runtime_status?: "idle" | "running" | "waiting_input";
  title: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Create a new conversation session.
 *
 * @param agentId - Agent ID for the session
 * @returns Promise resolving to created session
 */
export const createSession = async (
  agentId: number,
  options?: {
    projectId?: string | null;
    type?: ChatSessionType;
    testSnapshot?: StudioTestSnapshotPayload | null;
  },
): Promise<SessionResponse> => {
  return apiRequest('/sessions', {
    method: 'POST',
    body: JSON.stringify({
      agent_id: agentId,
      project_id: options?.projectId ?? null,
      type: options?.type ?? 'consumer',
      test_snapshot: options?.testSnapshot ?? null,
    }),
  }) as Promise<SessionResponse>;
};

/**
 * List projects for one agent.
 *
 * @param agentId - Agent ID whose projects should be fetched
 * @returns Promise resolving to the user's projects for that agent
 */
export const listProjects = async (
  agentId: number,
): Promise<ProjectListResponse> => {
  return apiRequest(`/projects?agent_id=${agentId}`) as Promise<ProjectListResponse>;
};

/**
 * Create a new project for one agent.
 *
 * @param payload - Project creation metadata
 * @returns Promise resolving to the created project
 */
export const createProject = async (payload: {
  agent_id: number;
  name: string;
  description?: string | null;
}): Promise<ProjectResponse> => {
  return apiRequest('/projects', {
    method: 'POST',
    body: JSON.stringify({
      agent_id: payload.agent_id,
      name: payload.name,
      description: payload.description ?? null,
    }),
  }) as Promise<ProjectResponse>;
};

/**
 * Update one existing project.
 *
 * @param projectId - Public project UUID
 * @param payload - Partial metadata updates
 * @returns Promise resolving to the updated project
 */
export const updateProject = async (
  projectId: string,
  payload: {
    name?: string | null;
    description?: string | null;
  },
): Promise<ProjectResponse> => {
  return apiRequest(`/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }) as Promise<ProjectResponse>;
};

/**
 * Delete one project and its child sessions.
 *
 * @param projectId - Public project UUID
 */
export const deleteProject = async (projectId: string): Promise<void> => {
  await apiRequest(`/projects/${projectId}`, {
    method: 'DELETE',
  });
};

export const getProjectAccess = async (
  projectId: string,
): Promise<ProjectAccess> => {
  return apiRequest(`/projects/${projectId}/access`) as Promise<ProjectAccess>;
};

export const getProjectAccessOptions = async (
  projectId: string,
): Promise<ProjectAccessOptions> => {
  return apiRequest(
    `/projects/${projectId}/access-options`,
  ) as Promise<ProjectAccessOptions>;
};

export const updateProjectAccess = async (
  projectId: string,
  access: Omit<ProjectAccess, 'project_id'>,
): Promise<ProjectAccess> => {
  return apiRequest(`/projects/${projectId}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<ProjectAccess>;
};

/**
 * List sessions for the current user.
 *
 * @param agentId - Optional agent ID filter
 * @param limit - Maximum number of sessions to return
 * @returns Promise resolving to list of sessions
 */
export const listSessions = async (
  agentId?: number,
  limit: number = 50,
  options?: {
    type?: ChatSessionType;
  },
): Promise<SessionListResponse> => {
  let endpoint = `/sessions?limit=${limit}`;
  if (agentId !== undefined) {
    endpoint += `&agent_id=${agentId}`;
  }
  if (options?.type) {
    endpoint += `&session_type=${options.type}`;
  }
  return apiRequest(endpoint) as Promise<SessionListResponse>;
};

/**
 * Get a session by ID.
 *
 * @param sessionId - Session UUID
 * @returns Promise resolving to session details
 */
export const getSession = async (sessionId: string): Promise<SessionResponse> => {
  return apiRequest(`/sessions/${sessionId}`) as Promise<SessionResponse>;
};

/**
 * Update user-managed sidebar metadata for a session.
 *
 * @param sessionId - Session UUID
 * @param sessionData - Partial sidebar metadata changes
 * @returns Promise resolving to the updated session
 */
export const updateSession = async (
  sessionId: string,
  sessionData: {
    title?: string | null;
    is_pinned?: boolean;
  },
): Promise<SessionResponse> => {
  return apiRequest(`/sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify(sessionData),
  }) as Promise<SessionResponse>;
};

/**
 * Chat history message from session API.
 */
export interface SessionChatHistoryMessage {
  type: string;
  content: string;
  timestamp: string;
  files?: ChatFileAsset[];
  attachments?: TaskAttachmentAsset[];
}

/**
 * Uploaded file metadata returned by backend.
 */
export interface ChatFileAsset {
  file_id: string;
  kind: 'image' | 'document';
  source: FileUploadSource;
  original_name: string;
  mime_type: string;
  format: string;
  extension: string;
  size_bytes: number;
  width: number;
  height: number;
  page_count?: number | null;
  can_extract_text?: boolean;
  suspected_scanned?: boolean;
  text_encoding?: string | null;
  session_id: string | null;
  task_id: string | null;
  created_at: string;
  expires_at?: string;
}

/**
 * Assistant-generated attachment metadata returned by the backend.
 */
export interface TaskAttachmentAsset {
  attachment_id: string;
  display_name: string;
  original_name: string;
  mime_type: string;
  extension: string;
  size_bytes: number;
  render_kind: 'markdown' | 'pdf' | 'image' | 'text' | 'download';
  workspace_relative_path: string;
  created_at: string;
}

/**
 * Backward-compatible alias for legacy image-only call sites.
 */
export type ChatImageFile = ChatFileAsset;

/**
 * Chat history response from session API.
 */
export interface SessionChatHistoryResponse {
  version: number;
  messages: SessionChatHistoryMessage[];
}

/**
 * Delete a session.
 *
 * @param sessionId - Session UUID
 * @returns Promise resolving when session is deleted
 */
export const deleteSession = async (sessionId: string): Promise<void> => {
  await apiRequest(`/sessions/${sessionId}`, {
    method: 'DELETE',
  });
};

/**
 * Get chat history for a session.
 *
 * @param sessionId - Session UUID
 * @returns Promise resolving to chat history
 */
export const getSessionHistory = async (sessionId: string): Promise<SessionChatHistoryResponse> => {
  return apiRequest(`/sessions/${sessionId}/history`) as Promise<SessionChatHistoryResponse>;
};

/**
 * Recursion detail from full session history API.
 */
export interface RecursionDetail {
  iteration: number;
  trace_id: string;
  input_message_json: string | null;
  observe: string | null;
  thinking: string | null;
  reason: string | null;
  summary: string | null;
  action_type: string | null;
  action_output: string | null;
  tool_call_results: string | null;
  status: string;
  error_log: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_input_tokens?: number;
  created_at: string;
  updated_at: string;
}

/**
 * Compact recursion summary nested under one current-plan step.
 */
export interface CurrentPlanRecursionSummary {
  iteration?: number | null;
  summary: string;
}

/**
 * Latest persisted current-plan step returned with task history.
 */
export interface CurrentPlanStep {
  step_id: string;
  general_goal: string;
  specific_description: string;
  completion_criteria: string;
  status: string;
  recursion_history?: CurrentPlanRecursionSummary[];
}

/**
 * Task message from full session history API.
 */
export interface TaskMessage {
  task_id: string;
  user_message: string;
  files?: ChatFileAsset[];
  mandatory_skills?: Array<{
    name: string;
    path: string;
  }>;
  assistant_attachments?: TaskAttachmentAsset[];
  agent_answer: string | null;
  status: string;
  total_tokens: number;
  pending_user_action?: {
    kind: string;
    approval_request?: {
      submission_id: number;
      skill_name: string;
      change_type: string;
      question: string;
      message?: string;
      file_count?: number;
      total_bytes?: number;
    } | null;
  } | null;
  current_plan?: CurrentPlanStep[];
  recursions: RecursionDetail[];
  created_at: string;
  updated_at: string;
}

/**
 * Full session history response from API.
 */
export interface FullSessionHistoryResponse {
  session_id: string;
  last_event_id: number;
  resume_from_event_id: number;
  tasks: TaskMessage[];
}

/**
 * Response returned when a ReAct task has been queued for execution.
 */
export interface ReactTaskStartResponse {
  task_id: string;
  session_id: string | null;
  status: string;
  cursor_before_start: number;
}

/**
 * Response returned after a task cancellation request.
 */
export interface ReactTaskCancelResponse {
  task_id: string;
  status: string;
  cancel_requested: boolean;
}

/**
 * Structured decision for one waiting system-owned user action.
 */
export interface ReactPendingUserActionResponse {
  task_id: string;
  session_id: string | null;
  status: string;
  cursor_before_start: number;
}

/**
 * One runtime-visible skill option returned to the chat composer.
 */
export interface ReactRuntimeSkillItem {
  /** Stable globally unique skill name. */
  name: string;
  /** Human-readable description shown in the mention picker. */
  description: string;
  /** Canonical sandbox path visible to the runtime. */
  path: string;
}

/**
 * Prompt-context usage summary returned by the ReAct context estimator API.
 */
export interface ReactContextUsageSummary {
  task_id: string | null;
  session_id: string | null;
  estimation_mode: string;
  message_count: number;
  session_message_count: number;
  used_tokens: number;
  remaining_tokens: number;
  max_context_tokens: number;
  used_percent: number;
  remaining_percent: number;
  system_tokens: number;
  conversation_tokens: number;
  session_tokens: number;
  preview_tokens: number;
  bootstrap_tokens: number;
  draft_tokens: number;
  includes_task_bootstrap: boolean;
}

/**
 * Debug snapshot of the persisted runtime prompt window for one session.
 */
export interface ReactSessionRuntimeDebug {
  session_id: string;
  runtime_message_count: number;
  runtime_message_roles: string[];
  has_compact_result: boolean;
  compact_result: Record<string, unknown> | Array<unknown> | string | null;
  compact_result_raw: string | null;
  updated_at: string;
}

/**
 * Get full session history with recursion details.
 *
 * @param sessionId - Session UUID
 * @returns Promise resolving to full session history with tasks and recursions
 */
export const getFullSessionHistory = async (sessionId: string): Promise<FullSessionHistoryResponse> => {
  return apiRequest(`/sessions/${sessionId}/full-history`) as Promise<FullSessionHistoryResponse>;
};

/**
 * Queue one ReAct task for background execution.
 *
 * @param payload - Launch payload for the task
 * @returns Promise resolving to launch metadata
 */
export const startReactTask = async (payload: {
  agent_id: number;
  message: string;
  task_id?: string | null;
  session_id?: string | null;
  file_ids?: string[];
  web_search_provider?: string | null;
  thinking_mode?: "auto" | "fast" | "thinking" | null;
  mandatory_skill_names?: string[];
}): Promise<ReactTaskStartResponse> => {
  return apiRequest('/react/tasks', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ReactTaskStartResponse>;
};

/**
 * Request cancellation for one running ReAct task.
 *
 * @param taskId - Task UUID to cancel
 * @returns Promise resolving to the cancellation acknowledgement
 */
export const cancelReactTask = async (
  taskId: string,
): Promise<ReactTaskCancelResponse> => {
  return apiRequest(`/react/tasks/${taskId}/cancel`, {
    method: 'POST',
  }) as Promise<ReactTaskCancelResponse>;
};

/**
 * Submit one structured approve/reject decision for a waiting task.
 *
 * @param taskId - Waiting task UUID
 * @param decision - Structured user decision
 * @returns Promise resolving to resume metadata
 */
export const submitReactUserAction = async (
  taskId: string,
  decision: "approve" | "reject",
): Promise<ReactPendingUserActionResponse> => {
  return apiRequest(`/react/tasks/${taskId}/user-action`, {
    method: 'POST',
    body: JSON.stringify({ decision }),
  }) as Promise<ReactPendingUserActionResponse>;
};

/**
 * Estimate the current ReAct prompt-window usage for the chat composer.
 *
 * @param payload - Agent/session/task identifiers plus the current draft input
 * @returns Promise resolving to the estimated context usage summary
 */
export const getReactContextUsage = async (payload: {
  agent_id: number;
  session_id?: string | null;
  task_id?: string | null;
  draft_message?: string;
  file_ids?: string[];
  session_type?: ChatSessionType;
  test_snapshot?: StudioTestSnapshotPayload | null;
  mandatory_skill_names?: string[];
}): Promise<ReactContextUsageSummary> => {
  return apiRequest('/react/context-usage', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ReactContextUsageSummary>;
};

/**
 * Fetch the runtime-visible skills for the current chat surface.
 *
 * @param payload - Runtime resolution inputs matching the current chat state
 * @returns Promise resolving to visible skill metadata for the mention picker
 */
export const getReactRuntimeSkills = async (payload: {
  agent_id: number;
  session_id?: string | null;
  session_type?: ChatSessionType;
  test_snapshot?: StudioTestSnapshotPayload | null;
}): Promise<ReactRuntimeSkillItem[]> => {
  return apiRequest('/react/runtime-skills', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ReactRuntimeSkillItem[]>;
};

/**
 * Load the latest persisted runtime debug snapshot for one session.
 *
 * @param sessionId - Session UUID whose runtime window should be inspected
 * @returns Promise resolving to compact-aware runtime debug data
 */
export const getReactSessionRuntimeDebug = async (
  sessionId: string,
): Promise<ReactSessionRuntimeDebug> => {
  return apiRequest(
    `/react/sessions/${sessionId}/runtime-debug`,
  ) as Promise<ReactSessionRuntimeDebug>;
};

/**
 * Build auth headers for non-JSON requests.
 *
 * @returns Headers with bearer token when available
 * @throws AuthError if token is invalid
 */
const getAuthorizedHeaders = (): Record<string, string> => {
  if (!isTokenValid()) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Token expired or invalid. Please log in again.');
  }

  const headers: Record<string, string> = {};
  const token = getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
};

/**
 * Upload one chat file for later multimodal sending.
 *
 * @param file - File selected locally or extracted from clipboard
 * @param source - Upload source label stored in backend metadata
 * @param signal - Optional abort signal for cancelling in-flight upload
 * @returns Promise resolving to persisted file metadata
 */
export const uploadChatFile = async (
  file: File,
  source: FileUploadSource,
  signal?: AbortSignal
): Promise<ChatFileAsset> => {
  const url = `${getApiBaseUrl()}/files/uploads`;
  const headers = getAuthorizedHeaders();
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source', source);

  try {
    const response = await httpClient(url, {
      method: 'POST',
      headers,
      body: formData,
      signal,
    });

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    return await response.json() as ChatFileAsset;
  } catch (error) {
    console.error(`File upload failed for ${file.name}:`, error);
    throw error;
  }
};

/**
 * Upload one chat image for later multimodal sending.
 *
 * @param file - Image file selected locally or extracted from clipboard
 * @param source - Upload source label stored in backend metadata
 * @param signal - Optional abort signal for cancelling in-flight upload
 * @returns Promise resolving to persisted image metadata
 */
export const uploadChatImage = async (
  file: File,
  source: FileUploadSource,
  signal?: AbortSignal
): Promise<ChatFileAsset> => {
  return uploadChatFile(file, source, signal);
};

/**
 * Delete an uploaded chat file before it is used in a conversation.
 *
 * @param fileId - Backend file UUID
 */
export const deleteChatFile = async (fileId: string): Promise<void> => {
  const url = `${getApiBaseUrl()}/files/${fileId}`;
  const headers = getAuthorizedHeaders();

  try {
    const response = await httpClient(url, {
      method: 'DELETE',
      headers,
    });

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok && response.status !== 204) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }
  } catch (error) {
    console.error(`File deletion failed for ${fileId}:`, error);
    throw error;
  }
};

/**
 * Delete an uploaded chat image before it is used in a conversation.
 *
 * @param fileId - Backend file UUID
 */
export const deleteChatImage = async (fileId: string): Promise<void> => {
  await deleteChatFile(fileId);
};

/**
 * Fetch an uploaded file blob with auth so the UI can render historical thumbnails.
 *
 * @param fileId - Backend file UUID
 * @param signal - Optional abort signal
 * @returns Promise resolving to a file blob
 */
export const fetchChatFileBlob = async (
  fileId: string,
  signal?: AbortSignal
): Promise<Blob> => {
  const url = `${getApiBaseUrl()}/files/${fileId}/content`;
  const headers = getAuthorizedHeaders();

  const response = await httpClient(url, {
    method: 'GET',
    headers,
    signal,
  });

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }

  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return await response.blob();
};

/**
 * Fetch an uploaded image blob with auth so the UI can render historical thumbnails.
 *
 * @param fileId - Backend file UUID
 * @param signal - Optional abort signal
 * @returns Promise resolving to an image blob
 */
export const fetchChatImageBlob = async (
  fileId: string,
  signal?: AbortSignal
): Promise<Blob> => {
  return fetchChatFileBlob(fileId, signal);
};

/**
 * Fetch an assistant-generated task attachment blob with auth headers.
 *
 * @param attachmentId - Persisted attachment UUID
 * @param signal - Optional abort signal
 * @returns Promise resolving to the attachment blob
 */
export const fetchTaskAttachmentBlob = async (
  attachmentId: string,
  signal?: AbortSignal
): Promise<Blob> => {
  const url = `${getApiBaseUrl()}/task-attachments/${attachmentId}/content`;
  const headers = getAuthorizedHeaders();

  const response = await httpClient(url, {
    method: 'GET',
    headers,
    signal,
  });

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }

  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return await response.blob();
};

// ---------------------------------------------------------------------------
// Tools API
// ---------------------------------------------------------------------------

/**
 * A tool parameter property descriptor.
 */
export interface ToolParameterProperty {
  type: string;
  description?: string;
}

/**
 * JSON-Schema-style parameters object attached to a tool.
 */
export interface ToolParameters {
  type?: string;
  properties?: Record<string, ToolParameterProperty>;
  required?: string[];
  additionalProperties?: boolean;
}

/**
 * Execution category for a tool.
 */
export type ToolExecutionType = 'normal' | 'sandbox';

export interface UsableTool {
  name: string;
  description: string;
  parameters: ToolParameters;
  tool_type: ToolExecutionType;
  source_type: ToolSourceType;
  read_only: boolean;
  creator_id: number | null;
}

export type ManagedTool = UsableTool;

/**
 * Source code payload for a tool read response.
 */
export interface ToolSourcePayload {
  name: string;
  source: string;
}

export type ToolSourceType = 'builtin' | 'manual';

export interface ToolAccess {
  tool_name: string;
  source_type: ToolSourceType;
  read_only: boolean;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export type ToolAccessOptions = LLMAccessOptions;

/**
 * A Monaco-compatible editor diagnostic marker.
 */
export interface ToolDiagnostic {
  line: number;
  col: number;
  endLine?: number;
  endCol?: number;
  message: string;
  severity: string;
  source: string;
}

export type SkillSource = 'manual' | 'network' | 'bundle' | 'agent';

/**
 * One file entry selected from a local skill bundle.
 */
export interface BundleSkillImportFile {
  file: File;
  relativePath: string;
}

/**
 * Progress event emitted by a skill archive import job.
 */
export interface SkillImportProgressEvent {
  event_id: number;
  job_id: string;
  stage: string;
  label: string;
  percent: number;
  status: 'running' | 'complete' | 'failed';
  detail: string | null;
  metadata: UserSkill | null;
  timestamp: string;
}

/**
 * User skill metadata entry.
 */
export interface UserSkill {
  name: string;
  description: string;
  location: string;
  filename: string;
  use_scope: 'all' | 'selected';
  source: SkillSource;
  creator_id: number | null;
  creator: string | null;
  read_only: boolean;
  md5: string;
  github_repo_url: string | null;
  github_ref: string | null;
  github_ref_type: 'branch' | 'tag' | null;
  github_skill_path: string | null;
  imported: boolean;
  created_at: string;
  updated_at: string;
}

export type UsableSkill = UserSkill;
export type ManagedSkill = UserSkill;

export interface SkillAccess {
  skill_name: string;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export type SkillAccessOptions = LLMAccessOptions;

/**
 * One valid skill folder discovered in a GitHub repository.
 */
export interface GitHubSkillCandidate {
  directory_name: string;
  entry_filename: string;
  suggested_name: string;
  description: string;
  name_conflict: boolean;
}

/**
 * Repository metadata returned by GitHub skill probing.
 */
export interface GitHubSkillRepository {
  owner: string;
  repo: string;
  html_url: string;
  description: string | null;
}

/**
 * Result payload for probing a GitHub repository for importable skills.
 */
export interface GitHubSkillProbeResponse {
  repository: GitHubSkillRepository;
  default_ref: string;
  selected_ref: string;
  branches: string[];
  tags: string[];
  has_skills_dir: boolean;
  candidates: GitHubSkillCandidate[];
}

/**
 * Source code payload for a skill read response.
 */
export interface SkillSourcePayload {
  name: string;
  source: string;
  metadata: UserSkill;
}

export interface SkillFileTreeEntry {
  path: string;
  name: string;
  kind: 'directory' | 'file';
  parent_path: string | null;
  size_bytes: number | null;
}

export interface SkillFileTree {
  root_path: string;
  entries: SkillFileTreeEntry[];
}

export interface SkillFileContent {
  path: string;
  content: string;
  encoding: 'utf-8';
}

/**
 * Fetch skills the current Studio user can select when configuring agents.
 */
export const getUsableSkills = async (): Promise<UsableSkill[]> => {
  return apiRequest('/skills/usable') as Promise<UsableSkill[]>;
};

export const getManageableSkills = async (): Promise<ManagedSkill[]> => {
  return apiRequest('/skills/manage') as Promise<ManagedSkill[]>;
};

export const getSkillAccess = async (skillName: string): Promise<SkillAccess> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/access`) as Promise<SkillAccess>;
};

export const getSkillAccessOptions = async (
  skillName: string,
): Promise<SkillAccessOptions> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(
    `/skills/${encodedSkillName}/access-options`,
  ) as Promise<SkillAccessOptions>;
};

export const getSkillCreateAccessOptions = async (): Promise<SkillAccessOptions> => {
  return apiRequest('/skills/access-options') as Promise<SkillAccessOptions>;
};

export const updateSkillAccess = async (
  skillName: string,
  access: Omit<SkillAccess, 'skill_name'>,
): Promise<SkillAccess> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<SkillAccess>;
};

export const getSkillSource = async (skillName: string): Promise<SkillSourcePayload> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/source`) as Promise<SkillSourcePayload>;
};

export const createSkill = async (
  skillName: string,
  source: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  return apiRequest('/skills', {
    method: 'POST',
    body: JSON.stringify({ skill_name: skillName, source }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const updateSkillSource = async (
  skillName: string,
  source: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/source`, {
    method: 'PUT',
    body: JSON.stringify({ source }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const getSkillFileTree = async (
  skillName: string,
  path?: string | null,
): Promise<SkillFileTree> => {
  const encodedSkillName = encodeURIComponent(skillName);
  const query = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiRequest(`/skills/${encodedSkillName}/files/tree${query}`) as Promise<SkillFileTree>;
};

export const getSkillFileContent = async (
  skillName: string,
  path: string,
): Promise<SkillFileContent> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(
    `/skills/${encodedSkillName}/files/content?path=${encodeURIComponent(path)}`,
  ) as Promise<SkillFileContent>;
};

export const updateSkillFileContent = async (
  skillName: string,
  path: string,
  content: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/files/content`, {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const createSkillFileContent = async (
  skillName: string,
  path: string,
  content = '',
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/files/content`, {
    method: 'POST',
    body: JSON.stringify({ path, content }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const createSkillDirectory = async (
  skillName: string,
  path: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/files/directory`, {
    method: 'POST',
    body: JSON.stringify({ path }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const deleteSkillPath = async (
  skillName: string,
  path: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(
    `/skills/${encodedSkillName}/files/path?path=${encodeURIComponent(path)}`,
    {
      method: 'DELETE',
    },
  ) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const deleteSkill = async (
  skillName: string,
): Promise<void> => {
  const encodedSkillName = encodeURIComponent(skillName);
  await apiRequest(`/skills/${encodedSkillName}`, {
    method: 'DELETE',
  });
};

/**
 * Probe a public GitHub repository for importable skills.
 */
export const probeGitHubSkills = async (
  githubUrl: string,
  ref?: string | null
): Promise<GitHubSkillProbeResponse> => {
  return apiRequest('/skills/import/github/probe', {
    method: 'POST',
    body: JSON.stringify({
      github_url: githubUrl,
      ref: ref ?? null,
    }),
  }) as Promise<GitHubSkillProbeResponse>;
};

/**
 * Import one skill folder from a public GitHub repository.
 */
export const importGitHubSkill = async (payload: {
  github_url: string;
  ref: string;
  ref_type: 'branch' | 'tag';
  remote_directory_name: string;
  skill_name: string;
}): Promise<{ status: string; metadata: UserSkill }> => {
  return apiRequest('/skills/import/github', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<{ status: string; metadata: UserSkill }>;
};

/**
 * Import one skill bundle selected from the local machine.
 */
export const importBundleSkill = async (payload: {
  bundleName: string;
  skillName: string;
  files: BundleSkillImportFile[];
}): Promise<{ status: string; metadata: UserSkill }> => {
  const url = `${getApiBaseUrl()}/skills/import/bundle`;
  const headers = getAuthorizedHeaders();
  const formData = new FormData();

  formData.append('bundle_name', payload.bundleName);
  formData.append('skill_name', payload.skillName);
  payload.files.forEach((entry) => {
    formData.append('files', entry.file);
    formData.append('relative_paths', entry.relativePath);
  });

  try {
    const response = await httpClient(url, {
      method: 'POST',
      headers,
      body: formData,
    });

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    return await response.json() as { status: string; metadata: UserSkill };
  } catch (error) {
    console.error(`Bundle import failed for ${payload.bundleName}:`, error);
    throw error;
  }
};

/**
 * Create one observable archive import job.
 */
export const createSkillArchiveImportJob = async (): Promise<{ job_id: string }> => {
  return apiRequest('/skills/import/archive/jobs', {
    method: 'POST',
  }) as Promise<{ job_id: string }>;
};

function parseSkillImportProgressEvent(value: unknown): SkillImportProgressEvent | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const event = value as Partial<SkillImportProgressEvent>;
  if (
    typeof event.event_id !== 'number' ||
    typeof event.job_id !== 'string' ||
    typeof event.stage !== 'string' ||
    typeof event.label !== 'string' ||
    typeof event.percent !== 'number' ||
    typeof event.status !== 'string'
  ) {
    return null;
  }
  if (!['running', 'complete', 'failed'].includes(event.status)) {
    return null;
  }
  return event as SkillImportProgressEvent;
}

/**
 * Stream progress events for one archive import job.
 */
export const streamSkillArchiveImportJobEvents = async (
  jobId: string,
  onEvent: (event: SkillImportProgressEvent) => void,
  signal?: AbortSignal,
): Promise<void> => {
  const response = await httpClient(
    `${getApiBaseUrl()}/skills/import/archive/jobs/${jobId}/events/stream`,
    {
      headers: getAuthorizedHeaders(),
      signal,
    },
  );

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }
  if (!response.ok || !response.body) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim() || line.startsWith(':') || !line.startsWith('data: ')) {
        continue;
      }
      const parsed = JSON.parse(line.slice(6).trim()) as unknown;
      const event = parseSkillImportProgressEvent(parsed);
      if (event) {
        onEvent(event);
      }
    }
  }
};

/**
 * Upload one compressed skill archive into an existing import job.
 */
export const importSkillArchive = async (payload: {
  jobId: string;
  skillName: string;
  archive: File;
}): Promise<{ status: string; metadata: UserSkill }> => {
  const formData = new FormData();
  formData.append('archive', payload.archive);
  formData.append('skill_name', payload.skillName);

  const response = await httpClient(
    `${getApiBaseUrl()}/skills/import/archive/jobs/${payload.jobId}`,
    {
      method: 'POST',
      headers: getAuthorizedHeaders(),
      body: formData,
    },
  );

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }
  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return await response.json() as { status: string; metadata: UserSkill };
};

export const getUsableTools = async (): Promise<UsableTool[]> => {
  return apiRequest('/tools/usable') as Promise<UsableTool[]>;
};

export const getManageableTools = async (): Promise<ManagedTool[]> => {
  return apiRequest('/tools/manage') as Promise<ManagedTool[]>;
};

export const getToolCreateAccessOptions = async (): Promise<ToolAccessOptions> => {
  return apiRequest('/tools/access-options') as Promise<ToolAccessOptions>;
};

/**
 * Surface-scoped workspace file endpoint URLs exposed by the backend bootstrap.
 */
export interface SurfaceFilesApiResponse {
  /** Direct directory listing endpoint for workspace paths visible to the surface. */
  directory_url: string;
  /** UTF-8 file endpoint for the same surface session. */
  text_url: string;
  /** Binary file endpoint for uploads and authenticated downloads. */
  blob_url: string;
  /** Tree listing endpoint for workspace paths visible to the surface. */
  tree_url: string;
  /** UTF-8 file content endpoint for the same surface session. */
  content_url: string;
}

/**
 * Session-scoped preview endpoint returned by the backend.
 */
export interface PreviewEndpointResponse {
  /** Stable backend-issued preview identifier. */
  preview_id: string;
  /** Chat session that owns this preview endpoint. */
  session_id: string;
  /** Workspace identifier bound to the chat session. */
  workspace_id: string;
  /** Logical workspace root visible to the current operator. */
  workspace_logical_root: string;
  /** Operator-facing preview label. */
  title: string;
  /** Sandbox-local port exposed through the preview gateway. */
  port: number;
  /** Initial preview path opened through the gateway. */
  path: string;
  /** Whether Pivot recorded enough launch metadata to reconnect this preview. */
  has_launch_recipe: boolean;
  /** Host-facing preview URL that the surface should open. */
  proxy_url: string;
  /** UTC creation timestamp for this preview endpoint. */
  created_at: string;
}

/**
 * Reconnect response returned to one surface runtime.
 */
export interface ReconnectPreviewEndpointResponse {
  /** Preview endpoint that was just reconnected. */
  preview: PreviewEndpointResponse;
  /** Full preview registry visible to the current surface session. */
  available_previews: PreviewEndpointResponse[];
  /** Preview that should become active after reconnect. */
  active_preview_id: string | null;
}

/**
 * Minimal bootstrap payload returned for one development surface session.
 */
export interface DevSurfaceBootstrapResponse {
  /** Stable backend-issued surface session identifier. */
  surface_session_id: string;
  /** Short-lived surface token used by iframe bootstrap and future runtime APIs. */
  surface_token: string;
  /** Current runtime mode for this surface session. */
  mode: 'dev';
  /** Stable surface key declared by the development runtime. */
  surface_key: string;
  /** Operator-facing label rendered by the dock. */
  display_name: string;
  /** Owning agent identifier for the bound chat session. */
  agent_id: number;
  /** Chat session identifier that owns the runtime workspace. */
  session_id: string;
  /** Workspace identifier visible to future surface tooling. */
  workspace_id: string;
  /** Logical workspace root currently bound to the active chat session. */
  workspace_logical_root: string;
  /** Local development runtime URL validated by the backend. */
  dev_server_url: string;
  /** Capabilities granted to the surface runtime. */
  capabilities: string[];
  /** Surface-scoped file endpoints available to the runtime. */
  files_api: SurfaceFilesApiResponse;
}

/**
 * Development surface session metadata returned to the chat host.
 */
export interface DevSurfaceSessionResponse {
  /** Stable backend-issued surface session identifier. */
  surface_session_id: string;
  /** Short-lived surface token used by the initial iframe navigation. */
  surface_token: string;
  /** Stable surface key declared by the runtime. */
  surface_key: string;
  /** Operator-facing label rendered by the dock. */
  display_name: string;
  /** Owning agent identifier for the bound chat session. */
  agent_id: number;
  /** Bound chat session identifier. */
  session_id: string;
  /** Bound workspace identifier. */
  workspace_id: string;
  /** Logical workspace root currently bound to the active chat session. */
  workspace_logical_root: string;
  /** Local development runtime URL validated by the backend. */
  dev_server_url: string;
  /** UTC creation timestamp for the dev surface session. */
  created_at: string;
  /** Minimum runtime bootstrap payload returned by the backend. */
  bootstrap: DevSurfaceBootstrapResponse;
}

/**
 * Minimal bootstrap payload returned for one installed surface session.
 */
export interface InstalledSurfaceBootstrapResponse {
  /** Stable backend-issued surface session identifier. */
  surface_session_id: string;
  /** Short-lived surface token used by iframe bootstrap and later runtime APIs. */
  surface_token: string;
  /** Current runtime mode for this surface session. */
  mode: 'installed';
  /** Stable surface key declared by the installed extension. */
  surface_key: string;
  /** Operator-facing label rendered by the dock. */
  display_name: string;
  /** Canonical package id that owns this installed surface. */
  package_id: string;
  /** Installed extension version selected for this runtime. */
  extension_installation_id: number;
  /** Owning agent identifier for the bound chat session. */
  agent_id: number;
  /** Chat session identifier that owns the runtime workspace. */
  session_id: string;
  /** Workspace identifier visible to the installed runtime. */
  workspace_id: string;
  /** Logical workspace root currently bound to the active chat session. */
  workspace_logical_root: string;
  /** Host-relative runtime iframe URL served by the backend. */
  runtime_url: string;
  /** Capabilities granted to the surface runtime. */
  capabilities: string[];
  /** Surface-scoped file endpoints available to the runtime. */
  files_api: SurfaceFilesApiResponse;
}

/**
 * Installed surface session metadata returned to the chat host.
 */
export interface InstalledSurfaceSessionResponse {
  /** Stable backend-issued surface session identifier. */
  surface_session_id: string;
  /** Short-lived surface token used by the initial iframe navigation. */
  surface_token: string;
  /** Stable surface key declared by the installed extension. */
  surface_key: string;
  /** Operator-facing label rendered by the dock. */
  display_name: string;
  /** Canonical package id that owns this installed surface. */
  package_id: string;
  /** Installed extension version selected for this runtime. */
  extension_installation_id: number;
  /** Owning agent identifier for the bound chat session. */
  agent_id: number;
  /** Bound chat session identifier. */
  session_id: string;
  /** Bound workspace identifier. */
  workspace_id: string;
  /** Logical workspace root currently bound to the active chat session. */
  workspace_logical_root: string;
  /** Host-relative runtime iframe URL served by the backend. */
  runtime_url: string;
  /** UTC creation timestamp for the installed surface session. */
  created_at: string;
  /** Minimum runtime bootstrap payload returned by the backend. */
  bootstrap: InstalledSurfaceBootstrapResponse;
}

/**
 * Create one development-mode chat surface session for the current chat session.
 *
 * Why: the dock needs a backend-issued surface session before later phases can
 * proxy a local dev server or grant surface-scoped file access.
 *
 * @param payload - Session id plus local dev runtime details
 * @returns Promise resolving to the created surface session and bootstrap
 */
export const createDevSurfaceSession = async (payload: {
  sessionId: string;
  surfaceKey: string;
  /** Runtime URL. May point at a dev server root or entry HTML page. */
  devServerUrl: string;
  displayName?: string | null;
}): Promise<DevSurfaceSessionResponse> => {
  return apiRequest('/chat-surfaces/dev-sessions', {
    method: 'POST',
    body: JSON.stringify({
      session_id: payload.sessionId,
      surface_key: payload.surfaceKey,
      dev_server_url: payload.devServerUrl,
      display_name: payload.displayName ?? null,
    }),
  }) as Promise<DevSurfaceSessionResponse>;
};

/**
 * Create one installed-surface session for the current chat session.
 *
 * Why: installed chat surfaces should reuse the same dock and iframe host as
 * development surfaces, but their runtime assets come from the selected
 * extension installation rather than a local dev server.
 *
 * @param payload - Session id plus installed extension identifiers
 * @returns Promise resolving to the created installed surface session
 */
export const createInstalledSurfaceSession = async (payload: {
  sessionId: string;
  extensionInstallationId: number;
  surfaceKey: string;
}): Promise<InstalledSurfaceSessionResponse> => {
  return apiRequest('/chat-surfaces/installed-sessions', {
    method: 'POST',
    body: JSON.stringify({
      session_id: payload.sessionId,
      extension_installation_id: payload.extensionInstallationId,
      surface_key: payload.surfaceKey,
    }),
  }) as Promise<InstalledSurfaceSessionResponse>;
};

/**
 * Create one session-scoped web preview endpoint for the active chat session.
 *
 * Why: preview endpoints are a separate lifecycle from surface sessions and
 * should not leak raw sandbox ports into the host UI contract.
 *
 * @param payload - Session id plus sandbox-local preview details
 * @returns Promise resolving to the created preview endpoint
 */
export const createPreviewEndpoint = async (payload: {
  sessionId: string;
  previewName: string;
  startServer: string;
  port: number;
  path?: string | null;
  cwd?: string | null;
}): Promise<PreviewEndpointResponse> => {
  return apiRequest('/chat-previews', {
    method: 'POST',
    body: JSON.stringify({
      session_id: payload.sessionId,
      preview_name: payload.previewName,
      start_server: payload.startServer,
      port: payload.port,
      path: payload.path ?? '/',
      cwd: payload.cwd ?? '.',
    }),
  }) as Promise<PreviewEndpointResponse>;
};

/**
 * Fetch the current preview registry for one chat session.
 *
 * @param sessionId - Owning chat session identifier
 * @returns Promise resolving to all preview endpoints visible to the caller
 */
export const getPreviewEndpoints = async (
  sessionId: string,
): Promise<PreviewEndpointResponse[]> => {
  const encodedSessionId = encodeURIComponent(sessionId);
  return apiRequest(
    `/chat-previews?session_id=${encodedSessionId}`,
  ) as Promise<PreviewEndpointResponse[]>;
};

/**
 * Ask the backend to reconnect one stored preview recipe for a surface session.
 *
 * @param payload - Surface session and preview identifiers plus access token
 * @returns Promise resolving to the refreshed preview registry payload
 */
export const reconnectSurfacePreview = async (payload: {
  surfaceSessionId: string;
  previewId: string;
  surfaceToken: string;
}): Promise<ReconnectPreviewEndpointResponse> => {
  const nextUrl = new URL(
    `/api/chat-surfaces/sessions/${payload.surfaceSessionId}/previews/${payload.previewId}/connect`,
    window.location.origin,
  );
  nextUrl.searchParams.set('surface_token', payload.surfaceToken);
  return apiRequest(nextUrl.pathname + nextUrl.search, {
    method: 'POST',
    skipAuth: true,
    skipTokenCheck: true,
  }) as Promise<ReconnectPreviewEndpointResponse>;
};

export const getToolSource = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<ToolSourcePayload> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(
    `/tools/${sourceType}/${encodedToolName}/source`,
  ) as Promise<ToolSourcePayload>;
};

export const updateToolSource = async (
  sourceType: ToolSourceType,
  toolName: string,
  source: string,
): Promise<void> => {
  const encodedToolName = encodeURIComponent(toolName);
  await apiRequest(`/tools/${sourceType}/${encodedToolName}/source`, {
    method: 'PUT',
    body: JSON.stringify({ source }),
  });
};

export const deleteToolSource = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<void> => {
  const encodedToolName = encodeURIComponent(toolName);
  await apiRequest(`/tools/${sourceType}/${encodedToolName}/source`, {
    method: 'DELETE',
  });
};

export const getToolAccess = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<ToolAccess> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(
    `/tools/${sourceType}/${encodedToolName}/access`,
  ) as Promise<ToolAccess>;
};

export const getToolAccessOptions = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<ToolAccessOptions> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(
    `/tools/${sourceType}/${encodedToolName}/access-options`,
  ) as Promise<ToolAccessOptions>;
};

export const updateToolAccess = async (
  sourceType: ToolSourceType,
  toolName: string,
  access: Omit<ToolAccess, 'tool_name' | 'source_type' | 'read_only'>,
): Promise<ToolAccess> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(`/tools/${sourceType}/${encodedToolName}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<ToolAccess>;
};

/**
 * Check Python source code with ast.parse (fast syntax check).
 *
 * @param source - Python source code
 * @returns Promise resolving to list of diagnostics
 */
export const checkToolAst = async (source: string): Promise<ToolDiagnostic[]> => {
  return apiRequest('/tools/check/ast', {
    method: 'POST',
    body: JSON.stringify({ source }),
  }) as Promise<ToolDiagnostic[]>;
};

/**
 * Check Python source code with ruff (style and lint check).
 *
 * @param source - Python source code
 * @returns Promise resolving to list of diagnostics
 */
export const checkToolRuff = async (source: string): Promise<ToolDiagnostic[]> => {
  return apiRequest('/tools/check/ruff', {
    method: 'POST',
    body: JSON.stringify({ source }),
  }) as Promise<ToolDiagnostic[]>;
};

/**
 * Check Python source code with pyright (type check).
 *
 * @param source - Python source code
 * @returns Promise resolving to list of diagnostics
 */
export const checkToolPyright = async (source: string): Promise<ToolDiagnostic[]> => {
  return apiRequest('/tools/check/pyright', {
    method: 'POST',
    body: JSON.stringify({ source }),
  }) as Promise<ToolDiagnostic[]>;
};
