import type { Agent, Scene, SceneGraph, ChatResponse, ChatHistoryResponse, BuildChatRequest, BuildChatResponse, PreviewChatRequest, PreviewChatResponse, StreamEvent, LLM } from '../types';
import { getAuthToken, isTokenValid, AUTH_EXPIRED_EVENT } from '../contexts/AuthContext';

/**
 * API base URL from environment configuration.
 * In development, uses localhost; in production, uses relative path.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8003/api';

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
 * Send a message to a specific agent by ID.
 * 
 * @param agentId - Unique identifier of the target agent
 * @param message - User message to send to the agent
 * @param user - User identifier (defaults to 'preview-user')
 * @returns Promise resolving to the agent's response
 */
export const chatWithAgentById = async (
  agentId: number,
  message: string,
  user: string = 'preview-user'
): Promise<ChatResponse> => {
  return apiRequest(`/agents/${agentId}/chat`, {
    method: 'POST',
    body: JSON.stringify({ message, user }),
  }) as Promise<ChatResponse>;
};

/**
 * Fetch chat history for a specific agent and user.
 * 
 * @param agentId - Unique identifier of the agent
 * @param user - User identifier (defaults to 'preview-user')
 * @returns Promise resolving to chat history and latest graph
 */
export const getChatHistory = async (
  agentId: number,
  user: string = 'preview-user'
): Promise<ChatHistoryResponse> => {
  return apiRequest(`/agents/${agentId}/chat-history?user=${user}`) as Promise<ChatHistoryResponse>;
};

/**
 * Clear chat history for a specific agent and user.
 * 
 * @param agentId - Unique identifier of the agent
 * @param user - User identifier (defaults to 'preview-user')
 * @returns Promise resolving when history is cleared
 */
export const clearChatHistory = async (
  agentId: number,
  user: string = 'preview-user'
): Promise<void> => {
  await apiRequest(`/agents/${agentId}/chat-history?user=${user}`, {
    method: 'DELETE',
  });
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
 * Send a message to the Build Agent for agent editing assistance.
 * 
 * @param request - Build chat request containing message and optional session/agent info
 * @returns Promise resolving to Build Agent's response with updated agent data
 */
export const chatWithBuildAgent = async (request: BuildChatRequest): Promise<BuildChatResponse> => {
  return apiRequest('/build/chat', {
    method: 'POST',
    body: JSON.stringify(request),
  }) as Promise<BuildChatResponse>;
};

/**
 * Send a message to Preview Agent (stateless) with streaming response.
 *
 * @param request - Preview chat request containing message, agent definition, and state
 * @param onEvent - Callback for handling stream events
 * @returns Promise resolving when stream completes
 */
export const previewChatStream = async (
  request: PreviewChatRequest,
  onEvent: (event: StreamEvent) => void
): Promise<void> => {
  // Check token validity before making request
  if (!isTokenValid()) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Token expired or invalid. Please log in again.');
  }

  const token = getAuthToken();
  const url = `${API_BASE_URL}/preview/chat/stream`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  });

  // Handle 401 Unauthorized
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }

  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  if (!response.body) {
    throw new Error('ReadableStream not supported');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6)) as StreamEvent;
            onEvent(data);
          } catch (e) {
            console.error('Error parsing SSE data:', e);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
};

/**
 * Send a message to Build Agent (streaming) for agent editing assistance.
 *
 * @param request - Build chat request containing message and optional agent ID
 * @param onEvent - Callback for handling stream events
 * @returns Promise resolving when stream completes
 */
export const buildChatStream = async (
  request: BuildChatRequest,
  onEvent: (event: StreamEvent) => void
): Promise<void> => {
  // Check token validity before making request
  if (!isTokenValid()) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Token expired or invalid. Please log in again.');
  }

  const token = getAuthToken();
  const url = `${API_BASE_URL}/build/chat/stream`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  });

  // Handle 401 Unauthorized
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }

  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  if (!response.body) {
    throw new Error('ReadableStream not supported');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6)) as StreamEvent;
            onEvent(data);
          } catch (e) {
            console.error('Error parsing SSE data:', e);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
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
    is_active?: boolean;
  }
): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify(agentData),
  }) as Promise<Agent>;
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
  chat?: boolean;
  system_role?: boolean;
  tool_calling?: string;
  json_schema?: string;
  streaming?: boolean;
  max_context?: number;
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
    chat?: boolean;
    system_role?: boolean;
    tool_calling?: string;
    json_schema?: string;
    streaming?: boolean;
    max_context?: number;
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
}

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
  thought: string | null;
  abstract: string | null;
  action_type: string | null;
  action_output: string | null;
  tool_call_results: string | null;
  status: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  created_at: string;
  updated_at: string;
}

/**
 * Task message from full session history API.
 */
export interface TaskMessage {
  task_id: string;
  user_message: string;
  agent_answer: string | null;
  status: string;
  total_tokens: number;
  recursions: RecursionDetail[];
  created_at: string;
  updated_at: string;
}

/**
 * Full session history response from API.
 */
export interface FullSessionHistoryResponse {
  session_id: string;
  tasks: TaskMessage[];
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
