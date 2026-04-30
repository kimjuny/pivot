import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Inbox, Loader2, Plus, RefreshCcw } from "@/lib/lucide";
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import ConfigFieldGroup from './ConfigFieldGroup';
import DraggableDialog from './DraggableDialog';
import { MediaProviderBadge } from './MediaProviderBadge';
import { ProviderMetadataBadges } from './ProviderMetadataBadges';
import { formatProviderExtensionLabel } from '@/utils/providerMetadata';
import {
  createAgentMediaProviderBinding,
  testAgentMediaProviderBinding,
  testMediaProviderDraft,
  updateAgentMediaProviderBinding,
  type MediaProviderBinding,
  type MediaProviderCatalogItem,
  type MediaProviderManifest,
} from '@/utils/api';

/**
 * Convert runtime config values into stable form input strings.
 * Why: object stringification would otherwise produce useless "[object Object]" output.
 */
function toFieldValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '';
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return JSON.stringify(value);
}

/**
 * Build form defaults from manifest fields before merging saved binding data.
 */
function getDefaultFieldValues(
  fields: MediaProviderManifest['config_schema'],
): Record<string, string> {
  return Object.fromEntries(
    fields
      .filter((field) => field.default_value !== null && field.default_value !== undefined)
      .map((field) => [field.key, toFieldValue(field.default_value)])
  );
}

interface MediaGenerationBindingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  catalog: MediaProviderCatalogItem[];
  configuredProviderKeys: string[];
  initialBinding?: MediaProviderBinding | null;
  onSaved: () => Promise<void> | void;
}

/**
 * Media-provider editor used for both create and edit flows.
 */
function MediaGenerationBindingDialog({
  open,
  onOpenChange,
  agentId,
  catalog,
  configuredProviderKeys,
  initialBinding,
  onSaved,
}: MediaGenerationBindingDialogProps) {
  const navigate = useNavigate();
  const [providerKey, setProviderKey] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [authConfig, setAuthConfig] = useState<Record<string, string>>({});
  const [runtimeConfig, setRuntimeConfig] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const manifest = useMemo<MediaProviderManifest | null>(() => {
    if (!providerKey) {
      return null;
    }
    return catalog.find((item) => item.manifest.key === providerKey)?.manifest ?? null;
  }, [catalog, providerKey]);
  const extensionLabel = useMemo(
    () => (
      manifest
        ? formatProviderExtensionLabel(
            manifest.extension_display_name,
            manifest.extension_name,
            manifest.extension_version,
          )
        : null
    ),
    [manifest],
  );
  const disabledReason = initialBinding?.disabled_reason ?? null;

  const selectableCatalog = useMemo(() => {
    if (initialBinding) {
      return catalog;
    }
    return catalog.filter((item) => !configuredProviderKeys.includes(item.manifest.key));
  }, [catalog, configuredProviderKeys, initialBinding]);

  useEffect(() => {
    if (!open) {
      return;
    }

    if (initialBinding) {
      const nextManifest =
        catalog.find((item) => item.manifest.key === initialBinding.provider_key)?.manifest ?? null;
      setProviderKey(initialBinding.provider_key);
      setEnabled(initialBinding.enabled);
      setAuthConfig({
        ...(nextManifest ? getDefaultFieldValues(nextManifest.auth_schema) : {}),
        ...initialBinding.auth_config,
      });
      setRuntimeConfig(
        {
          ...(nextManifest ? getDefaultFieldValues(nextManifest.config_schema) : {}),
          ...Object.fromEntries(
            Object.entries(initialBinding.runtime_config).map(([key, value]) => [key, toFieldValue(value)])
          ),
        }
      );
      setTestMessage(initialBinding.last_health_message);
      return;
    }

    const firstManifest = selectableCatalog[0]?.manifest;
    setProviderKey(firstManifest?.key ?? '');
    setEnabled(true);
    setAuthConfig(firstManifest ? getDefaultFieldValues(firstManifest.auth_schema) : {});
    setRuntimeConfig(firstManifest ? getDefaultFieldValues(firstManifest.config_schema) : {});
    setTestMessage(null);
  }, [catalog, initialBinding, open, selectableCatalog]);

  const handleFieldChange = (
    scope: 'auth' | 'runtime',
    fieldKey: string,
    value: string
  ) => {
    if (scope === 'auth') {
      setAuthConfig((prev) => ({ ...prev, [fieldKey]: value }));
      return;
    }
    setRuntimeConfig((prev) => ({ ...prev, [fieldKey]: value }));
  };

  const handleProviderChange = (nextProviderKey: string) => {
    const nextManifest =
      catalog.find((item) => item.manifest.key === nextProviderKey)?.manifest ?? null;
    setProviderKey(nextProviderKey);
    setAuthConfig(nextManifest ? getDefaultFieldValues(nextManifest.auth_schema) : {});
    setRuntimeConfig(nextManifest ? getDefaultFieldValues(nextManifest.config_schema) : {});
    setTestMessage(null);
  };

  const handleSave = async () => {
    if (!manifest) {
      toast.error('Please select a media provider');
      return;
    }

    setIsSaving(true);
    try {
      const payload = {
        enabled,
        auth_config: authConfig,
        runtime_config: runtimeConfig,
      };

      if (initialBinding) {
        await updateAgentMediaProviderBinding(initialBinding.id, payload);
      } else {
        await createAgentMediaProviderBinding(agentId, {
          provider_key: manifest.key,
          ...payload,
        });
      }

      await onSaved();
      toast.success(initialBinding ? 'Media provider updated' : 'Media provider created');
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save media provider');
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    if (!manifest) {
      toast.error('Please select a media provider');
      return;
    }

    setIsTesting(true);
    try {
      const result = initialBinding
        ? await testAgentMediaProviderBinding(initialBinding.id)
        : await testMediaProviderDraft(manifest.key, {
            auth_config: authConfig,
            runtime_config: runtimeConfig,
          });
      setTestMessage(result.result.message);
      toast.success(result.result.message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to test media provider';
      setTestMessage(message);
      toast.error(message);
    } finally {
      setIsTesting(false);
    }
  };

  const hasNoAvailableProviders = !initialBinding && selectableCatalog.length === 0;

  const handleOpenMediaProvidersList = () => {
    navigate('/studio/connections/media-generation');
    onOpenChange(false);
  };

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title={initialBinding ? 'Edit Media Provider' : 'Add Media Provider'}
      size="default"
    >
      <div className="flex h-full flex-col">
        {hasNoAvailableProviders ? (
          <div className="flex flex-1 items-center justify-center px-4 py-6">
            <Empty className="min-h-64 gap-4 p-4 md:p-6">
              <EmptyHeader className="gap-1.5">
                <EmptyMedia variant="icon">
                  <Inbox className="size-5" />
                </EmptyMedia>
                <EmptyTitle className="text-base">No media providers available</EmptyTitle>
                <EmptyDescription className="text-xs/relaxed">
                  Add or install a media provider first, then bind it to this agent.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button type="button" size="sm" onClick={handleOpenMediaProvidersList}>
                  <Plus className="size-3.5" />
                  Go to Media Providers
                </Button>
              </EmptyContent>
            </Empty>
          </div>
        ) : (
        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
          {!initialBinding && (
            <div className="space-y-2">
              <Label htmlFor="media-provider">Provider</Label>
              <Select value={providerKey} onValueChange={handleProviderChange}>
                <SelectTrigger id="media-provider">
                  {manifest ? (
                    <MediaProviderBadge
                      name={manifest.name}
                    />
                  ) : (
                    <SelectValue placeholder="Select a provider" />
                  )}
                </SelectTrigger>
                <SelectContent>
                  {selectableCatalog.map((item) => (
                    <SelectItem key={item.manifest.key} value={item.manifest.key}>
                      <MediaProviderBadge
                        name={item.manifest.name}
                      />
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {manifest && (
            <>
              <div className="rounded-lg border border-border px-3 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-foreground">{manifest.name}</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {manifest.description}
                    </div>
                  </div>
                  <a
                    href={manifest.docs_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  >
                    Docs
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
                <div className="mt-3">
                  <ProviderMetadataBadges
                    mediaType={manifest.media_type}
                    visibility={manifest.visibility}
                    status={manifest.status}
                  />
                </div>
                {extensionLabel ? (
                  <div className="mt-2 text-xs text-muted-foreground">
                    Package: {extensionLabel}
                  </div>
                ) : null}
              </div>

              <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
                <div>
                  <div className="text-sm font-medium text-foreground">Enabled</div>
                  <div className="text-xs text-muted-foreground">
                    Disable this provider without deleting its credentials.
                  </div>
                </div>
                <Switch checked={enabled} onCheckedChange={setEnabled} />
              </div>

              {disabledReason ? (
                <div className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground">
                  {disabledReason}
                </div>
              ) : null}

              <ConfigFieldGroup
                title="Credentials"
                description="These fields are defined by the provider manifest and stored only on this agent."
                fields={manifest.auth_schema}
                values={authConfig}
                onChange={(fieldKey, value) => handleFieldChange('auth', fieldKey, value)}
              />

              {manifest.config_schema.length > 0 && (
                <ConfigFieldGroup
                  title="Runtime Config"
                  description="Optional provider-specific behavior settings."
                  fields={manifest.config_schema}
                  values={runtimeConfig}
                  onChange={(fieldKey, value) => handleFieldChange('runtime', fieldKey, value)}
                />
              )}

              <div className="space-y-2">
                <div className="text-sm font-medium text-foreground">Setup Notes</div>
                <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
                  {manifest.setup_steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              </div>

              {manifest.supported_operations.length > 0 && (
                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground">Supported Operations</div>
                  <div className="flex flex-wrap gap-1.5">
                    {manifest.supported_operations.map((operation) => (
                      <span
                        key={operation}
                        className="rounded bg-muted px-2 py-1 text-[11px] text-muted-foreground"
                      >
                        {operation}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {manifest.supported_parameters.length > 0 && (
                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground">Supported Tool Parameters</div>
                  <div className="flex flex-wrap gap-1.5">
                    {manifest.supported_parameters.map((parameter) => (
                      <span
                        key={parameter}
                        className="rounded bg-muted px-2 py-1 text-[11px] text-muted-foreground"
                      >
                        {parameter}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {testMessage && (
                <div className="rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground">
                  {testMessage}
                </div>
              )}
            </>
          )}
        </div>
        )}

        <Separator />

        <div className="flex items-center justify-between gap-3 px-4 py-3">
          {!hasNoAvailableProviders ? (
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleTest()}
              disabled={isTesting || !manifest}
            >
              {isTesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              Test Connection
            </Button>
          ) : (
            <div />
          )}

          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              {hasNoAvailableProviders ? 'Close' : 'Cancel'}
            </Button>
            {!hasNoAvailableProviders && (
              <Button type="button" onClick={() => void handleSave()} disabled={isSaving || !manifest}>
                {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Save
              </Button>
            )}
          </div>
        </div>
      </div>
    </DraggableDialog>
  );
}

export default MediaGenerationBindingDialog;
