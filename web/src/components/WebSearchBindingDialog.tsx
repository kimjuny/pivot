import { useEffect, useMemo, useState } from 'react';
import { ExternalLink, Loader2, RefreshCcw } from "@/lib/lucide";
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import ConfigFieldGroup from './ConfigFieldGroup';
import DraggableDialog from './DraggableDialog';
import { ProviderMetadataBadges } from './ProviderMetadataBadges';
import { WebSearchProviderBadge } from './WebSearchProviderBadge';
import { formatProviderExtensionLabel } from '@/utils/providerMetadata';
import {
  createAgentWebSearchBinding,
  testAgentWebSearchBinding,
  testWebSearchProviderDraft,
  updateAgentWebSearchBinding,
  type WebSearchBinding,
  type WebSearchCatalogItem,
  type WebSearchProviderManifest,
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

interface WebSearchBindingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  catalog: WebSearchCatalogItem[];
  configuredProviderKeys: string[];
  initialBinding?: WebSearchBinding | null;
  onSaved: () => Promise<void> | void;
}

/**
 * Web-search provider editor used for both create and edit flows.
 */
function WebSearchBindingDialog({
  open,
  onOpenChange,
  agentId,
  catalog,
  configuredProviderKeys,
  initialBinding,
  onSaved,
}: WebSearchBindingDialogProps) {
  const [providerKey, setProviderKey] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [authConfig, setAuthConfig] = useState<Record<string, string>>({});
  const [runtimeConfig, setRuntimeConfig] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const manifest = useMemo<WebSearchProviderManifest | null>(() => {
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
      setProviderKey(initialBinding.provider_key);
      setEnabled(initialBinding.enabled);
      setAuthConfig(initialBinding.auth_config);
      setRuntimeConfig(
        Object.fromEntries(
          Object.entries(initialBinding.runtime_config).map(([key, value]) => [key, toFieldValue(value)])
        )
      );
      setTestMessage(initialBinding.last_health_message);
      return;
    }

    const firstManifest = selectableCatalog[0]?.manifest;
    setProviderKey(firstManifest?.key ?? '');
    setEnabled(true);
    setAuthConfig({});
    setRuntimeConfig({});
    setTestMessage(null);
  }, [initialBinding, open, selectableCatalog]);

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

  const handleSave = async () => {
    if (!manifest) {
      toast.error('Please select a web search provider');
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
        await updateAgentWebSearchBinding(initialBinding.id, payload);
      } else {
        await createAgentWebSearchBinding(agentId, {
          provider_key: manifest.key,
          ...payload,
        });
      }

      await onSaved();
      toast.success(initialBinding ? 'Web search provider updated' : 'Web search provider created');
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save web search provider');
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    if (!manifest) {
      toast.error('Please select a web search provider');
      return;
    }

    setIsTesting(true);
    try {
      const result = initialBinding
        ? await testAgentWebSearchBinding(initialBinding.id)
        : await testWebSearchProviderDraft(manifest.key, {
            auth_config: authConfig,
            runtime_config: runtimeConfig,
          });
      setTestMessage(result.result.message);
      toast.success(result.result.message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to test web search provider';
      setTestMessage(message);
      toast.error(message);
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title={initialBinding ? 'Edit Web Search Provider' : 'Add Web Search Provider'}
      size="default"
    >
      <div className="flex h-full flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
          {!initialBinding && (
            <div className="space-y-2">
              <Label htmlFor="web-search-provider">Provider</Label>
              <Select value={providerKey} onValueChange={setProviderKey}>
                <SelectTrigger id="web-search-provider">
                  {manifest ? (
                    <WebSearchProviderBadge
                      name={manifest.name}
                      logoUrl={manifest.logo_url ?? null}
                    />
                  ) : (
                    <SelectValue placeholder="Select a provider" />
                  )}
                </SelectTrigger>
                <SelectContent>
                  {selectableCatalog.map((item) => (
                    <SelectItem key={item.manifest.key} value={item.manifest.key}>
                      <WebSearchProviderBadge
                        name={item.manifest.name}
                        logoUrl={item.manifest.logo_url ?? null}
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

        <Separator />

        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => void handleTest()}
            disabled={isTesting || !manifest}
          >
            {isTesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
            Test Connection
          </Button>

          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleSave()} disabled={isSaving || !manifest}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Save
            </Button>
          </div>
        </div>
      </div>
    </DraggableDialog>
  );
}

export default WebSearchBindingDialog;
