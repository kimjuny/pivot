import { apiRequest } from './core';

export interface SurfaceFilesApiResponse {
  directory_url: string;
  text_url: string;
  blob_url: string;
  tree_url: string;
  content_url: string;
}

export interface PreviewEndpointResponse {
  preview_id: string;
  session_id: string;
  workspace_id: string;
  workspace_logical_root: string;
  title: string;
  port: number;
  path: string;
  has_launch_recipe: boolean;
  proxy_url: string;
  created_at: string;
}

/**
 * Structured operation intent emitted by a surface to the host.
 *
 * A surface declares an intent (e.g. "inpaint this image"); the host routes
 * it to the chat composer for the user to review before the agent acts on it.
 * `operation` and input `role` are open strings — only the agent runtime
 * interprets their semantics.
 */
export interface OperationRefInputPayload {
  /** Workspace-relative path of the referenced file. */
  path: string;
  /** Open semantic role, e.g. "reference", "mask", "subject". */
  role: string;
}

export interface OperationRefPayload {
  refId: string;
  sourceSurfaceKey: string;
  operation: string;
  operationLabel: string;
  inputs: OperationRefInputPayload[];
  params?: Record<string, unknown>;
}

export interface ReconnectPreviewEndpointResponse {
  preview: PreviewEndpointResponse;
  available_previews: PreviewEndpointResponse[];
  active_preview_id: string | null;
}

export interface DevSurfaceBootstrapResponse {
  surface_session_id: string;
  surface_token: string;
  mode: 'dev';
  surface_key: string;
  display_name: string;
  agent_id: number;
  session_id: string;
  workspace_id: string;
  workspace_logical_root: string;
  dev_server_url: string;
  capabilities: string[];
  files_api: SurfaceFilesApiResponse;
}

export interface DevSurfaceSessionResponse {
  surface_session_id: string;
  surface_token: string;
  surface_key: string;
  display_name: string;
  agent_id: number;
  session_id: string;
  workspace_id: string;
  workspace_logical_root: string;
  dev_server_url: string;
  created_at: string;
  bootstrap: DevSurfaceBootstrapResponse;
}

export interface InstalledSurfaceBootstrapResponse {
  surface_session_id: string;
  surface_token: string;
  mode: 'installed';
  surface_key: string;
  display_name: string;
  package_id: string;
  extension_installation_id: number;
  agent_id: number;
  session_id: string;
  workspace_id: string;
  workspace_logical_root: string;
  runtime_url: string;
  capabilities: string[];
  files_api: SurfaceFilesApiResponse;
}

export interface InstalledSurfaceSessionResponse {
  surface_session_id: string;
  surface_token: string;
  surface_key: string;
  display_name: string;
  package_id: string;
  extension_installation_id: number;
  agent_id: number;
  session_id: string;
  workspace_id: string;
  workspace_logical_root: string;
  runtime_url: string;
  created_at: string;
  bootstrap: InstalledSurfaceBootstrapResponse;
}

export const createDevSurfaceSession = async (payload: {
  sessionId: string;
  surfaceKey: string;
  devServerUrl: string;
  displayName?: string | null;
}): Promise<DevSurfaceSessionResponse> => {
  return apiRequest('/chat-surfaces/dev-sessions', {
    method: 'POST',
    body: JSON.stringify({
      session_id: payload.sessionId,
      surface_key: payload.surfaceKey,
      dev_server_url: payload.devServerUrl,
      display_name: payload.displayName ?? null,
    }),
  }) as Promise<DevSurfaceSessionResponse>;
};

export const createInstalledSurfaceSession = async (payload: {
  sessionId: string;
  extensionInstallationId: number;
  surfaceKey: string;
}): Promise<InstalledSurfaceSessionResponse> => {
  return apiRequest('/chat-surfaces/installed-sessions', {
    method: 'POST',
    body: JSON.stringify({
      session_id: payload.sessionId,
      extension_installation_id: payload.extensionInstallationId,
      surface_key: payload.surfaceKey,
    }),
  }) as Promise<InstalledSurfaceSessionResponse>;
};

export const createPreviewEndpoint = async (payload: {
  sessionId: string;
  previewName: string;
  startServer: string;
  port: number;
  path?: string | null;
  cwd?: string | null;
}): Promise<PreviewEndpointResponse> => {
  return apiRequest('/chat-previews', {
    method: 'POST',
    body: JSON.stringify({
      session_id: payload.sessionId,
      preview_name: payload.previewName,
      start_server: payload.startServer,
      port: payload.port,
      path: payload.path ?? '/',
      cwd: payload.cwd ?? '.',
    }),
  }) as Promise<PreviewEndpointResponse>;
};

export const getPreviewEndpoints = async (
  sessionId: string,
): Promise<PreviewEndpointResponse[]> => {
  const encodedSessionId = encodeURIComponent(sessionId);
  return apiRequest(
    `/chat-previews?session_id=${encodedSessionId}`,
  ) as Promise<PreviewEndpointResponse[]>;
};

export const reconnectSurfacePreview = async (payload: {
  surfaceSessionId: string;
  previewId: string;
  surfaceToken: string;
}): Promise<ReconnectPreviewEndpointResponse> => {
  const nextUrl = new URL(
    `/api/chat-surfaces/sessions/${payload.surfaceSessionId}/previews/${payload.previewId}/connect`,
    window.location.origin,
  );
  nextUrl.searchParams.set('surface_token', payload.surfaceToken);
  return apiRequest(nextUrl.pathname + nextUrl.search, {
    method: 'POST',
    skipAuth: true,
    skipTokenCheck: true,
  }) as Promise<ReconnectPreviewEndpointResponse>;
};
