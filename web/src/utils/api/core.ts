import { getAuthToken, isTokenValid, AUTH_EXPIRED_EVENT } from '../../contexts/auth-core';

// ---------------------------------------------------------------------------
// API base URL
// ---------------------------------------------------------------------------

let runtimeApiBaseUrl: string | null = null;

export function setApiBaseUrl(url: string): void {
  runtimeApiBaseUrl = url;
}

export function getApiBaseUrl(): string {
  if (import.meta.env.DEV) return '/api';
  if (runtimeApiBaseUrl) return runtimeApiBaseUrl;
  return import.meta.env.VITE_API_BASE_URL || 'http://localhost:8003/api';
}

// ---------------------------------------------------------------------------
// Pluggable HTTP client
// ---------------------------------------------------------------------------

let _fetch: typeof fetch = fetch;

export function setHttpClient(client: typeof fetch): void {
  _fetch = client;
}

export function httpClient(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  return _fetch(input, init);
}

// ---------------------------------------------------------------------------
// Request helpers
// ---------------------------------------------------------------------------

export interface RequestOptions {
  headers?: Record<string, string>;
  method?: string;
  body?: BodyInit | null;
  skipAuth?: boolean;
  skipTokenCheck?: boolean;
}

export type FileUploadSource = 'local' | 'clipboard';

export class AuthError extends Error {
  constructor(message: string = 'Authentication required') {
    super(message);
    this.name = 'AuthError';
  }
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  code: string | null;

  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code =
      detail && typeof detail === 'object' && 'code' in detail
        ? String((detail as { code: unknown }).code)
        : null;
  }
}

export const apiRequest = async (endpoint: string, options: RequestOptions = {}): Promise<unknown> => {
  const url = `${getApiBaseUrl()}${endpoint}`;
  const isMultipartBody = options.body instanceof FormData;

  const headers: Record<string, string> = {
    ...options.headers,
  };
  if (!isMultipartBody && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  if (!options.skipAuth) {
    if (!options.skipTokenCheck && !isTokenValid()) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Token expired or invalid. Please log in again.');
    }

    const token = getAuthToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  const config: RequestInit = {
    headers,
    ...options,
  };

  try {
    const response = await httpClient(url, config);

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok) {
      const errorData = await response.json() as { detail?: unknown };
      const detail = errorData.detail;
      const message =
        typeof detail === 'string'
          ? detail
          : detail && typeof detail === 'object' && 'message' in detail
            ? String((detail as { message: unknown }).message)
            : `HTTP error! status: ${response.status}`;
      throw new ApiError(response.status, detail, message);
    }

    if (response.status === 204) {
      return null;
    }

    return await response.json();
  } catch (error) {
    console.error(`API request failed for ${url}:`, error);
    throw error;
  }
};

export const apiRequestFormData = async (
  endpoint: string,
  formData: FormData,
): Promise<unknown> => {
  return apiRequest(endpoint, {
    method: 'POST',
    body: formData,
  });
};

export const getAuthorizedHeaders = (): Record<string, string> => {
  if (!isTokenValid()) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Token expired or invalid. Please log in again.');
  }

  const headers: Record<string, string> = {};
  const token = getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
};

// ---------------------------------------------------------------------------
// System status
// ---------------------------------------------------------------------------

export interface StorageStatus {
  requested_profile: string;
  active_profile: string;
  object_storage_backend: string;
  posix_workspace_backend: string;
  fallback_reason: string | null;
  backend_workspace_root: string;
  external_posix_root: string | null;
  external_host_posix_root: string | null;
  external_posix_root_exists: boolean;
  external_filer_reachable: boolean | null;
  external_namespace_shared: boolean | null;
  external_readiness_reason: string | null;
}

export const getStorageStatus = async (): Promise<StorageStatus> => {
  return apiRequest('/system/storage-status') as Promise<StorageStatus>;
};

// ---------------------------------------------------------------------------
// Shared access-control types (reused by llms, tools, skills)
// ---------------------------------------------------------------------------

export interface AccessUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface AccessGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

export interface AccessOptions {
  users: AccessUserOption[];
  groups: AccessGroupOption[];
}
