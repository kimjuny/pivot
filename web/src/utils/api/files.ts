import { httpClient, getAuthorizedHeaders, AuthError, getApiBaseUrl, type FileUploadSource } from './core';
import { AUTH_EXPIRED_EVENT } from '../../contexts/auth-core';
import type { ChatFileAsset } from './sessions';

export const uploadChatFile = async (
  file: File,
  source: FileUploadSource,
  signal?: AbortSignal
): Promise<ChatFileAsset> => {
  const url = `${getApiBaseUrl()}/files/uploads`;
  const headers = getAuthorizedHeaders();
  const formData = new FormData();
  formData.append('file', file);
  formData.append('source', source);

  try {
    const response = await httpClient(url, {
      method: 'POST',
      headers,
      body: formData,
      signal,
    });

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }

    return await response.json() as ChatFileAsset;
  } catch (error) {
    console.error(`File upload failed for ${file.name}:`, error);
    throw error;
  }
};

export const uploadChatImage = async (
  file: File,
  source: FileUploadSource,
  signal?: AbortSignal
): Promise<ChatFileAsset> => {
  return uploadChatFile(file, source, signal);
};

export const deleteChatFile = async (fileId: string): Promise<void> => {
  const url = `${getApiBaseUrl()}/files/${fileId}`;
  const headers = getAuthorizedHeaders();

  try {
    const response = await httpClient(url, {
      method: 'DELETE',
      headers,
    });

    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      throw new AuthError('Authentication expired. Please log in again.');
    }

    if (!response.ok && response.status !== 204) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }
  } catch (error) {
    console.error(`File deletion failed for ${fileId}:`, error);
    throw error;
  }
};

export const deleteChatImage = async (fileId: string): Promise<void> => {
  await deleteChatFile(fileId);
};

export const fetchChatFileBlob = async (
  fileId: string,
  signal?: AbortSignal
): Promise<Blob> => {
  const url = `${getApiBaseUrl()}/files/${fileId}/content`;
  const headers = getAuthorizedHeaders();

  const response = await httpClient(url, {
    method: 'GET',
    headers,
    signal,
  });

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }

  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return await response.blob();
};

export const fetchChatImageBlob = async (
  fileId: string,
  signal?: AbortSignal
): Promise<Blob> => {
  return fetchChatFileBlob(fileId, signal);
};

export const fetchTaskAttachmentBlob = async (
  attachmentId: string,
  signal?: AbortSignal
): Promise<Blob> => {
  const url = `${getApiBaseUrl()}/task-attachments/${attachmentId}/content`;
  const headers = getAuthorizedHeaders();

  const response = await httpClient(url, {
    method: 'GET',
    headers,
    signal,
  });

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new AuthError('Authentication expired. Please log in again.');
  }

  if (!response.ok) {
    const errorData = await response.json() as { detail?: string };
    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
  }

  return await response.blob();
};
