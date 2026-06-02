import { apiRequest } from './core';

export interface WebSearchConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'secret' | 'textarea' | 'boolean';
  required: boolean;
  placeholder?: string | null;
  description?: string | null;
}

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
  default_runtime_config: Record<string, unknown>;
}

export interface WebSearchCatalogItem {
  manifest: WebSearchProviderManifest;
}

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

export const getWebSearchProviders = async (agentId?: number): Promise<WebSearchCatalogItem[]> => {
  const query = typeof agentId === 'number' ? `?agent_id=${agentId}` : '';
  return apiRequest(`/web-search/providers${query}`) as Promise<WebSearchCatalogItem[]>;
};

export const getAgentWebSearchBindings = async (agentId: number): Promise<WebSearchBinding[]> => {
  return apiRequest(`/agents/${agentId}/web-search`) as Promise<WebSearchBinding[]>;
};

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

export const deleteAgentWebSearchBinding = async (bindingId: number): Promise<void> => {
  await apiRequest(`/agent-web-search/${bindingId}`, {
    method: 'DELETE',
  });
};

export const testAgentWebSearchBinding = async (
  bindingId: number
): Promise<{ result: { ok: boolean; status: string; message: string } }> => {
  return apiRequest(`/agent-web-search/${bindingId}/test`, {
    method: 'POST',
  }) as Promise<{ result: { ok: boolean; status: string; message: string } }>;
};

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
