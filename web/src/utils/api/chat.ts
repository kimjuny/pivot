import type { Agent, LLMUsable } from '../../types';
import { apiRequest } from './core';
import type { SessionListItem, ProjectResponse } from './sessions';

export interface ChatSurfaceDescriptorResponse {
  installation_id: number;
  package_id: string;
  surface_key: string;
  display_name: string;
  logo_url: string | null;
  description: string | null;
  min_width: number | null;
  icon: string | null;
}

export interface WebSearchProviderOptionResponse {
  provider_key: string;
  name: string;
  logo_url: string | null;
}

export interface ChatBootstrapResponse {
  agent: Agent;
  llm: LLMUsable | null;
  sessions: SessionListItem[];
  projects: ProjectResponse[];
  chat_surfaces: ChatSurfaceDescriptorResponse[];
  web_search_providers: WebSearchProviderOptionResponse[];
}

export const getAgentChatSurfaces = async (
  agentId: number,
): Promise<ChatSurfaceDescriptorResponse[]> => {
  return apiRequest(
    `/agents/${agentId}/chat-surfaces`,
  ) as Promise<ChatSurfaceDescriptorResponse[]>;
};

export const getChatBootstrap = async (
  agentId: number,
): Promise<ChatBootstrapResponse> => {
  return apiRequest(
    `/client/agents/${agentId}/chat-bootstrap`,
  ) as Promise<ChatBootstrapResponse>;
};
