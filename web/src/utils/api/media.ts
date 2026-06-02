import { apiRequest } from './core';

export interface MediaProviderConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'secret' | 'textarea' | 'boolean';
  required: boolean;
  placeholder?: string | null;
  default_value?: string | number | boolean | null;
  description?: string | null;
}

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
  logo_url?: string | null;
  auth_schema: MediaProviderConfigField[];
  config_schema: MediaProviderConfigField[];
  setup_steps: string[];
  supported_operations: string[];
  supported_parameters: string[];
  capability_flags: Record<string, boolean>;
}

export interface MediaProviderCatalogItem {
  manifest: MediaProviderManifest;
}

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

export const getMediaGenerationProviders = async (agentId?: number): Promise<MediaProviderCatalogItem[]> => {
  const query = typeof agentId === 'number' ? `?agent_id=${agentId}` : '';
  return apiRequest(`/media-generation/providers${query}`) as Promise<MediaProviderCatalogItem[]>;
};

export const getAgentMediaProviderBindings = async (agentId: number): Promise<MediaProviderBinding[]> => {
  return apiRequest(`/agents/${agentId}/media-providers`) as Promise<MediaProviderBinding[]>;
};

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

export const deleteAgentMediaProviderBinding = async (bindingId: number): Promise<void> => {
  await apiRequest(`/agent-media-providers/${bindingId}`, {
    method: 'DELETE',
  });
};

export const testAgentMediaProviderBinding = async (
  bindingId: number
): Promise<{ result: { ok: boolean; status: string; message: string } }> => {
  return apiRequest(`/agent-media-providers/${bindingId}/test`, {
    method: 'POST',
  }) as Promise<{ result: { ok: boolean; status: string; message: string } }>;
};

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
