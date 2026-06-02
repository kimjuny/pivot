import { apiRequest, httpClient, getAuthorizedHeaders, AuthError, getApiBaseUrl, type AccessOptions } from './core';
import { AUTH_EXPIRED_EVENT } from '../../contexts/auth-core';

export type SkillSource = 'manual' | 'network' | 'bundle' | 'agent' | 'extension';
export type SkillSourceCategory = 'builder' | 'extension';

export interface BundleSkillImportFile {
  file: File;
  relativePath: string;
}

export interface SkillImportProgressEvent {
  event_id: number;
  job_id: string;
  stage: string;
  label: string;
  percent: number;
  status: 'running' | 'complete' | 'failed';
  detail: string | null;
  metadata: UserSkill | null;
  timestamp: string;
}

export interface UserSkill {
  name: string;
  description: string;
  location: string;
  filename: string;
  use_scope: 'all' | 'selected';
  source: SkillSource;
  source_category: SkillSourceCategory;
  creator_id: number | null;
  creator: string | null;
  from_label: string | null;
  read_only: boolean;
  md5: string;
  github_repo_url: string | null;
  github_ref: string | null;
  github_ref_type: 'branch' | 'tag' | null;
  github_skill_path: string | null;
  imported: boolean;
  extension_package_id?: string | null;
  extension_display_name?: string | null;
  extension_version?: string | null;
  created_at: string;
  updated_at: string;
}

export type UsableSkill = UserSkill;
export type ManagedSkill = UserSkill;

export interface SkillAccess {
  skill_name: string;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export type SkillAccessOptions = AccessOptions;

export interface GitHubSkillCandidate {
  directory_name: string;
  entry_filename: string;
  suggested_name: string;
  description: string;
  name_conflict: boolean;
}

export interface GitHubSkillRepository {
  owner: string;
  repo: string;
  html_url: string;
  description: string | null;
}

export interface GitHubSkillProbeResponse {
  repository: GitHubSkillRepository;
  default_ref: string;
  selected_ref: string;
  branches: string[];
  tags: string[];
  has_skills_dir: boolean;
  candidates: GitHubSkillCandidate[];
}

export interface SkillSourcePayload {
  name: string;
  source: string;
  metadata: UserSkill;
}

export interface SkillFileTreeEntry {
  path: string;
  name: string;
  kind: 'directory' | 'file';
  parent_path: string | null;
  size_bytes: number | null;
}

export interface SkillFileTree {
  root_path: string;
  entries: SkillFileTreeEntry[];
}

export interface SkillFileContent {
  path: string;
  content: string;
  encoding: 'utf-8';
}

export const getUsableSkills = async (): Promise<UsableSkill[]> => {
  return apiRequest('/skills/usable') as Promise<UsableSkill[]>;
};

export const getManageableSkills = async (): Promise<ManagedSkill[]> => {
  return apiRequest('/skills/manage') as Promise<ManagedSkill[]>;
};

export const getSkillAccess = async (skillName: string): Promise<SkillAccess> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/access`) as Promise<SkillAccess>;
};

export const getSkillAccessOptions = async (
  skillName: string,
): Promise<SkillAccessOptions> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(
    `/skills/${encodedSkillName}/access-options`,
  ) as Promise<SkillAccessOptions>;
};

export const getSkillCreateAccessOptions = async (): Promise<SkillAccessOptions> => {
  return apiRequest('/skills/access-options') as Promise<SkillAccessOptions>;
};

export const updateSkillAccess = async (
  skillName: string,
  access: Omit<SkillAccess, 'skill_name'>,
): Promise<SkillAccess> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<SkillAccess>;
};

export const getSkillSource = async (skillName: string): Promise<SkillSourcePayload> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/source`) as Promise<SkillSourcePayload>;
};

export const createSkill = async (
  skillName: string,
  source: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  return apiRequest('/skills', {
    method: 'POST',
    body: JSON.stringify({ skill_name: skillName, source }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const updateSkillSource = async (
  skillName: string,
  source: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/source`, {
    method: 'PUT',
    body: JSON.stringify({ source }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const getSkillFileTree = async (
  skillName: string,
  path?: string | null,
): Promise<SkillFileTree> => {
  const encodedSkillName = encodeURIComponent(skillName);
  const query = path ? `?path=${encodeURIComponent(path)}` : '';
  return apiRequest(`/skills/${encodedSkillName}/files/tree${query}`) as Promise<SkillFileTree>;
};

export const getSkillFileContent = async (
  skillName: string,
  path: string,
): Promise<SkillFileContent> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(
    `/skills/${encodedSkillName}/files/content?path=${encodeURIComponent(path)}`,
  ) as Promise<SkillFileContent>;
};

export const updateSkillFileContent = async (
  skillName: string,
  path: string,
  content: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/files/content`, {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const createSkillFileContent = async (
  skillName: string,
  path: string,
  content = '',
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/files/content`, {
    method: 'POST',
    body: JSON.stringify({ path, content }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const createSkillDirectory = async (
  skillName: string,
  path: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(`/skills/${encodedSkillName}/files/directory`, {
    method: 'POST',
    body: JSON.stringify({ path }),
  }) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const deleteSkillPath = async (
  skillName: string,
  path: string,
): Promise<{ status: string; metadata: ManagedSkill }> => {
  const encodedSkillName = encodeURIComponent(skillName);
  return apiRequest(
    `/skills/${encodedSkillName}/files/path?path=${encodeURIComponent(path)}`,
    {
      method: 'DELETE',
    },
  ) as Promise<{ status: string; metadata: ManagedSkill }>;
};

export const deleteSkill = async (
  skillName: string,
): Promise<void> => {
  const encodedSkillName = encodeURIComponent(skillName);
  await apiRequest(`/skills/${encodedSkillName}`, {
    method: 'DELETE',
  });
};

export const probeGitHubSkills = async (
  githubUrl: string,
  ref?: string | null
): Promise<GitHubSkillProbeResponse> => {
  return apiRequest('/skills/import/github/probe', {
    method: 'POST',
    body: JSON.stringify({
      github_url: githubUrl,
      ref: ref ?? null,
    }),
  }) as Promise<GitHubSkillProbeResponse>;
};

export const importGitHubSkill = async (payload: {
  github_url: string;
  ref: string;
  ref_type: 'branch' | 'tag';
  remote_directory_name: string;
  skill_name: string;
}): Promise<{ status: string; metadata: UserSkill }> => {
  return apiRequest('/skills/import/github', {
    method: 'POST',
    body: JSON.stringify(payload),
  }) as Promise<{ status: string; metadata: UserSkill }>;
};

export const importBundleSkill = async (payload: {
  bundleName: string;
  skillName: string;
  files: BundleSkillImportFile[];
}): Promise<{ status: string; metadata: UserSkill }> => {
  const url = `${getApiBaseUrl()}/skills/import/bundle`;
  const headers = getAuthorizedHeaders();
  const formData = new FormData();

  formData.append('bundle_name', payload.bundleName);
  formData.append('skill_name', payload.skillName);
  payload.files.forEach((entry) => {
    formData.append('files', entry.file);
    formData.append('relative_paths', entry.relativePath);
  });

  try {
    const response = await httpClient(url, {
      method: 'POST',
      headers,
      body: formData,
    });

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    return await response.json() as { status: string; metadata: UserSkill };
  } catch (error) {
    console.error(`Bundle import failed for ${payload.bundleName}:`, error);
    throw error;
  }
};

export const createSkillArchiveImportJob = async (): Promise<{ job_id: string }> => {
  return apiRequest('/skills/import/archive/jobs', {
    method: 'POST',
  }) as Promise<{ job_id: string }>;
};

function parseSkillImportProgressEvent(value: unknown): SkillImportProgressEvent | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const event = value as Partial<SkillImportProgressEvent>;
  if (
    typeof event.event_id !== 'number' ||
    typeof event.job_id !== 'string' ||
    typeof event.stage !== 'string' ||
    typeof event.label !== 'string' ||
    typeof event.percent !== 'number' ||
    typeof event.status !== 'string'
  ) {
    return null;
  }
  if (!['running', 'complete', 'failed'].includes(event.status)) {
    return null;
  }
  return event as SkillImportProgressEvent;
}

export const streamSkillArchiveImportJobEvents = async (
  jobId: string,
  onEvent: (event: SkillImportProgressEvent) => void,
  signal?: AbortSignal,
): Promise<void> => {
  const response = await httpClient(
    `${getApiBaseUrl()}/skills/import/archive/jobs/${jobId}/events/stream`,
    {
      headers: getAuthorizedHeaders(),
      signal,
    },
  );

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }
  if (!response.ok || !response.body) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim() || line.startsWith(':') || !line.startsWith('data: ')) {
        continue;
      }
      const parsed = JSON.parse(line.slice(6).trim()) as unknown;
      const event = parseSkillImportProgressEvent(parsed);
      if (event) {
        onEvent(event);
      }
    }
  }
};

export const importSkillArchive = async (payload: {
  jobId: string;
  skillName: string;
  archive: File;
}): Promise<{ status: string; metadata: UserSkill }> => {
  const formData = new FormData();
  formData.append('archive', payload.archive);
  formData.append('skill_name', payload.skillName);

  const response = await httpClient(
    `${getApiBaseUrl()}/skills/import/archive/jobs/${payload.jobId}`,
    {
      method: 'POST',
      headers: getAuthorizedHeaders(),
      body: formData,
    },
  );

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }
  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return await response.json() as { status: string; metadata: UserSkill };
};
