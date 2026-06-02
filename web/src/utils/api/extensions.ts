import { apiRequest, apiRequestFormData, httpClient, getAuthorizedHeaders, AuthError, getApiBaseUrl } from './core';
import { AUTH_EXPIRED_EVENT } from '../../contexts/auth-core';

export interface ExtensionInstallation {
  contribution_summary: ExtensionContributionSummary;
  contribution_items: ExtensionContributionItem[];
  reference_summary: ExtensionReferenceSummary | null;
  id: number;
  scope: string;
  name: string;
  package_id: string;
  version: string;
  display_name: string;
  description: string;
  logo_url: string | null;
  manifest_hash: string;
  artifact_storage_backend: string;
  artifact_key: string;
  artifact_digest: string;
  artifact_size_bytes: number;
  install_root: string;
  source: string;
  trust_status: string;
  trust_source: string;
  hub_scope: string | null;
  hub_package_id: string | null;
  hub_package_version_id: string | null;
  hub_artifact_digest: string | null;
  creator_id: number | null;
  use_scope: 'all' | 'selected';
  read_only: boolean;
  has_installation_configuration: boolean;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ExtensionPendingUpgrade {
  id: number;
  package_id: string;
  source_version: string;
  target_version: string;
  mode: ExtensionUpgradeMode;
  created_at?: string | null;
  affected_agent_count: number;
  affected_agent_names: string[];
  running_task_count: number;
  manifest_hash_changed?: boolean;
  added_capabilities?: ExtensionContributionItem[];
  removed_capabilities?: ExtensionContributionItem[];
}

export interface ExtensionPendingUpgradeActionResponse {
  completed: boolean;
  upgrade: ExtensionPendingUpgrade | null;
}

export interface ExtensionContributionSummary {
  tools: string[];
  skills: string[];
  hooks: string[];
  chat_surfaces?: string[];
  channel_providers: string[];
  media_providers?: string[];
  web_search_providers: string[];
}

export interface ExtensionContributionItem {
  type: string;
  key?: string | null;
  name: string;
  description: string;
  min_width?: number | null;
  icon?: string | null;
}

export interface ExtensionConfigurationField {
  key: string;
  label: string;
  type: string;
  description: string;
  required: boolean;
  default: unknown;
  placeholder: string;
}

export interface ExtensionConfigurationSection {
  fields: ExtensionConfigurationField[];
}

export interface ExtensionConfigurationSchema {
  installation: ExtensionConfigurationSection;
  binding: ExtensionConfigurationSection;
}

export interface ExtensionPackage {
  scope: string;
  name: string;
  package_id: string;
  display_name: string;
  description: string;
  logo_url: string | null;
  readme_markdown: string;
  latest_version: string;
  active_version_count: number;
  disabled_version_count: number;
  pending_upgrade?: ExtensionPendingUpgrade | null;
  versions: ExtensionInstallation[];
}

export interface ExtensionReferenceSummary {
  extension_binding_count: number;
  channel_binding_count: number;
  media_provider_binding_count?: number;
  web_search_binding_count: number;
  binding_count: number;
  release_count: number;
  test_snapshot_count: number;
  saved_draft_count: number;
}

export interface ExtensionImportPreview {
  scope: string;
  name: string;
  package_id: string;
  version: string;
  display_name: string;
  description: string;
  source: string;
  trust_status: string;
  trust_source: string;
  manifest_hash: string;
  contribution_summary: ExtensionContributionSummary;
  contribution_items: ExtensionContributionItem[];
  permissions: Record<string, unknown>;
  existing_installation_id: number | null;
  existing_installation_status: string | null;
  identical_to_installed: boolean;
  requires_overwrite_confirmation: boolean;
  overwrite_blocked_reason: string;
  existing_reference_summary: ExtensionReferenceSummary | null;
  import_mode?: 'new_install' | 'same_version_reuse' | 'same_version_overwrite' | 'upgrade';
  upgrade_from_version?: string | null;
  upgrade_impact?: {
    affected_agent_count: number;
    affected_agent_names: string[];
    running_task_count: number;
    manifest_hash_changed?: boolean;
    added_capabilities?: ExtensionContributionItem[];
    removed_capabilities?: ExtensionContributionItem[];
  } | null;
}

export type ExtensionUpgradeMode = 'safe' | 'force';

export interface ExtensionImportProgressEvent {
  event_id: number;
  job_id: string;
  stage: string;
  label: string;
  percent: number;
  status: 'running' | 'complete' | 'failed';
  detail: string | null;
  metadata: unknown;
  timestamp: string;
}

export interface ExtensionUninstallResult {
  mode: string;
  references: ExtensionReferenceSummary;
  installation: ExtensionInstallation | null;
}

export interface ExtensionHookExecution {
  id: number;
  session_id: string | null;
  task_id: string;
  trace_id: string | null;
  iteration: number;
  agent_id: number;
  release_id: number | null;
  extension_package_id: string;
  extension_version: string;
  hook_event: string;
  hook_callable: string;
  status: string;
  hook_context: Record<string, unknown> | null;
  effects: Array<Record<string, unknown>> | null;
  error: Record<string, unknown> | null;
  started_at: string;
  finished_at: string;
  duration_ms: number;
}

export interface ExtensionHookReplayResult {
  execution_id: number;
  extension_package_id: string;
  extension_version: string;
  hook_event: string;
  hook_callable: string;
  status: string;
  effects: Array<Record<string, unknown>> | null;
  error: Record<string, unknown> | null;
  replayed_at: string;
}

export interface ExtensionInstallationConfigurationState {
  installation_id: number;
  package_id: string;
  version: string;
  configuration_schema: ExtensionConfigurationSchema;
  config: Record<string, unknown>;
}

export interface ExtensionInstallationAccess {
  installation_id: number;
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface ExtensionInstallationAccessUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface ExtensionInstallationAccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface ExtensionInstallationAccessOptions {
  users: ExtensionInstallationAccessUserOption[];
  groups: ExtensionInstallationAccessGroupOption[];
}

export interface AgentExtensionBinding {
  id: number;
  agent_id: number;
  extension_installation_id: number;
  enabled: boolean;
  priority: number;
  config: Record<string, unknown>;
  status?: 'active' | 'needs_reconfiguration';
  created_at: string;
  updated_at: string;
  installation: ExtensionInstallation;
}

export interface AgentExtensionPackage {
  scope: string;
  name: string;
  package_id: string;
  display_name: string;
  description: string;
  logo_url: string | null;
  latest_version: string;
  active_version_count: number;
  disabled_version_count: number;
  has_update_available: boolean;
  selected_binding: AgentExtensionBinding | null;
  versions: ExtensionInstallation[];
}

// ---------------------------------------------------------------------------
// Package-level API functions
// ---------------------------------------------------------------------------

export const getExtensionPackages = async (): Promise<ExtensionPackage[]> => {
  return apiRequest('/extensions/packages') as Promise<ExtensionPackage[]>;
};

export const previewExtensionBundle = async (
  files: File[],
): Promise<ExtensionImportPreview> => {
  if (files.length === 0) {
    throw new Error('Choose an extension folder before importing.');
  }

  const bundleName =
    files[0]?.webkitRelativePath.split('/')[0]?.trim() || files[0]?.name || 'extension-bundle';
  const formData = new FormData();
  formData.append('bundle_name', bundleName);
  files.forEach((file) => {
    formData.append('files', file);
    formData.append('relative_paths', file.webkitRelativePath || file.name);
  });

  return apiRequestFormData(
    '/extensions/installations/import/bundle/preview',
    formData,
  ) as Promise<ExtensionImportPreview>;
};

export const importExtensionBundle = async (
  files: File[],
  options: {
    trustConfirmed: boolean;
    overwriteConfirmed?: boolean;
    upgradeMode?: ExtensionUpgradeMode;
  },
): Promise<ExtensionInstallation> => {
  if (files.length === 0) {
    throw new Error('Choose an extension folder before importing.');
  }

  const bundleName =
    files[0]?.webkitRelativePath.split('/')[0]?.trim() || files[0]?.name || 'extension-bundle';
  const formData = new FormData();
  formData.append('bundle_name', bundleName);
  formData.append('trust_confirmed', options.trustConfirmed ? 'true' : 'false');
  formData.append('overwrite_confirmed', options.overwriteConfirmed ? 'true' : 'false');
  formData.append('upgrade_mode', options.upgradeMode ?? 'force');
  files.forEach((file) => {
    formData.append('files', file);
    formData.append('relative_paths', file.webkitRelativePath || file.name);
  });

  return apiRequestFormData(
    '/extensions/installations/import/bundle',
    formData,
  ) as Promise<ExtensionInstallation>;
};

export const createExtensionBundleImportJob = async (): Promise<{ job_id: string }> => {
  return apiRequest('/extensions/installations/import/bundle/jobs', {
    method: 'POST',
  }) as Promise<{ job_id: string }>;
};

function parseExtensionImportProgressEvent(value: unknown): ExtensionImportProgressEvent | null {
  if (!value || typeof value !== 'object') {
    return null;
  }
  const event = value as Partial<ExtensionImportProgressEvent>;
  if (
    typeof event.event_id !== 'number'
    || typeof event.job_id !== 'string'
    || typeof event.stage !== 'string'
    || typeof event.label !== 'string'
    || typeof event.percent !== 'number'
    || typeof event.status !== 'string'
  ) {
    return null;
  }
  if (!['running', 'complete', 'failed'].includes(event.status)) {
    return null;
  }
  return event as ExtensionImportProgressEvent;
}

export const streamExtensionBundleImportJobEvents = async (
  jobId: string,
  onEvent: (event: ExtensionImportProgressEvent) => void,
  signal?: AbortSignal,
): Promise<void> => {
  const response = await httpClient(
    `${getApiBaseUrl()}/extensions/installations/import/bundle/jobs/${jobId}/events/stream`,
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
      const event = parseExtensionImportProgressEvent(parsed);
      if (event) {
        onEvent(event);
      }
    }
  }
};

export const importExtensionBundleWithJob = async (payload: {
  jobId: string;
  files: File[];
  trustConfirmed: boolean;
  overwriteConfirmed: boolean;
  upgradeMode: ExtensionUpgradeMode;
}): Promise<unknown> => {
  if (payload.files.length === 0) {
    throw new Error('Choose an extension folder before importing.');
  }

  const bundleName =
    payload.files[0]?.webkitRelativePath.split('/')[0]?.trim()
    || payload.files[0]?.name
    || 'extension-bundle';

  const formData = new FormData();
  formData.append('bundle_name', bundleName);
  formData.append('trust_confirmed', payload.trustConfirmed ? 'true' : 'false');
  formData.append('overwrite_confirmed', payload.overwriteConfirmed ? 'true' : 'false');
  formData.append('upgrade_mode', payload.upgradeMode);
  payload.files.forEach((file) => {
    formData.append('files', file);
    formData.append('relative_paths', file.webkitRelativePath || file.name);
  });

  return apiRequestFormData(
    `/extensions/installations/import/bundle/jobs/${payload.jobId}`,
    formData,
  );
};

export const reconcileExtensionUpgrade = async (
  pendingUpgradeId: number,
): Promise<ExtensionPendingUpgradeActionResponse> => {
  return apiRequest(`/extensions/upgrades/${pendingUpgradeId}/reconcile`, {
    method: 'POST',
  }) as Promise<ExtensionPendingUpgradeActionResponse>;
};

export const forceExtensionUpgrade = async (
  pendingUpgradeId: number,
): Promise<ExtensionPendingUpgradeActionResponse> => {
  return apiRequest(`/extensions/upgrades/${pendingUpgradeId}/force`, {
    method: 'POST',
  }) as Promise<ExtensionPendingUpgradeActionResponse>;
};

export const updateExtensionInstallationStatus = async (
  installationId: number,
  status: 'active' | 'disabled',
): Promise<ExtensionInstallation> => {
  return apiRequest(`/extensions/installations/${installationId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  }) as Promise<ExtensionInstallation>;
};

export const getExtensionInstallationReferences = async (
  installationId: number,
): Promise<ExtensionReferenceSummary> => {
  return apiRequest(
    `/extensions/installations/${installationId}/references`,
  ) as Promise<ExtensionReferenceSummary>;
};

export const uninstallExtensionInstallation = async (
  installationId: number,
): Promise<ExtensionUninstallResult> => {
  return apiRequest(`/extensions/installations/${installationId}`, {
    method: 'DELETE',
  }) as Promise<ExtensionUninstallResult>;
};

export const getExtensionInstallationAccess = async (
  installationId: number,
): Promise<ExtensionInstallationAccess> => {
  return apiRequest(
    `/extensions/installations/${installationId}/access`,
  ) as Promise<ExtensionInstallationAccess>;
};

export const getExtensionInstallationAccessOptions = async (
  installationId: number,
): Promise<ExtensionInstallationAccessOptions> => {
  return apiRequest(
    `/extensions/installations/${installationId}/access-options`,
  ) as Promise<ExtensionInstallationAccessOptions>;
};

export const updateExtensionInstallationAccess = async (
  installationId: number,
  access: Omit<ExtensionInstallationAccess, 'installation_id'>,
): Promise<ExtensionInstallationAccess> => {
  return apiRequest(`/extensions/installations/${installationId}/access`, {
    method: 'PUT',
    body: JSON.stringify({
      use_scope: access.use_scope,
      use_user_ids: access.use_user_ids,
      use_group_ids: access.use_group_ids,
      edit_user_ids: access.edit_user_ids,
      edit_group_ids: access.edit_group_ids,
    }),
  }) as Promise<ExtensionInstallationAccess>;
};

export const getExtensionInstallationConfiguration = async (
  installationId: number,
): Promise<ExtensionInstallationConfigurationState> => {
  return apiRequest(
    `/extensions/installations/${installationId}/configuration`,
  ) as Promise<ExtensionInstallationConfigurationState>;
};

export const updateExtensionInstallationConfiguration = async (
  installationId: number,
  config: Record<string, unknown>,
): Promise<ExtensionInstallationConfigurationState> => {
  return apiRequest(`/extensions/installations/${installationId}/configuration`, {
    method: 'PUT',
    body: JSON.stringify({ config }),
  }) as Promise<ExtensionInstallationConfigurationState>;
};

export const getExtensionHookExecutions = async (filters?: {
  sessionId?: string;
  taskId?: string;
  traceId?: string;
  iteration?: number;
  extensionPackageId?: string;
  hookEvent?: string;
  limit?: number;
}): Promise<ExtensionHookExecution[]> => {
  const params = new URLSearchParams();
  if (filters?.sessionId) {
    params.set('session_id', filters.sessionId);
  }
  if (filters?.taskId) {
    params.set('task_id', filters.taskId);
  }
  if (filters?.traceId) {
    params.set('trace_id', filters.traceId);
  }
  if (typeof filters?.iteration === 'number') {
    params.set('iteration', String(filters.iteration));
  }
  if (filters?.extensionPackageId) {
    params.set('extension_package_id', filters.extensionPackageId);
  }
  if (filters?.hookEvent) {
    params.set('hook_event', filters.hookEvent);
  }
  if (typeof filters?.limit === 'number') {
    params.set('limit', String(filters.limit));
  }
  const query = params.toString();
  return apiRequest(
    `/extensions/hook-executions${query ? `?${query}` : ''}`,
  ) as Promise<ExtensionHookExecution[]>;
};

export const replayExtensionHookExecution = async (
  executionId: number,
): Promise<ExtensionHookReplayResult> => {
  return apiRequest(`/extensions/hook-executions/${executionId}/replay`, {
    method: 'POST',
  }) as Promise<ExtensionHookReplayResult>;
};

export const getAgentExtensionPackages = async (
  agentId: number,
): Promise<AgentExtensionPackage[]> => {
  return apiRequest(
    `/agents/${agentId}/extensions/packages`,
  ) as Promise<AgentExtensionPackage[]>;
};

export const upsertAgentExtensionBinding = async (
  agentId: number,
  extensionInstallationId: number,
  payload: {
    enabled?: boolean;
    priority?: number;
    config?: Record<string, unknown>;
  },
): Promise<AgentExtensionBinding> => {
  return apiRequest(
    `/agents/${agentId}/extensions/${extensionInstallationId}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
  ) as Promise<AgentExtensionBinding>;
};

export const confirmAgentExtensionBinding = async (
  agentId: number,
  bindingId: number,
): Promise<AgentExtensionBinding> => {
  return apiRequest(
    `/agents/${agentId}/extensions/${bindingId}/confirm`,
    { method: 'POST' },
  ) as Promise<AgentExtensionBinding>;
};

export const replaceAgentExtensionBindings = async (
  agentId: number,
  bindings: Array<{
    extension_installation_id: number;
    enabled: boolean;
    priority: number;
    config: Record<string, unknown>;
  }>,
): Promise<AgentExtensionBinding[]> => {
  return apiRequest(`/agents/${agentId}/extensions`, {
    method: 'PUT',
    body: JSON.stringify({ bindings }),
  }) as Promise<AgentExtensionBinding[]>;
};

export const deleteAgentExtensionBinding = async (
  agentId: number,
  extensionInstallationId: number,
): Promise<void> => {
  await apiRequest(`/agents/${agentId}/extensions/${extensionInstallationId}`, {
    method: 'DELETE',
  });
};
