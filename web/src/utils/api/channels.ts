import { apiRequest } from './core';

export interface ChannelConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'secret' | 'textarea' | 'boolean';
  required: boolean;
  placeholder?: string | null;
  description?: string | null;
}

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
  logo_url?: string | null;
  capabilities: string[];
  auth_schema: ChannelConfigField[];
  config_schema: ChannelConfigField[];
  setup_steps: string[];
}

export interface ChannelEndpointInfo {
  label: string;
  method: string;
  url: string;
  description: string;
}

export interface ChannelCatalogItem {
  manifest: ChannelManifest;
}

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

export const getChannels = async (agentId?: number): Promise<ChannelCatalogItem[]> => {
  const query = typeof agentId === 'number' ? `?agent_id=${agentId}` : '';
  return apiRequest(`/channels${query}`) as Promise<ChannelCatalogItem[]>;
};

export const getChannel = async (channelKey: string): Promise<ChannelCatalogItem> => {
  return apiRequest(`/channels/${encodeURIComponent(channelKey)}`) as Promise<ChannelCatalogItem>;
};

export const getAgentChannels = async (agentId: number): Promise<ChannelBinding[]> => {
  return apiRequest(`/agents/${agentId}/channels`) as Promise<ChannelBinding[]>;
};

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

export const deleteAgentChannel = async (bindingId: number): Promise<void> => {
  await apiRequest(`/agent-channels/${bindingId}`, {
    method: 'DELETE',
  });
};

export const testAgentChannel = async (
  bindingId: number
): Promise<{ result: { ok: boolean; status: string; message: string; endpoint_infos: ChannelEndpointInfo[] } }> => {
  return apiRequest(`/agent-channels/${bindingId}/test`, {
    method: 'POST',
  }) as Promise<{ result: { ok: boolean; status: string; message: string; endpoint_infos: ChannelEndpointInfo[] } }>;
};

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

export const pollAgentChannel = async (
  bindingId: number
): Promise<{ fetched: number; next_offset: number | null; replies: Array<{ conversation_id: string; external_user_id: string | null; reply: string }> }> => {
  return apiRequest(`/agent-channels/${bindingId}/poll`, {
    method: 'POST',
  }) as Promise<{ fetched: number; next_offset: number | null; replies: Array<{ conversation_id: string; external_user_id: string | null; reply: string }> }>;
};

export const getChannelLinkStatus = async (
  token: string
): Promise<ChannelLinkStatus> => {
  return apiRequest(`/channel-link/${encodeURIComponent(token)}`, {
    skipAuth: true,
    skipTokenCheck: true,
  }) as Promise<ChannelLinkStatus>;
};

export const completeChannelLink = async (
  token: string
): Promise<{ status: string; message: string; pivot_user_id: number; linked_at: string }> => {
  return apiRequest(`/channel-link/${encodeURIComponent(token)}/complete`, {
    method: 'POST',
  }) as Promise<{ status: string; message: string; pivot_user_id: number; linked_at: string }>;
};
