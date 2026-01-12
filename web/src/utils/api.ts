import type { Agent, Scene, SceneGraph, ChatRequest, ChatResponse, ChatHistoryResponse } from '../types';

const API_BASE_URL = 'http://localhost:8003/api';

interface RequestOptions {
  headers?: Record<string, string>;
  method?: string;
  body?: string;
}

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

export const getAgents = async (): Promise<Agent[]> => {
  return apiRequest('/agents') as Promise<Agent[]>;
};

export const getAgentById = async (agentId: number): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}`) as Promise<Agent>;
};

export const getScenes = async (): Promise<Scene[]> => {
  return apiRequest('/scenes') as Promise<Scene[]>;
};

export const getSceneById = async (sceneId: number): Promise<Scene> => {
  return apiRequest(`/scenes/${sceneId}`) as Promise<Scene>;
};

export const getSceneSubscenes = async (sceneId: number): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/subscenes`);
};

export const getSceneGraph = async (sceneId: number): Promise<unknown> => {
  return apiRequest(`/scenes/${sceneId}/graph`);
};

export const initializeAgent = async (): Promise<unknown> => {
  return apiRequest('/initialize', {
    method: 'POST',
  });
};

export const chatWithAgent = async (message: string): Promise<ChatResponse> => {
  return apiRequest('/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  }) as Promise<ChatResponse>;
};

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

export const getChatHistory = async (
  agentId: number,
  user: string = 'preview-user'
): Promise<ChatHistoryResponse> => {
  return apiRequest(`/agents/${agentId}/chat-history?user=${user}`) as Promise<ChatHistoryResponse>;
};

export const clearChatHistory = async (
  agentId: number,
  user: string = 'preview-user'
): Promise<void> => {
  await apiRequest(`/agents/${agentId}/chat-history?user=${user}`, {
    method: 'DELETE',
  });
};

export const fetchSceneGraph = async (): Promise<SceneGraph> => {
  return apiRequest('/scene-graph') as Promise<SceneGraph>;
};

export const getAgentState = async (): Promise<unknown> => {
  return apiRequest('/state');
};

export const resetAgent = async (): Promise<unknown> => {
  return apiRequest('/reset', {
    method: 'POST',
  });
};
