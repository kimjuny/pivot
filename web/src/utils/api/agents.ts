import type { Agent, AgentDelegation } from '../../types';
import { apiRequest } from './core';

export interface AgentReleaseRecord {
  id: number;
  version: number;
  release_note: string | null;
  change_summary: string[];
  published_by_user_id: number | null;
  created_at: string;
}

export interface AgentSavedDraftInfo {
  saved_at: string;
  saved_by_user_id: number | null;
  snapshot_hash: string;
}

export interface AgentDraftState {
  saved_draft: AgentSavedDraftInfo;
  latest_release: AgentReleaseRecord | null;
  has_publishable_changes: boolean;
  publish_summary: string[];
  release_history: AgentReleaseRecord[];
}

export interface AgentSidebarSectionStats {
  selected_count: number;
  total_count: number;
}

export interface AgentSidebarStats {
  tools: AgentSidebarSectionStats;
  skills: AgentSidebarSectionStats;
  extensions: AgentSidebarSectionStats;
  channels: AgentSidebarSectionStats;
  media: AgentSidebarSectionStats;
  web_search: AgentSidebarSectionStats;
  delegations: AgentSidebarSectionStats;
}

export interface AgentAccess {
  agent_id: number;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface AgentAccessUserOption {
  id: number;
  username: string;
  email: string | null;
}

export interface AgentAccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface AgentAccessOptions {
  users: AgentAccessUserOption[];
  groups: AgentAccessGroupOption[];
}

export const getAgents = async (): Promise<Agent[]> => {
  return apiRequest('/agents') as Promise<Agent[]>;
};

export const createAgent = async (agentData: {
  name: string;
  description?: string;
  llm_id: number;
  session_idle_timeout_minutes?: number;
  sandbox_timeout_seconds?: number;
  compact_threshold_percent?: number;
  max_iteration?: number;
  allow_delegation?: boolean;
  delegation_description?: string;
  use_scope?: 'all' | 'selected';
  use_user_ids?: number[];
  use_group_ids?: number[];
}): Promise<Agent> => {
  return apiRequest('/agents', {
    method: 'POST',
    body: JSON.stringify(agentData),
  }) as Promise<Agent>;
};

export const updateAgentClientState = async (
  agentId: number,
  clientState: 'open' | 'paused',
): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}/client-state`, {
    method: 'PATCH',
    body: JSON.stringify({ client_state: clientState }),
  }) as Promise<Agent>;
};

export const getAgentAccess = async (agentId: number): Promise<AgentAccess> => {
  return apiRequest(`/agents/${agentId}/access`) as Promise<AgentAccess>;
};

export const getAgentAccessOptions = async (
  agentId: number,
): Promise<AgentAccessOptions> => {
  return apiRequest(`/agents/${agentId}/access-options`) as Promise<AgentAccessOptions>;
};

export const getAgentCreateAccessOptions = async (): Promise<AgentAccessOptions> => {
  return apiRequest('/agents/access-options') as Promise<AgentAccessOptions>;
};

export const updateAgentAccess = async (
  agentId: number,
  access: AgentAccess,
): Promise<AgentAccess> => {
  return apiRequest(`/agents/${agentId}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<AgentAccess>;
};

export const getAgentById = async (agentId: number): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}`) as Promise<Agent>;
};

export const getAgentSidebarStats = async (agentId: number): Promise<AgentSidebarStats> => {
  return apiRequest(`/agents/${agentId}/sidebar-stats`) as Promise<AgentSidebarStats>;
};

export const deleteAgent = async (agentId: number): Promise<void> => {
  await apiRequest(`/agents/${agentId}`, {
    method: 'DELETE',
  });
};

export const updateAgent = async (
  agentId: number,
  agentData: {
    name?: string;
    description?: string;
    llm_id?: number;
    session_idle_timeout_minutes?: number;
    sandbox_timeout_seconds?: number;
    compact_threshold_percent?: number;
    max_iteration?: number;
    allow_delegation?: boolean;
    delegation_description?: string;
    tool_ids?: string | null;
    skill_ids?: string | null;
  }
): Promise<Agent> => {
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify(agentData),
  }) as Promise<Agent>;
};

export const getAgentDraftState = async (agentId: number): Promise<AgentDraftState> => {
  return apiRequest(`/agents/${agentId}/draft-state`) as Promise<AgentDraftState>;
};

export const saveAgentDraft = async (agentId: number): Promise<AgentDraftState> => {
  return apiRequest(`/agents/${agentId}/drafts/save`, {
    method: 'POST',
  }) as Promise<AgentDraftState>;
};

export const publishAgentRelease = async (
  agentId: number,
  releaseNote: string
): Promise<AgentDraftState> => {
  return apiRequest(`/agents/${agentId}/releases`, {
    method: 'POST',
    body: JSON.stringify({ release_note: releaseNote.trim() || null }),
  }) as Promise<AgentDraftState>;
};

export const updateAgentToolIds = async (
  agentId: number,
  toolNames: string[] | null
): Promise<Agent> => {
  const tool_ids = toolNames === null ? null : JSON.stringify(toolNames);
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify({ tool_ids }),
  }) as Promise<Agent>;
};

export const updateAgentSkillIds = async (
  agentId: number,
  skillNames: string[] | null
): Promise<Agent> => {
  const skill_ids = skillNames === null ? null : JSON.stringify(skillNames);
  return apiRequest(`/agents/${agentId}`, {
    method: 'PUT',
    body: JSON.stringify({ skill_ids }),
  }) as Promise<Agent>;
};

// ---------------------------------------------------------------------------
// Delegations API
// ---------------------------------------------------------------------------

export const getAgentDelegations = async (
  agentId: number
): Promise<AgentDelegation[]> => {
  return apiRequest(`/agents/${agentId}/delegations`) as Promise<AgentDelegation[]>;
};

export const replaceAgentDelegations = async (
  agentId: number,
  delegations: Array<{
    callee_agent_id: number;
    callee_alias: string;
    pass_mode?: string;
    max_timeout_seconds?: number;
    max_iterations_override?: number | null;
    enabled?: boolean;
    priority?: number;
  }>
): Promise<AgentDelegation[]> => {
  return apiRequest(`/agents/${agentId}/delegations`, {
    method: 'PUT',
    body: JSON.stringify({ delegations }),
  }) as Promise<AgentDelegation[]>;
};

export const createAgentDelegation = async (
  agentId: number,
  data: {
    callee_agent_id: number;
    callee_alias: string;
    pass_mode?: string;
    max_timeout_seconds?: number;
    max_iterations_override?: number | null;
    enabled?: boolean;
    priority?: number;
  }
): Promise<AgentDelegation> => {
  return apiRequest(`/agents/${agentId}/delegations`, {
    method: 'POST',
    body: JSON.stringify(data),
  }) as Promise<AgentDelegation>;
};

export const deleteAgentDelegation = async (
  agentId: number,
  delegationId: number
): Promise<void> => {
  await apiRequest(`/agents/${agentId}/delegations/${delegationId}`, {
    method: 'DELETE',
  });
};
