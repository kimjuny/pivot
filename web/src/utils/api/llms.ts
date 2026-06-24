import type { LLM, LLMUsable } from '../../types';
import { apiRequest, type AccessOptions } from './core';

export type LLMAccessUserOption = AccessOptions['users'][number];
export type LLMAccessGroupOption = AccessOptions['groups'][number];
export type LLMAccessOptions = AccessOptions;

export interface LLMAccess {
  llm_id: number;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export const getModels = async (): Promise<string[]> => {
  const response = await apiRequest('/models') as { models: string[]; count: number };
  return response.models;
};

export const getLLMs = async (): Promise<LLM[]> => {
  return apiRequest('/llms') as Promise<LLM[]>;
};

export const getUsableLLMs = async (): Promise<LLMUsable[]> => {
  return apiRequest('/llms/usable') as Promise<LLMUsable[]>;
};

export const getUsableLLMById = async (llmId: number): Promise<LLMUsable> => {
  return apiRequest(`/llms/usable/${llmId}`) as Promise<LLMUsable>;
};

export const createLLM = async (llmData: {
  name: string;
  endpoint: string;
  model: string;
  api_key: string;
  protocol?: string;
  cache_policy?: string;
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

export const getLLMById = async (llmId: number): Promise<LLM> => {
  return apiRequest(`/llms/${llmId}`) as Promise<LLM>;
};

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

export const updateLLM = async (
  llmId: number,
  llmData: {
    name?: string;
    endpoint?: string;
    model?: string;
    api_key?: string;
    protocol?: string;
    cache_policy?: string;
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

export const deleteLLM = async (llmId: number): Promise<void> => {
  await apiRequest(`/llms/${llmId}`, {
    method: 'DELETE',
  });
};
