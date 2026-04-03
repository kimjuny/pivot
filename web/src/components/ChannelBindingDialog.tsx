import { useEffect, useMemo, useState } from 'react';
import { Copy, Loader2, RefreshCcw } from "@/lib/lucide";
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Switch } from '@/components/ui/switch';
import DraggableDialog from './DraggableDialog';
import { ChannelProviderBadge } from './ChannelProviderBadge';
import ConfigFieldGroup from './ConfigFieldGroup';
import { ProviderMetadataBadges } from './ProviderMetadataBadges';
import { formatProviderExtensionLabel } from '@/utils/providerMetadata';
import {
  createAgentChannel,
  pollAgentChannel,
  testChannelDraft,
  testAgentChannel,
  updateAgentChannel,
  type ChannelBinding,
  type ChannelCatalogItem,
  type ChannelManifest,
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

interface ChannelBindingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  catalog: ChannelCatalogItem[];
  initialBinding?: ChannelBinding | null;
  onSaved: () => Promise<void> | void;
}

/**
 * Channel binding editor used for both create and edit flows.
 */
function ChannelBindingDialog({
  open,
  onOpenChange,
  agentId,
  catalog,
  initialBinding,
  onSaved,
}: ChannelBindingDialogProps) {
  const [channelKey, setChannelKey] = useState('');
  const [name, setName] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [authConfig, setAuthConfig] = useState<Record<string, string>>({});
  const [runtimeConfig, setRuntimeConfig] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);

  const manifest = useMemo<ChannelManifest | null>(() => {
    if (!channelKey) {
      return null;
    }
    return catalog.find((item) => item.manifest.key === channelKey)?.manifest ?? null;
  }, [catalog, channelKey]);
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

  useEffect(() => {
    if (!open) {
      return;
    }

    if (initialBinding) {
      setChannelKey(initialBinding.channel_key);
      setName(initialBinding.name);
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

    const firstManifest = catalog[0]?.manifest;
    setChannelKey(firstManifest?.key ?? '');
    setName(firstManifest ? `${firstManifest.name} Binding` : '');
    setEnabled(true);
    setAuthConfig({});
    setRuntimeConfig({});
    setTestMessage(null);
  }, [catalog, initialBinding, open]);

  useEffect(() => {
    if (!manifest || initialBinding) {
      return;
    }
    setName((currentName) => currentName || `${manifest.name} Binding`);
  }, [manifest, initialBinding]);

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
      toast.error('Please select a channel provider');
      return;
    }

    setIsSaving(true);
    try {
      const payload = {
        name,
        enabled,
        auth_config: authConfig,
        runtime_config: runtimeConfig,
      };

      if (initialBinding) {
        await updateAgentChannel(initialBinding.id, payload);
      } else {
        await createAgentChannel(agentId, {
          channel_key: manifest.key,
          ...payload,
        });
      }

      await onSaved();
      toast.success(initialBinding ? 'Channel updated' : 'Channel created');
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to save channel');
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    if (!manifest) {
      toast.error('Please select a channel provider');
      return;
    }

    setIsTesting(true);
    try {
      const result = initialBinding
        ? await testAgentChannel(initialBinding.id)
        : await testChannelDraft(manifest.key, {
            auth_config: authConfig,
            runtime_config: runtimeConfig,
          });
      setTestMessage(result.result.message);
      toast.success(result.result.message);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to test channel';
      setTestMessage(message);
      toast.error(message);
    } finally {
      setIsTesting(false);
    }
  };

  const handlePoll = async () => {
    if (!initialBinding) {
      return;
    }

    setIsPolling(true);
    try {
      const result = await pollAgentChannel(initialBinding.id);
      setTestMessage(`Fetched ${result.fetched} updates from Telegram.`);
      toast.success(`Fetched ${result.fetched} updates`);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to poll channel';
      setTestMessage(message);
      toast.error(message);
    } finally {
      setIsPolling(false);
    }
  };

  /**
   * Copy one generated endpoint to the clipboard.
   * Why: webhook setup often happens in a separate provider console, so reducing manual copy mistakes matters.
   */
  const handleCopy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success('Copied to clipboard');
    } catch {
      toast.error('Failed to copy to clipboard');
    }
  };

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title={initialBinding ? 'Edit Channel Binding' : 'Add Channel Binding'}
      size="default"
    >
      <div className="flex h-full flex-col">
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
          {!initialBinding && (
            <div className="space-y-2">
              <Label htmlFor="channel-provider">Provider</Label>
              <Select value={channelKey} onValueChange={setChannelKey}>
                <SelectTrigger id="channel-provider">
                  {manifest ? (
                    <ChannelProviderBadge
                      channelKey={manifest.key}
                      name={manifest.name}
                    />
                  ) : (
                    <SelectValue placeholder="Select a provider" />
                  )}
                </SelectTrigger>
                <SelectContent>
                  {catalog.map((item) => (
                    <SelectItem key={item.manifest.key} value={item.manifest.key}>
                      <ChannelProviderBadge
                        channelKey={item.manifest.key}
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
              <div className="rounded-lg border border-border px-3 py-2">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-foreground">Per-Agent Binding</div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      These credentials belong only to this agent binding. The channel catalog page never stores shared
                      secrets or global bot config.
                    </div>
                  </div>
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

              <div className="space-y-2">
                <Label htmlFor="channel-name">Binding Name</Label>
                <Input
                  id="channel-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={`${manifest.name} Binding`}
                />
              </div>

              <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
                <div>
                  <div className="text-sm font-medium text-foreground">Enabled</div>
                  <div className="text-xs text-muted-foreground">
                    Disable the binding without deleting its credentials.
                  </div>
                </div>
                <Switch checked={enabled} onCheckedChange={setEnabled} />
              </div>

              <ConfigFieldGroup
                title="Credentials"
                description="These fields are defined by the provider manifest and stored on the binding."
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
                <ul className="space-y-1 list-disc pl-4 text-xs text-muted-foreground">
                  {manifest.setup_steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              </div>

              {initialBinding && initialBinding.endpoint_infos.length > 0 && (
                <div className="space-y-2">
                  <div className="text-sm font-medium text-foreground">Generated Endpoints</div>
                  <div className="space-y-2">
                    {initialBinding.endpoint_infos.map((endpoint) => (
                      <div key={`${endpoint.label}-${endpoint.url}`} className="rounded-lg border border-border px-3 py-2">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span className="rounded bg-muted px-1.5 py-0.5 font-medium text-foreground">{endpoint.method}</span>
                            <span>{endpoint.label}</span>
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 px-2"
                            onClick={() => void handleCopy(endpoint.url)}
                          >
                            <Copy className="h-3.5 w-3.5" />
                            Copy
                          </Button>
                        </div>
                        <div className="mt-2 break-all text-sm text-foreground">{endpoint.url}</div>
                        <div className="mt-1 text-xs text-muted-foreground">{endpoint.description}</div>
                      </div>
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
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => void handleTest()}
              disabled={isTesting}
            >
              {isTesting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
              Test Connection
            </Button>
            {initialBinding?.manifest.transport_mode === 'polling' && (
              <Button
                type="button"
                variant="outline"
                onClick={() => void handlePoll()}
                disabled={isPolling}
              >
                {isPolling ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Poll Once
              </Button>
            )}
          </div>

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

export default ChannelBindingDialog;
