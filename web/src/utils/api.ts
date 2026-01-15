import type { Agent, Scene, SceneGraph, ChatResponse, ChatHistoryResponse } from '../types';

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
}

/**
 * Make an API request to backend server.
 * Handles common request/response logic including error handling.
 * 
 * @param endpoint - API endpoint path (e.g., '/agents')
 * @param options - Request configuration options
 * @returns Promise resolving to response data
 * @throws Error if request fails or returns non-OK status
 */
const apiRequest = async (endpoint: string, options: RequestOptions = {}): Promise<unknown> => {
  const url = `${API_BASE_URL}${endpoint}`;

  const config: RequestInit = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  try {
    const response = await fetch(url, config);

    if (!response.ok) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
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
  model_name?: string;
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
 * @returns Promise resolving to array of Scene objects
 */
export const getScenes = async (): Promise<Scene[]> => {
  return apiRequest('/scenes') as Promise<Scene[]>;
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
