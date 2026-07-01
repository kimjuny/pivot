import type { ChatSessionType, StudioTestSnapshotPayload } from '@/utils/agentTestSnapshot';
import { apiRequest, type FileUploadSource } from './core';

export interface ProjectResponse {
  id: number;
  project_id: string;
  agent_id: number;
  name: string;
  description: string | null;
  workspace_id: string;
  can_edit: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectAccess {
  project_id: string;
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface ProjectAccessUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface ProjectAccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface ProjectAccessOptions {
  users: ProjectAccessUserOption[];
  groups: ProjectAccessGroupOption[];
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
  total: number;
}

export interface SessionListItem {
  session_id: string;
  agent_id: number;
  type?: ChatSessionType;
  release_id?: number | null;
  latest_release_id?: number | null;
  is_stale?: boolean;
  migrated_to_session_id?: string | null;
  project_id?: string | null;
  workspace_id?: string | null;
  workspace_scope?: "session_private" | "project_shared" | null;
  test_workspace_hash?: string | null;
  status: string;
  runtime_status?: "idle" | "running" | "waiting_input";
  title: string | null;
  is_pinned: boolean;
  channel_key?: string | null;
  channel_logo_url?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionListResponse {
  sessions: SessionListItem[];
  total: number;
}

export interface SessionResponse {
  id: number;
  session_id: string;
  agent_id: number;
  type?: ChatSessionType;
  release_id?: number | null;
  latest_release_id?: number | null;
  is_stale?: boolean;
  migrated_to_session_id?: string | null;
  project_id?: string | null;
  workspace_id?: string | null;
  workspace_scope?: "session_private" | "project_shared" | null;
  test_workspace_hash?: string | null;
  user_id: number;
  status: string;
  runtime_status?: "idle" | "running" | "waiting_input";
  title: string | null;
  is_pinned: boolean;
  created_at: string;
  updated_at: string;
}

export interface SessionMigrateResponse {
  old_session_id: string;
  new_session_id: string;
  new_release_id: number | null;
}

export interface SessionChatHistoryMessage {
  type: string;
  content: string;
  timestamp: string;
  files?: ChatFileAsset[];
  attachments?: TaskAttachmentAsset[];
}

export interface ChatFileAsset {
  file_id: string;
  kind: 'image' | 'document';
  source: FileUploadSource;
  original_name: string;
  mime_type: string;
  format: string;
  extension: string;
  size_bytes: number;
  width: number;
  height: number;
  page_count?: number | null;
  can_extract_text?: boolean;
  suspected_scanned?: boolean;
  text_encoding?: string | null;
  session_id: string | null;
  task_id: string | null;
  created_at: string;
  expires_at?: string;
}

export interface TaskAttachmentAsset {
  attachment_id: string;
  display_name: string;
  original_name: string;
  mime_type: string;
  extension: string;
  size_bytes: number;
  render_kind:
    | 'markdown'
    | 'pdf'
    | 'image'
    | 'text'
    | 'docx'
    | 'spreadsheet'
    | 'video'
    | 'download';
  workspace_relative_path: string;
  created_at: string;
}

export type ChatImageFile = ChatFileAsset;

export interface SessionChatHistoryResponse {
  version: number;
  messages: SessionChatHistoryMessage[];
}

export const createSession = async (
  agentId: number,
  options?: {
    projectId?: string | null;
    type?: ChatSessionType;
    testSnapshot?: StudioTestSnapshotPayload | null;
  },
): Promise<SessionResponse> => {
  return apiRequest('/sessions', {
    method: 'POST',
    body: JSON.stringify({
      agent_id: agentId,
      project_id: options?.projectId ?? null,
      type: options?.type ?? 'client',
      test_snapshot: options?.testSnapshot ?? null,
    }),
  }) as Promise<SessionResponse>;
};

export const listProjects = async (
  agentId: number,
): Promise<ProjectListResponse> => {
  return apiRequest(`/projects?agent_id=${agentId}`) as Promise<ProjectListResponse>;
};

export const createProject = async (payload: {
  agent_id: number;
  name: string;
  description?: string | null;
}): Promise<ProjectResponse> => {
  return apiRequest('/projects', {
    method: 'POST',
    body: JSON.stringify({
      agent_id: payload.agent_id,
      name: payload.name,
      description: payload.description ?? null,
    }),
  }) as Promise<ProjectResponse>;
};

export const updateProject = async (
  projectId: string,
  payload: {
    name?: string | null;
    description?: string | null;
  },
): Promise<ProjectResponse> => {
  return apiRequest(`/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }) as Promise<ProjectResponse>;
};

export const deleteProject = async (projectId: string): Promise<void> => {
  await apiRequest(`/projects/${projectId}`, {
    method: 'DELETE',
  });
};

export const getProjectAccess = async (
  projectId: string,
): Promise<ProjectAccess> => {
  return apiRequest(`/projects/${projectId}/access`) as Promise<ProjectAccess>;
};

export const getProjectAccessOptions = async (
  projectId: string,
): Promise<ProjectAccessOptions> => {
  return apiRequest(
    `/projects/${projectId}/access-options`,
  ) as Promise<ProjectAccessOptions>;
};

export const updateProjectAccess = async (
  projectId: string,
  access: Omit<ProjectAccess, 'project_id'>,
): Promise<ProjectAccess> => {
  return apiRequest(`/projects/${projectId}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<ProjectAccess>;
};

export const listSessions = async (
  agentId?: number,
  limit: number = 50,
  options?: {
    type?: ChatSessionType;
  },
): Promise<SessionListResponse> => {
  let endpoint = `/sessions?limit=${limit}`;
  if (agentId !== undefined) {
    endpoint += `&agent_id=${agentId}`;
  }
  if (options?.type) {
    endpoint += `&session_type=${options.type}`;
  }
  return apiRequest(endpoint) as Promise<SessionListResponse>;
};

export const getSession = async (sessionId: string): Promise<SessionResponse> => {
  return apiRequest(`/sessions/${sessionId}`) as Promise<SessionResponse>;
};

export const updateSession = async (
  sessionId: string,
  sessionData: {
    title?: string | null;
    is_pinned?: boolean;
  },
): Promise<SessionResponse> => {
  return apiRequest(`/sessions/${sessionId}`, {
    method: 'PATCH',
    body: JSON.stringify(sessionData),
  }) as Promise<SessionResponse>;
};

export const deleteSession = async (sessionId: string): Promise<void> => {
  await apiRequest(`/sessions/${sessionId}`, {
    method: 'DELETE',
  });
};

export const closeSession = async (
  sessionId: string,
): Promise<SessionResponse> => {
  return apiRequest(`/sessions/${sessionId}/close`, {
    method: 'POST',
  }) as Promise<SessionResponse>;
};

export const migrateSession = async (
  sessionId: string,
): Promise<SessionMigrateResponse> => {
  return apiRequest(`/sessions/${sessionId}/migrate`, {
    method: 'POST',
  }) as Promise<SessionMigrateResponse>;
};

export const getSessionHistory = async (sessionId: string): Promise<SessionChatHistoryResponse> => {
  return apiRequest(`/sessions/${sessionId}/history`) as Promise<SessionChatHistoryResponse>;
};
