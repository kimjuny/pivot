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
  getExtensionInstallationConfiguration,
  getAgentExtensionPackages,
  getExtensionHookExecutions,
  importExtensionBundle,
  previewExtensionBundle,
  replayExtensionHookExecution,
  fetchTaskAttachmentBlob,
  setHttpClient,
  uploadChatFile,
  uploadChatImage,
  updateExtensionInstallationConfiguration,
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

  it('imports extension bundles with authenticated multipart form data', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 9,
          scope: 'acme',
          name: 'crm',
          package_id: '@acme/crm',
          version: '0.1.0',
          display_name: 'ACME CRM',
          description: 'CRM extension',
          manifest_hash: 'hash-1',
          artifact_storage_backend: 'local_fs',
          artifact_key: 'extensions/acme/crm/0.1.0/hash-1.tar.gz',
          artifact_digest: 'artifact-hash-1',
          artifact_size_bytes: 128,
          install_root: '/tmp/extensions/acme/crm/0.1.0',
          source: 'bundle',
          trust_status: 'trusted_local',
          trust_source: 'local_import',
          hub_scope: null,
          hub_package_id: null,
          hub_package_version_id: null,
          hub_artifact_digest: null,
          installed_by: 'alice',
          status: 'active',
          created_at: '2026-03-08T00:00:00Z',
          updated_at: '2026-03-08T00:00:00Z',
          reference_summary: {
            extension_binding_count: 0,
            channel_binding_count: 0,
            web_search_binding_count: 0,
            binding_count: 0,
            release_count: 0,
            test_snapshot_count: 0,
            saved_draft_count: 0,
          },
          contribution_summary: {
            tools: [],
            skills: [],
            hooks: [],
            channel_providers: [],
            web_search_providers: [],
          },
          contribution_items: [],
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const manifest = new File(['{}'], 'manifest.json', {
      type: 'application/json',
    });
    Object.defineProperty(manifest, 'webkitRelativePath', {
      value: 'acme-bundle/manifest.json',
    });

    const result = await importExtensionBundle([manifest], { trustConfirmed: true });

    expect(result.source).toBe('bundle');
    const uploadCall = vi.mocked(fetch).mock.calls[0];
    expect(uploadCall?.[0]).toEqual(
      expect.stringContaining('/extensions/installations/import/bundle'),
    );
    const requestInit = uploadCall?.[1];
    expect(requestInit).toBeDefined();
    if (!requestInit) {
      throw new Error('Missing extension bundle request options');
    }
    expect(requestInit.method).toBe('POST');
    expect(requestInit.headers).toEqual(
      expect.objectContaining({
        Authorization: 'Bearer token-123',
      }),
    );
    expect(requestInit.body).toBeInstanceOf(FormData);
    const overwriteValue = (requestInit.body as FormData).get('overwrite_confirmed');
    expect(overwriteValue).toBe('false');
  });

  it('loads and saves extension installation configuration', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            installation_id: 9,
            package_id: '@acme/memory',
            version: '1.0.0',
            configuration_schema: {
              installation: {
                fields: [
                  {
                    key: 'base_url',
                    label: 'Base URL',
                    type: 'string',
                    description: 'Memory service URL',
                    required: true,
                    default: 'http://localhost:8765',
                    placeholder: 'http://localhost:8765',
                  },
                ],
              },
              binding: { fields: [] },
            },
            config: {
              base_url: 'http://localhost:8765',
            },
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            installation_id: 9,
            package_id: '@acme/memory',
            version: '1.0.0',
            configuration_schema: {
              installation: { fields: [] },
              binding: { fields: [] },
            },
            config: {
              base_url: 'http://mem0.local',
            },
          }),
          {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      );

    const state = await getExtensionInstallationConfiguration(9);
    expect(state.config.base_url).toBe('http://localhost:8765');

    const updated = await updateExtensionInstallationConfiguration(9, {
      base_url: 'http://mem0.local',
    });
    expect(updated.config.base_url).toBe('http://mem0.local');
    expect(fetch).toHaveBeenLastCalledWith(
      expect.stringContaining('/extensions/installations/9/configuration'),
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          config: {
            base_url: 'http://mem0.local',
          },
        }),
      }),
    );
  });

  it('previews extension bundles before local trust is granted', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          scope: 'acme',
          name: 'providers',
          package_id: '@acme/providers',
          version: '1.0.0',
          display_name: 'ACME Providers',
          description: 'Provider package',
          source: 'bundle',
          trust_status: 'unverified',
          trust_source: 'local_import',
          manifest_hash: 'hash-preview',
          contribution_summary: {
            tools: [],
            skills: [],
            hooks: [],
            channel_providers: ['acme@chat'],
            web_search_providers: ['acme@search'],
          },
          contribution_items: [],
          permissions: {
            network: {
              allow_hosts: ['api.acme.com'],
            },
          },
          existing_installation_id: null,
          existing_installation_status: null,
          identical_to_installed: false,
          requires_overwrite_confirmation: false,
          overwrite_blocked_reason: '',
          existing_reference_summary: null,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const manifest = new File(['{}'], 'manifest.json', {
      type: 'application/json',
    });
    Object.defineProperty(manifest, 'webkitRelativePath', {
      value: 'acme-bundle/manifest.json',
    });

    const result = await previewExtensionBundle([manifest]);

    expect(result.package_id).toBe('@acme/providers');
    expect(result.trust_status).toBe('unverified');
    const previewCall = vi.mocked(fetch).mock.calls[0];
    expect(previewCall?.[0]).toEqual(
      expect.stringContaining('/extensions/installations/import/bundle/preview'),
    );
    const requestInit = previewCall?.[1];
    expect(requestInit).toBeDefined();
    if (!requestInit) {
      throw new Error('Missing extension preview request options');
    }
    expect(requestInit.method).toBe('POST');
    expect(requestInit.body).toBeInstanceOf(FormData);
  });

  it('fetches agent extension package choices', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            scope: 'acme',
            name: 'crm',
            package_id: '@acme/crm',
            display_name: 'ACME CRM',
            description: 'CRM extension',
            latest_version: '0.2.0',
            active_version_count: 2,
            disabled_version_count: 0,
            has_update_available: true,
            selected_binding: null,
            versions: [],
          },
        ]),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const result = await getAgentExtensionPackages(7);

    expect(result).toHaveLength(1);
    const requestCall = vi.mocked(fetch).mock.calls[0];
    expect(requestCall?.[0]).toEqual(
      expect.stringContaining('/agents/7/extensions/packages'),
    );
    const requestInit = requestCall?.[1];
    expect(requestInit).toBeDefined();
    if (!requestInit) {
      throw new Error('Missing extension packages request options');
    }
    expect(requestInit.headers).toEqual(
      expect.objectContaining({
        Authorization: 'Bearer token-123',
      }),
    );
  });

  it('fetches extension hook executions with query filters', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            id: 1,
            session_id: 'session-1',
            task_id: 'task-1',
            trace_id: 'trace-1',
            iteration: 2,
            agent_id: 7,
            release_id: null,
            extension_package_id: '@acme/hooks',
            extension_version: '1.0.0',
            hook_event: 'iteration.after_tool_result',
            hook_callable: 'handle_task_event',
            status: 'succeeded',
            hook_context: { task_id: 'task-1' },
            effects: [{ type: 'observe' }],
            error: null,
            started_at: '2026-03-08T00:00:00Z',
            finished_at: '2026-03-08T00:00:01Z',
            duration_ms: 10,
          },
        ]),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const result = await getExtensionHookExecutions({
      taskId: 'task-1',
      traceId: 'trace-1',
      iteration: 2,
      extensionPackageId: '@acme/hooks',
      limit: 10,
    });

    expect(result).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining(
        '/extensions/hook-executions?task_id=task-1&trace_id=trace-1&iteration=2&extension_package_id=%40acme%2Fhooks&limit=10',
      ),
      expect.any(Object),
    );
  });

  it('replays one extension hook execution', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          execution_id: 1,
          extension_package_id: '@acme/hooks',
          extension_version: '1.0.0',
          hook_event: 'task.before_start',
          hook_callable: 'handle_task_event',
          status: 'succeeded',
          effects: [{ type: 'observe' }],
          error: null,
          replayed_at: '2026-03-08T00:10:00Z',
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    );

    const result = await replayExtensionHookExecution(1);

    expect(result.status).toBe('succeeded');
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/extensions/hook-executions/1/replay'),
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
