import { useEffect, useMemo, useState } from 'react';

import { ArrowUp, Loader2 } from "@/lib/lucide";
import { toast } from 'sonner';

import DraggableDialog from './DraggableDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import {
  replaceAgentExtensionBindings,
  upsertAgentExtensionBinding,
  type AgentExtensionPackage,
  type ExtensionInstallation,
} from '@/utils/api';

/**
 * Return the preferred version choice for one package.
 * Why: new bindings should default to the newest active version instead of
 * making users manually undo a disabled or outdated default.
 */
function getPreferredInstallation(
  pkg: AgentExtensionPackage | null,
): ExtensionInstallation | null {
  if (!pkg) {
    return null;
  }
  return (
    pkg.versions.find((item) => item.status === 'active')
    ?? pkg.versions[0]
    ?? null
  );
}

/**
 * Convert one config payload into editable JSON text.
 */
function toConfigText(config: Record<string, unknown>): string {
  return JSON.stringify(config, null, 2);
}

/**
 * Parse editable config JSON text into a config object.
 */
function parseConfigText(configText: string): Record<string, unknown> {
  const trimmed = configText.trim();
  if (!trimmed) {
    return {};
  }

  const parsed = JSON.parse(trimmed) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error('Config must be a JSON object.');
  }
  return parsed as Record<string, unknown>;
}

interface ExtensionBindingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  packages: AgentExtensionPackage[];
  initialPackage?: AgentExtensionPackage | null;
  onSaved: () => Promise<void> | void;
}

/**
 * Extension binding editor used for both add and edit flows.
 */
function ExtensionBindingDialog({
  open,
  onOpenChange,
  agentId,
  packages,
  initialPackage = null,
  onSaved,
}: ExtensionBindingDialogProps) {
  const [packageId, setPackageId] = useState('');
  const [installationId, setInstallationId] = useState('');
  const [enabled, setEnabled] = useState(true);
  const [priority, setPriority] = useState('100');
  const [configText, setConfigText] = useState('{\n}');
  const [isSaving, setIsSaving] = useState(false);

  const selectablePackages = useMemo(() => {
    if (initialPackage) {
      return packages;
    }
    return packages.filter((pkg) => pkg.selected_binding === null);
  }, [initialPackage, packages]);

  const selectedPackage = useMemo(
    () => selectablePackages.find((pkg) => pkg.package_id === packageId) ?? null,
    [packageId, selectablePackages],
  );

  const selectedInstallation = useMemo(
    () =>
      selectedPackage?.versions.find(
        (item) => String(item.id) === installationId,
      ) ?? null,
    [installationId, selectedPackage],
  );

  useEffect(() => {
    if (!open) {
      return;
    }

    if (initialPackage?.selected_binding) {
      setPackageId(initialPackage.package_id);
      setInstallationId(
        String(initialPackage.selected_binding.extension_installation_id),
      );
      setEnabled(initialPackage.selected_binding.enabled);
      setPriority(String(initialPackage.selected_binding.priority));
      setConfigText(toConfigText(initialPackage.selected_binding.config));
      return;
    }

    const nextPackage = selectablePackages[0] ?? null;
    const nextInstallation = getPreferredInstallation(nextPackage);
    setPackageId(nextPackage?.package_id ?? '');
    setInstallationId(nextInstallation ? String(nextInstallation.id) : '');
    setEnabled(true);
    setPriority('100');
    setConfigText('{\n}');
  }, [initialPackage, open, selectablePackages]);

  useEffect(() => {
    if (!selectedPackage || initialPackage?.selected_binding) {
      return;
    }
    const preferredInstallation = getPreferredInstallation(selectedPackage);
    setInstallationId(preferredInstallation ? String(preferredInstallation.id) : '');
  }, [initialPackage, selectedPackage]);

  const handleSave = async () => {
    const parsedInstallationId = Number(installationId);
    const parsedPriority = Number(priority);

    if (!selectedPackage || !selectedInstallation || Number.isNaN(parsedInstallationId)) {
      toast.error('Please select an extension package and version.');
      return;
    }
    if (!Number.isInteger(parsedPriority)) {
      toast.error('Priority must be an integer.');
      return;
    }

    let parsedConfig: Record<string, unknown>;
    try {
      parsedConfig = parseConfigText(configText);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Invalid config JSON');
      return;
    }

    setIsSaving(true);
    try {
      const existingBinding = initialPackage?.selected_binding ?? null;
      const switchingVersion =
        existingBinding !== null
        && existingBinding.extension_installation_id !== parsedInstallationId;

      if (switchingVersion) {
        const bindings = packages
          .filter((pkg) => pkg.selected_binding !== null)
          .map((pkg) => {
            if (pkg.package_id === selectedPackage.package_id) {
              return {
                extension_installation_id: parsedInstallationId,
                enabled,
                priority: parsedPriority,
                config: parsedConfig,
              };
            }
            const binding = pkg.selected_binding;
            if (binding === null) {
              throw new Error('Unexpected missing binding while switching versions.');
            }
            return {
              extension_installation_id: binding.extension_installation_id,
              enabled: binding.enabled,
              priority: binding.priority,
              config: binding.config,
            };
          });
        await replaceAgentExtensionBindings(agentId, bindings);
      } else {
        await upsertAgentExtensionBinding(agentId, parsedInstallationId, {
          enabled,
          priority: parsedPriority,
          config: parsedConfig,
        });
      }

      await onSaved();
      toast.success(existingBinding ? 'Extension updated' : 'Extension added');
      onOpenChange(false);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to save extension',
      );
    } finally {
      setIsSaving(false);
    }
  };

  const activeVersionOptions = selectedPackage?.versions ?? [];
  const docsText = selectedPackage?.has_update_available
    ? 'A newer installed version is available for this package.'
    : 'This package is pinned at the currently selected installed version.';

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title={initialPackage ? 'Edit Extension Binding' : 'Add Extension Binding'}
      size="default"
    >
      <div className="flex h-full flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto px-4 py-4">
          {!initialPackage && (
            <div className="space-y-2">
              <Label htmlFor="extension-package">Package</Label>
              <Select value={packageId} onValueChange={setPackageId}>
                <SelectTrigger id="extension-package">
                  <SelectValue placeholder="Select an extension package" />
                </SelectTrigger>
                <SelectContent>
                  {selectablePackages.map((pkg) => (
                    <SelectItem key={pkg.package_id} value={pkg.package_id}>
                      {pkg.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {selectedPackage && (
            <>
              <div className="rounded-lg border border-border px-3 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-foreground">
                      {selectedPackage.display_name}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {selectedPackage.description || 'No description provided.'}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">Latest {selectedPackage.latest_version}</Badge>
                    {selectedPackage.has_update_available && (
                      <Badge className="gap-1">
                        <ArrowUp className="h-3 w-3" />
                        Update available
                      </Badge>
                    )}
                  </div>
                </div>
                <div className="mt-3 text-xs text-muted-foreground">
                  {docsText}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="extension-version">Version</Label>
                <Select value={installationId} onValueChange={setInstallationId}>
                  <SelectTrigger id="extension-version">
                    <SelectValue placeholder="Select a version" />
                  </SelectTrigger>
                  <SelectContent>
                    {activeVersionOptions.map((version) => (
                      <SelectItem key={version.id} value={String(version.id)}>
                        {version.version}
                        {version.status === 'disabled' ? ' · disabled' : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-4 md:grid-cols-[1fr_auto]">
                <div className="space-y-2">
                  <Label htmlFor="extension-priority">Priority</Label>
                  <Input
                    id="extension-priority"
                    type="number"
                    value={priority}
                    onChange={(event) => setPriority(event.target.value)}
                    placeholder="100"
                  />
                  <div className="text-xs text-muted-foreground">
                    Lower numbers resolve earlier in the extension bundle.
                  </div>
                </div>
                <div className="flex items-center justify-between rounded-lg border border-border px-3 py-2 md:min-w-[180px]">
                  <div>
                    <div className="text-sm font-medium text-foreground">Enabled</div>
                    <div className="text-xs text-muted-foreground">
                      Disable this binding without removing it.
                    </div>
                  </div>
                  <Switch checked={enabled} onCheckedChange={setEnabled} />
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="extension-config">Config (JSON)</Label>
                <Textarea
                  id="extension-config"
                  value={configText}
                  onChange={(event) => setConfigText(event.target.value)}
                  className="min-h-[180px] font-mono text-xs"
                  placeholder='{"region":"us"}'
                />
                <div className="text-xs text-muted-foreground">
                  Agent-local configuration stored on the binding for this package.
                </div>
              </div>
            </>
          )}

          {!selectedPackage && (
            <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
              {initialPackage
                ? 'This extension package is no longer available.'
                : 'Install an extension package first, then add it to this agent.'}
            </div>
          )}
        </div>

        <div className="border-t border-border px-4 py-3">
          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleSave()}
              disabled={isSaving || !selectedPackage || !selectedInstallation}
            >
              {isSaving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Save
            </Button>
          </div>
        </div>
      </div>
    </DraggableDialog>
  );
}

export default ExtensionBindingDialog;
