import { apiRequest } from './core';

export interface WorkspaceFileItem {
  path: string;
  name: string;
}

export const searchWorkspaceFiles = async (params: {
  session_id: string;
  q?: string;
  limit?: number;
}): Promise<{ files: WorkspaceFileItem[] }> => {
  const paramsObj = new URLSearchParams();
  if (params.q) {
    paramsObj.set("q", params.q);
  }
  if (params.limit) {
    paramsObj.set("limit", String(params.limit));
  }
  const query = paramsObj.toString();
  const url = `/sessions/${encodeURIComponent(params.session_id)}/workspace/search${query ? `?${query}` : ""}`;
  return apiRequest(url) as Promise<{ files: WorkspaceFileItem[] }>;
};
