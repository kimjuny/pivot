import { apiRequest, type AccessOptions } from './core';

export interface Tool {
  name: string;
  description: string;
  parameters: {
    type: string;
    properties: Record<string, unknown>;
    required?: string[];
  };
}

export interface ToolParameterProperty {
  type: string;
  description?: string;
}

export interface ToolParameters {
  type?: string;
  properties?: Record<string, ToolParameterProperty>;
  required?: string[];
  additionalProperties?: boolean;
}

export type ToolExecutionType = 'normal' | 'sandbox';

export type ToolSourceType = 'builtin' | 'manual';
export type ToolInventorySourceType = ToolSourceType | 'extension';
export type ToolSourceCategory = 'builtin' | 'builder' | 'extension';

export interface UsableTool {
  name: string;
  description: string;
  parameters: ToolParameters;
  tool_type: ToolExecutionType;
  source_type: ToolSourceType;
  source_category: ToolSourceCategory;
  read_only: boolean;
  creator_id: number | null;
  from_label: string | null;
  extension_package_id?: string | null;
  extension_display_name?: string | null;
  extension_version?: string | null;
}

export interface ManagedTool extends Omit<UsableTool, 'source_type'> {
  source_type: ToolInventorySourceType;
}

export interface ToolSourcePayload {
  name: string;
  source: string;
}

export interface ToolAccess {
  tool_name: string;
  source_type: ToolSourceType;
  read_only: boolean;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export type ToolAccessOptions = AccessOptions;

export interface ToolDiagnostic {
  line: number;
  col: number;
  endLine?: number;
  endCol?: number;
  message: string;
  severity: string;
  source: string;
}

export const getTools = async (): Promise<Tool[]> => {
  return apiRequest('/tools') as Promise<Tool[]>;
};

export const getUsableTools = async (): Promise<UsableTool[]> => {
  return apiRequest('/tools/usable') as Promise<UsableTool[]>;
};

export const getManageableTools = async (): Promise<ManagedTool[]> => {
  return apiRequest('/tools/manage') as Promise<ManagedTool[]>;
};

export const getToolCreateAccessOptions = async (): Promise<ToolAccessOptions> => {
  return apiRequest('/tools/access-options') as Promise<ToolAccessOptions>;
};

export const getToolSource = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<ToolSourcePayload> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(
    `/tools/${sourceType}/${encodedToolName}/source`,
  ) as Promise<ToolSourcePayload>;
};

export const updateToolSource = async (
  sourceType: ToolSourceType,
  toolName: string,
  source: string,
): Promise<void> => {
  const encodedToolName = encodeURIComponent(toolName);
  await apiRequest(`/tools/${sourceType}/${encodedToolName}/source`, {
    method: 'PUT',
    body: JSON.stringify({ source }),
  });
};

export const deleteToolSource = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<void> => {
  const encodedToolName = encodeURIComponent(toolName);
  await apiRequest(`/tools/${sourceType}/${encodedToolName}/source`, {
    method: 'DELETE',
  });
};

export const getToolAccess = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<ToolAccess> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(
    `/tools/${sourceType}/${encodedToolName}/access`,
  ) as Promise<ToolAccess>;
};

export const getToolAccessOptions = async (
  sourceType: ToolSourceType,
  toolName: string,
): Promise<ToolAccessOptions> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(
    `/tools/${sourceType}/${encodedToolName}/access-options`,
  ) as Promise<ToolAccessOptions>;
};

export const updateToolAccess = async (
  sourceType: ToolSourceType,
  toolName: string,
  access: Omit<ToolAccess, 'tool_name' | 'source_type' | 'read_only'>,
): Promise<ToolAccess> => {
  const encodedToolName = encodeURIComponent(toolName);
  return apiRequest(`/tools/${sourceType}/${encodedToolName}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<ToolAccess>;
};

export const checkToolAst = async (source: string): Promise<ToolDiagnostic[]> => {
  return apiRequest('/tools/check/ast', {
    method: 'POST',
    body: JSON.stringify({ source }),
  }) as Promise<ToolDiagnostic[]>;
};

export const checkToolRuff = async (source: string): Promise<ToolDiagnostic[]> => {
  return apiRequest('/tools/check/ruff', {
    method: 'POST',
    body: JSON.stringify({ source }),
  }) as Promise<ToolDiagnostic[]>;
};

export const checkToolPyright = async (source: string): Promise<ToolDiagnostic[]> => {
  return apiRequest('/tools/check/pyright', {
    method: 'POST',
    body: JSON.stringify({ source }),
  }) as Promise<ToolDiagnostic[]>;
};
