import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../contexts/auth-core', () => ({
  getAuthToken: () => 'token-123',
  isTokenValid: () => true,
  AUTH_EXPIRED_EVENT: 'auth-expired',
}));

import {
  deleteChatFile,
  deleteChatImage,
  fetchChatFileBlob,
  fetchChatImageBlob,
  fetchTaskAttachmentBlob,
  setHttpClient,
  uploadChatFile,
  uploadChatImage,
  updateSession,
} from './api';

describe('chat file api helpers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    setHttpClient(fetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setHttpClient(fetch);
    vi.restoreAllMocks();
  });

  it('uploads chat files with auth and form data', async () => {
    const payload = {
      file_id: 'file-1',
      kind: 'document',
      source: 'local',
      original_name: 'brief.pdf',
      mime_type: 'application/pdf',
      format: 'PDF',
      extension: 'pdf',
      size_bytes: 12,
      width: 0,
      height: 0,
      page_count: 2,
      can_extract_text: true,
      suspected_scanned: false,
      text_encoding: null,
      session_id: null,
      task_id: null,
      created_at: '2026-03-08T00:00:00Z',
      expires_at: '2026-03-08T02:00:00Z',
    };
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      })
    );

    const file = new File(['hello'], 'brief.pdf', { type: 'application/pdf' });
    const result = await uploadChatFile(file, 'local');

    expect(result.file_id).toBe('file-1');
    const uploadCall = vi.mocked(fetch).mock.calls[0];
    expect(uploadCall?.[0]).toEqual(expect.stringContaining('/files/uploads'));
    const requestInit = uploadCall?.[1];
    expect(requestInit).toBeDefined();
    if (!requestInit) {
      throw new Error('Missing upload request options');
    }
    expect(requestInit.method).toBe('POST');
    expect(requestInit.headers).toEqual(expect.objectContaining({
      Authorization: 'Bearer token-123',
    }));
    expect(requestInit.body).toBeInstanceOf(FormData);
  });

  it('keeps legacy image upload helper wired to the generic endpoint', async () => {
    const payload = {
      file_id: 'file-2',
      kind: 'image',
      source: 'local',
      original_name: 'diagram.png',
      mime_type: 'image/png',
      format: 'PNG',
      extension: 'png',
      size_bytes: 12,
      width: 3,
      height: 4,
      page_count: null,
      can_extract_text: false,
      suspected_scanned: false,
      text_encoding: null,
      session_id: null,
      task_id: null,
      created_at: '2026-03-08T00:00:00Z',
      expires_at: '2026-03-08T02:00:00Z',
    };
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      })
    );

    const file = new File(['hello'], 'diagram.png', { type: 'image/png' });
    const result = await uploadChatImage(file, 'local');

    expect(result.kind).toBe('image');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/files/uploads'),
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('deletes pending chat files', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));

    await expect(deleteChatFile('file-1')).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/files/file-1'),
      expect.objectContaining({
        method: 'DELETE',
      })
    );
  });

  it('keeps legacy image deletion helper working', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));

    await expect(deleteChatImage('file-2')).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/files/file-2'),
      expect.objectContaining({
        method: 'DELETE',
      })
    );
  });

  it('fetches chat image blobs for attachment previews', async () => {
    const blob = new Blob(['image-bytes'], { type: 'image/png' });
    vi.mocked(fetch).mockResolvedValue(new Response(blob, { status: 200 }));

    const result = await fetchChatImageBlob('file-1');

    expect(result.type).toBe('image/png');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/files/file-1/content'),
      expect.objectContaining({
        method: 'GET',
      })
    );
  });

  it('fetches generic file blobs for attachments', async () => {
    const blob = new Blob(['document-bytes'], { type: 'application/pdf' });
    vi.mocked(fetch).mockResolvedValue(new Response(blob, { status: 200 }));

    const result = await fetchChatFileBlob('file-3');

    expect(result.type).toBe('application/pdf');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/files/file-3/content'),
      expect.objectContaining({
        method: 'GET',
      })
    );
  });

  it('fetches assistant attachment blobs for preview dialogs', async () => {
    const blob = new Blob(['markdown-bytes'], { type: 'text/markdown' });
    vi.mocked(fetch).mockResolvedValue(new Response(blob, { status: 200 }));

    const result = await fetchTaskAttachmentBlob('attachment-1');

    expect(result.type).toBe('text/markdown');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/task-attachments/attachment-1/content'),
      expect.objectContaining({
        method: 'GET',
      })
    );
  });

  it('updates session sidebar metadata with a patch request', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 1,
          session_id: 'session-1',
          agent_id: 7,
          user: 'default',
          status: 'active',
          title: 'Pinned thread',
          is_pinned: true,
          created_at: '2026-03-08T00:00:00Z',
          updated_at: '2026-03-08T00:10:00Z',
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }
      )
    );

    const result = await updateSession('session-1', {
      title: 'Pinned thread',
      is_pinned: true,
    });

    expect(result.is_pinned).toBe(true);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/sessions/session-1'),
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({
          title: 'Pinned thread',
          is_pinned: true,
        }),
      })
    );
  });
});
