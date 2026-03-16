import type { Agent, Scene, SceneGraph, LLM } from '../types';
import { getAuthToken, isTokenValid, AUTH_EXPIRED_EVENT } from '../contexts/auth-core';

/**
 * API base URL from environment configuration.
 * In development, uses localhost; in production, uses relative path.
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8003/api';

/**
 * Configuration options for API requests.
 */
interface RequestOptions {
  /** Additional headers to include in request */
  headers?: Record<string, string>;
  /** HTTP method (GET, POST, DELETE, etc.) */
  method?: string;
  /** Request body as JSON string */
  body?: string;
  /** Whether to skip adding auth header (for login endpoint) */
  skipAuth?: boolean;
  /** Whether to skip token validation check */
  skipTokenCheck?: boolean;
}

/**
 * Supported image upload source labels.
 */
export type FileUploadSource = 'local' | 'clipboard';

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
const apiRequest = async (endpoint: string, options: RequestOptions = {}): Promise<unknown> => {
  const url = `${API_BASE_URL}${endpoint}`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

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
    const response = await fetch(url, config);

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
 * Fetch all agents from server.
 * 
 * @returns Promise resolving to array of Agent objects
 */
export const getAgents = async (): Promise<Agent[]> => {
  return apiRequest('/agents') as Promise<Agent[]>;
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
  skill_resolution_llm_id?: number | null;
  session_idle_timeout_minutes?: number;
  is_active?: boolean;
}): Promise<Agent> => {
  return apiRequest('/agents', {
    method: 'POST',
    body: JSON.stringify(agentData),
  }) as Promise<Agent>;
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
 * Fetch all scenes from server.
 * 
 * @param agentId - Optional agent ID to filter scenes
 * @returns Promise resolving to array of Scene objects
 */
export const getScenes = async (agentId?: number): Promise<Scene[]> => {
  const queryParams = agentId ? `?agent_id=${agentId}` : '';
  return apiRequest(`/scenes${queryParams}`) as Promise<Scene[]>;
};

/**
 * Create a new scene.
 * 
 * @param sceneData - Scene creation data
 * @returns Promise resolving to created Scene object
 */
export const createScene = async (sceneData: {
  name: string;
  description?: string;
  agent_id: number;
}): Promise<Scene> => {
  return apiRequest('/scenes', {
    method: 'POST',
    body: JSON.stringify(sceneData),
  }) as Promise<Scene>;
};

/**
 * Fetch scene graph for a specific scene.
 * 
 * @param sceneId - Unique identifier of the scene
 * @returns Promise resolving to scene graph data
 */
export const getSceneGraph = async (sceneId: number): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/graph`);
};

/**
 * Update a subscene.
 * 
 * @param sceneId - Unique identifier of the scene
 * @param subsceneName - Name of the subscene to update
 * @param subsceneData - Subscene update data
 * @returns Promise resolving to updated subscene data
 */
export const updateSubscene = async (
  sceneId: number,
  subsceneName: string,
  subsceneData: {
    name?: string;
    type?: string;
    mandatory?: boolean;
    objective?: string;
  }
): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/subscenes/${subsceneName}`, {
    method: 'PUT',
    body: JSON.stringify(subsceneData),
  });
};

/**
 * Update a connection.
 *
 * @param sceneId - Unique identifier of the scene
 * @param fromSubscene - Name of the source subscene
 * @param toSubscene - Name of the target subscene
 * @param connectionData - Connection update data
 * @returns Promise resolving to updated connection data
 */
export const updateConnection = async (
  sceneId: number,
  fromSubscene: string,
  toSubscene: string,
  connectionData: {
    name?: string;
    condition?: string;
  }
): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/connections`, {
    method: 'PUT',
    body: JSON.stringify({
      from_subscene: fromSubscene,
      to_subscene: toSubscene,
      ...connectionData,
    }),
  });
};

/**
 * Create a new subscene.
 *
 * @param sceneId - Unique identifier of the scene
 * @param subsceneData - Subscene creation data
 * @returns Promise resolving to created subscene data
 */
export const createSubscene = async (
  sceneId: number,
  subsceneData: {
    name: string;
    type?: string;
    mandatory?: boolean;
    objective?: string;
    description?: string;
  }
): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/subscenes`, {
    method: 'POST',
    body: JSON.stringify(subsceneData),
  });
};

/**
 * Create a new connection.
 *
 * @param sceneId - Unique identifier of the scene
 * @param connectionData - Connection creation data
 * @returns Promise resolving to created connection data
 */
export const createConnection = async (
  sceneId: number,
  connectionData: {
    name: string;
    from_subscene: string;
    to_subscene: string;
    condition?: string;
  }
): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/connections`, {
    method: 'POST',
    body: JSON.stringify(connectionData),
  });
};

/**
 * Bulk update scene graph with all subscenes and connections.
 * This replaces the entire scene graph with the provided data.
 *
 * @param sceneId - Unique identifier of the scene
 * @param graphData - Complete scene graph data with all subscenes and connections
 * @returns Promise resolving to updated scene graph data
 */
export const updateSceneGraph = async (
  sceneId: number,
  graphData: {
    scenes: Array<{
      name: string;
      type?: string;
      state?: string;
      description?: string;
      mandatory?: boolean;
      objective?: string;
      connections?: Array<{
        name?: string;
        condition?: string;
        to_subscene: string;
      }>;
    }>;
    agent_id?: number;
  }
): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/graph`, {
    method: 'PUT',
    body: JSON.stringify(graphData),
  });
};

/**
 * Bulk update agent scenes list.
 * 
 * @param agentId - Unique identifier of the agent
 * @param scenes - List of scenes to sync
 * @returns Promise resolving to updated list of Scene objects
 */
export const updateAgentScenes = async (
  agentId: number,
  scenes: Array<{
    name: string;
    description?: string;
    graph?: Array<{
      name: string;
      type?: string;
      state?: string;
      description?: string;
      mandatory?: boolean;
      objective?: string;
      connections?: Array<{
        name?: string;
        condition?: string;
        to_subscene: string;
      }>;
    }>;
  }>
): Promise<Scene[]> => {
  return apiRequest(`/agents/${agentId}/scenes`, {
    method: 'PUT',
    body: JSON.stringify({ scenes }),
  }) as Promise<Scene[]>;
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
    skill_resolution_llm_id?: number | null;
    session_idle_timeout_minutes?: number;
    is_active?: boolean;
    skill_ids?: string | null;
  }
): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify(agentData),
  }) as Promise<Agent>;
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
export const getChannels = async (): Promise<ChannelCatalogItem[]> => {
  return apiRequest('/channels') as Promise<ChannelCatalogItem[]>;
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
  chat?: boolean;
  system_role?: boolean;
  tool_calling?: string;
  json_schema?: string;
  thinking?: string;
  streaming?: boolean;
  image_input?: boolean;
  image_output?: boolean;
  max_context?: number;
  extra_config?: string;
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
    chat?: boolean;
    system_role?: boolean;
    tool_calling?: string;
    json_schema?: string;
    thinking?: string;
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
 * Session list item from API.
 */
export interface SessionListItem {
  session_id: string;
  agent_id: number;
  status: string;
  subject: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
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
  user: string;
  status: string;
  subject: {
    content: string;
    source: string;
    confidence: number;
  } | null;
  object: {
    content: string;
    source: string;
    confidence: number;
  } | null;
  created_at: string;
  updated_at: string;
}

/**
 * Create a new conversation session.
 *
 * @param agentId - Agent ID for the session
 * @returns Promise resolving to created session
 */
export const createSession = async (agentId: number): Promise<SessionResponse> => {
  return apiRequest('/sessions', {
    method: 'POST',
    body: JSON.stringify({ agent_id: agentId }),
  }) as Promise<SessionResponse>;
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
  limit: number = 50
): Promise<SessionListResponse> => {
  let endpoint = `/sessions?limit=${limit}`;
  if (agentId !== undefined) {
    endpoint += `&agent_id=${agentId}`;
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
 * Chat history message from session API.
 */
export interface SessionChatHistoryMessage {
  type: string;
  content: string;
  timestamp: string;
  files?: ChatFileAsset[];
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
  observe: string | null;
  thinking: string | null;
  thought: string | null;
  abstract: string | null;
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
  agent_answer: string | null;
  status: string;
  total_tokens: number;
  skill_selection_result?: {
    count?: number;
    selected_skills?: string[];
    duration_ms?: number;
    tokens?: {
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
      cached_input_tokens?: number;
    };
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
}): Promise<ReactContextUsageSummary> => {
  return apiRequest('/react/context-usage', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<ReactContextUsageSummary>;
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
  const url = `${API_BASE_URL}/files/uploads`;
  const headers = getAuthorizedHeaders();
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source', source);

  try {
    const response = await fetch(url, {
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
  const url = `${API_BASE_URL}/files/${fileId}`;
  const headers = getAuthorizedHeaders();

  try {
    const response = await fetch(url, {
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
  const url = `${API_BASE_URL}/files/${fileId}/content`;
  const headers = getAuthorizedHeaders();

  const response = await fetch(url, {
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

/**
 * A shared (built-in) tool returned by the server.
 */
export interface SharedTool {
  name: string;
  description: string;
  parameters: ToolParameters;
  tool_type: ToolExecutionType;
}

/**
 * A private (user-workspace) tool file entry.
 */
export interface PrivateTool {
  name: string;
  filename: string;
  tool_type: ToolExecutionType;
}

/**
 * Source code payload for a tool read response.
 */
export interface ToolSourcePayload {
  name: string;
  source: string;
}

/**
 * Backward-compatible alias for private tool source payload.
 */
export type PrivateToolSource = ToolSourcePayload;

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

/**
 * Shared skill metadata returned by the server.
 */
export interface SharedSkill {
  name: string;
  description: string;
  location: string;
  filename: string;
  kind: 'shared';
  source: 'builtin' | 'user';
  creator: string | null;
  builtin: boolean;
  read_only: boolean;
  md5: string;
  created_at: string;
  updated_at: string;
}

/**
 * User skill metadata entry.
 */
export interface UserSkill {
  name: string;
  description: string;
  location: string;
  filename: string;
  kind: 'private' | 'shared';
  source: 'user';
  creator: string | null;
  builtin: boolean;
  read_only: boolean;
  md5: string;
  created_at: string;
  updated_at: string;
}

/**
 * Source code payload for a skill read response.
 */
export interface SkillSourcePayload {
  name: string;
  source: string;
  metadata: SharedSkill | UserSkill;
}

/**
 * Fetch all shared skills visible to the current user.
 */
export const getSharedSkills = async (): Promise<SharedSkill[]> => {
  return apiRequest('/skills/shared') as Promise<SharedSkill[]>;
};

/**
 * Fetch list of private skills for the current user.
 */
export const getPrivateSkills = async (): Promise<UserSkill[]> => {
  return apiRequest('/skills/private') as Promise<UserSkill[]>;
};

/**
 * Fetch a creator-owned skill source from private/shared namespace.
 */
export const getUserSkillSource = async (
  kind: 'private' | 'shared',
  skillName: string
): Promise<SkillSourcePayload> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${kind}/${encodedSkillName}`) as Promise<SkillSourcePayload>;
};

/**
 * Fetch one shared skill source visible to the current user.
 */
export const getSharedSkillSource = async (skillName: string): Promise<SkillSourcePayload> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/shared/${encodedSkillName}`) as Promise<SkillSourcePayload>;
};

/**
 * Create or update a user-owned markdown skill.
 */
export const upsertUserSkill = async (
  kind: 'private' | 'shared',
  skillName: string,
  source: string
): Promise<void> => {
  const encodedSkillName = encodeURIComponent(skillName);
  await apiRequest(`/skills/${kind}/${encodedSkillName}`, {
    method: 'PUT',
    body: JSON.stringify({ source }),
  });
};

/**
 * Delete a user-owned markdown skill.
 */
export const deleteUserSkill = async (
  kind: 'private' | 'shared',
  skillName: string
): Promise<void> => {
  const encodedSkillName = encodeURIComponent(skillName);
  await apiRequest(`/skills/${kind}/${encodedSkillName}`, {
    method: 'DELETE',
  });
};

/**
 * Fetch all shared (built-in) tools.
 *
 * @returns Promise resolving to list of shared tools
 */
export const getSharedTools = async (): Promise<SharedTool[]> => {
  return apiRequest('/tools/shared') as Promise<SharedTool[]>;
};

/**
 * Fetch list of private tool files for the current user.
 *
 * @returns Promise resolving to list of private tool entries
 */
export const getPrivateTools = async (): Promise<PrivateTool[]> => {
  return apiRequest('/tools/private') as Promise<PrivateTool[]>;
};

/**
 * Fetch source code of a private tool.
 *
 * @param toolName - Tool name (file stem without .py)
 * @returns Promise resolving to tool source payload
 */
export const getPrivateToolSource = async (toolName: string): Promise<ToolSourcePayload> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(`/tools/private/${encodedToolName}`) as Promise<ToolSourcePayload>;
};

/**
 * Fetch source code of a shared (built-in) tool.
 *
 * @param toolName - Tool name from shared catalog
 * @returns Promise resolving to tool source payload
 */
export const getSharedToolSource = async (toolName: string): Promise<ToolSourcePayload> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(`/tools/shared/${encodedToolName}`) as Promise<ToolSourcePayload>;
};

/**
 * Create or update a private tool source file.
 *
 * @param toolName - Tool name (file stem without .py)
 * @param source - Python source code
 * @returns Promise resolving when saved
 */
export const upsertPrivateTool = async (toolName: string, source: string): Promise<void> => {
  await apiRequest(`/tools/private/${toolName}`, {
    method: 'PUT',
    body: JSON.stringify({ source }),
  });
};

/**
 * Delete a private tool.
 *
 * @param toolName - Tool name (file stem without .py)
 * @returns Promise resolving when deleted
 */
export const deletePrivateTool = async (toolName: string): Promise<void> => {
  await apiRequest(`/tools/private/${toolName}`, { method: 'DELETE' });
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
