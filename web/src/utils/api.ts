import type { Agent, Scene, SceneGraph, ChatRequest, ChatResponse, ChatHistoryResponse } from '../types';

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
 * Fetch a specific scene by ID.
 * 
 * @param sceneId - Unique identifier of the scene
 * @returns Promise resolving to Scene object
 */
export const getSceneById = async (sceneId: number): Promise<Scene> => {
  return apiRequest(`/scenes/${sceneId}`) as Promise<Scene>;
};

/**
 * Fetch all subscenes for a specific scene.
 * 
 * @param sceneId - Unique identifier of the scene
 * @returns Promise resolving to subscene data
 */
export const getSceneSubscenes = async (sceneId: number): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/subscenes`);
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
 * Initialize the agent system on the server.
 * This prepares the agent for receiving messages.
 * 
 * @returns Promise resolving when initialization is complete
 */
export const initializeAgent = async (): Promise<unknown> => {
  return apiRequest('/initialize', {
    method: 'POST',
  });
};

/**
 * Send a message to the default agent.
 * 
 * @param message - User message to send to the agent
 * @returns Promise resolving to the agent's response
 */
export const chatWithAgent = async (message: string): Promise<ChatResponse> => {
  return apiRequest('/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  }) as Promise<ChatResponse>;
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
 * Fetch the current scene graph from the server.
 * 
 * @returns Promise resolving to SceneGraph object
 */
export const fetchSceneGraph = async (): Promise<SceneGraph> => {
  return apiRequest('/scene-graph') as Promise<SceneGraph>;
};

/**
 * Fetch the current state of the agent system.
 * 
 * @returns Promise resolving to agent state data
 */
export const getAgentState = async (): Promise<unknown> => {
  return apiRequest('/state');
};

/**
 * Reset the agent system to its initial state.
 * Clears all state and history.
 * 
 * @returns Promise resolving when reset is complete
 */
export const resetAgent = async (): Promise<unknown> => {
  return apiRequest('/reset', {
    method: 'POST',
  });
};
