import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../contexts/auth-core', () => ({
  getAuthToken: () => 'token-123',
  isTokenValid: () => true,
  AUTH_EXPIRED_EVENT: 'auth-expired',
}));

import { deleteChatImage, fetchChatImageBlob, uploadChatImage } from './api';

describe('chat image api helpers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('uploads chat images with auth and form data', async () => {
    const payload = {
      file_id: 'file-1',
      source: 'local',
      original_name: 'diagram.png',
      mime_type: 'image/png',
      format: 'PNG',
      extension: 'png',
      size_bytes: 12,
      width: 3,
      height: 4,
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

    expect(result.file_id).toBe('file-1');
    const uploadCall = vi.mocked(fetch).mock.calls[0];
    expect(uploadCall?.[0]).toEqual(expect.stringContaining('/files/images'));
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

  it('deletes pending chat images', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }));

    await expect(deleteChatImage('file-1')).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/files/file-1'),
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
});
