import React, { useState, useEffect } from 'react';
import { Input } from '@base-ui/react/input';
import { Button } from '@base-ui/react/button';
import { Select } from '@base-ui/react/select';
import { Field } from '@base-ui/react/field';
import { ChevronUp, ChevronDown, Check } from 'lucide-react';
import { getModels } from '../utils/api';

function ChevronUpDownIcon() {
  return (
    <div className="flex flex-col items-center justify-center gap-0.5">
      <ChevronUp className="w-3 h-3" />
      <ChevronDown className="w-3 h-3" />
    </div>
  );
}

function CheckIcon() {
  return <Check className="size-3" />;
}

export interface AgentFormData {
  name: string;
  description: string | undefined;
  model_name: string | undefined;
  is_active: boolean;
}

interface AgentModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  initialData?: Partial<AgentFormData>;
  onClose: () => void;
  onSave: (data: AgentFormData) => Promise<void>;
}

function AgentModal({ isOpen, mode, initialData, onClose, onSave }: AgentModalProps) {
  const [formData, setFormData] = useState<AgentFormData>({
    name: '',
    description: '',
    model_name: '',
    is_active: true
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<{ label: string; value: string }[]>([]);
  const [loadingModels, setLoadingModels] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          description: initialData.description || '',
          model_name: initialData.model_name || '',
          is_active: initialData.is_active !== undefined ? initialData.is_active : true
        });
      } else {
        setFormData({
          name: '',
          description: '',
          model_name: '',
          is_active: true
        });
      }
      setServerError(null);

      // Load available models
      void loadModels();
    }
  }, [isOpen, mode, initialData]);

  const loadModels = async () => {
    setLoadingModels(true);
    try {
      const models = await getModels();
      setAvailableModels(models.map((model) => ({ label: model, value: model })));
    } catch (err) {
      const error = err as Error;
      console.error('Failed to load models:', error);
    } finally {
      setLoadingModels(false);
    }
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setServerError('Agent name is required');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      await onSave({
        name: formData.name.trim(),
        description: formData.description?.trim() || undefined,
        model_name: formData.model_name?.trim() || undefined,
        is_active: formData.is_active
      });
      onClose();
    } catch (err) {
      const error = err as Error;
      setServerError(error.message || 'Failed to save agent');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-dark-bg border border-dark-border rounded-xl shadow-card-lg w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-dark-border bg-dark-bg-lighter rounded-t-xl">
          <h3 className="text-lg font-semibold text-white">
            {mode === 'create' ? 'Create New Agent' : 'Edit Agent'}
          </h3>
        </div>

        {serverError && (
          <div className="px-6 py-3 bg-danger-100 border-b border-danger-200">
            <p className="text-sm text-danger">{serverError}</p>
          </div>
        )}

        <div className="p-6 space-y-4">
          <div>
            <Field.Root>
              <Field.Label
                className="block text-sm font-medium text-dark-text-secondary mb-2"
                nativeLabel={false}
                render={<div />}
              >
                Agent Name <span className="text-danger">*</span>
              </Field.Label>
              <Input
                value={formData.name}
                onValueChange={(value) => setFormData({ ...formData, name: value })}
                disabled={isSubmitting}
                className="h-10 w-full px-3.5 rounded-md border border-gray-200 bg-dark-bg-lighter text-base text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary"
                placeholder="Enter agent name"
              />
            </Field.Root>
          </div>

          <div>
            <label htmlFor="description" className="block text-sm font-medium text-dark-text-secondary mb-2">
              Description
            </label>
            <textarea
              id="description"
              name="description"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              disabled={isSubmitting}
              className="w-full px-3.5 py-2.5 bg-dark-bg-lighter border border-gray-200 rounded-md text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary resize-none"
              rows={3}
              placeholder="Enter agent description (optional)"
            />
          </div>

          <div>
            <Field.Root>
              <Field.Label
                className="block text-sm font-medium text-dark-text-secondary mb-2"
                nativeLabel={false}
                render={<div />}
              >
                Model Name
              </Field.Label>
              {loadingModels ? (
                <div className="h-10 w-full px-3.5 bg-dark-bg-lighter border border-gray-200 rounded-md text-dark-text-muted text-sm flex items-center">
                  Loading models...
                </div>
              ) : (
                <Select.Root
                  items={availableModels}
                  value={formData.model_name ?? null}
                  onValueChange={(value) => setFormData({ ...formData, model_name: value ?? undefined })}
                  disabled={isSubmitting}
                  modal={false}
                >
                  <Select.Trigger className="flex h-10 w-full items-center justify-between gap-3 rounded-md border border-gray-200 bg-dark-bg-lighter px-3.5 text-base text-dark-text-primary placeholder-dark-text-muted select-none hover:bg-dark-border-light focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-primary data-[popup-open]:bg-dark-border-light">
                    <Select.Value className="data-[placeholder]:opacity-60" placeholder="Select a model (optional)" />
                    <Select.Icon className="flex">
                      <ChevronUpDownIcon />
                    </Select.Icon>
                  </Select.Trigger>
                  <Select.Portal>
                    <Select.Positioner className="outline-none select-none z-[100]" sideOffset={8} alignItemWithTrigger={false}>
                      <Select.Popup className="group min-w-[var(--anchor-width)] origin-[var(--transform-origin)] bg-clip-padding rounded-md bg-dark-bg-lighter text-dark-text-primary shadow-lg outline outline-1 outline-dark-border transition-[transform,scale,opacity] overflow-y-auto data-[ending-style]:scale-90 data-[ending-style]:opacity-0 data-[starting-style]:scale-90 data-[starting-style]:opacity-0 data-[side=none]:min-w-[calc(var(--anchor-width)+1rem)]">
                        <Select.List className="relative py-1 scroll-py-6 max-h-[var(--available-height)]">
                          <Select.Item value="" className="grid cursor-default grid-cols-[0.75rem_1fr] items-center gap-2 py-2 pr-4 pl-2.5 text-sm leading-4 outline-none select-none data-[highlighted]:relative data-[highlighted]:z-0 data-[highlighted]:text-white data-[highlighted]:before:absolute data-[highlighted]:before:inset-x-1 data-[highlighted]:before:inset-y-0 data-[highlighted]:before:z-[-1] data-[highlighted]:before:rounded-sm data-[highlighted]:before:bg-primary pointer-coarse:py-2.5 pointer-coarse:text-[0.925rem]">
                            <Select.ItemIndicator className="col-start-1">
                              <CheckIcon />
                            </Select.ItemIndicator>
                            <Select.ItemText className="col-start-2">Select a model (optional)</Select.ItemText>
                          </Select.Item>
                          {availableModels.map((model) => (
                            <Select.Item
                              key={model.value}
                              value={model.value}
                              className="grid cursor-default grid-cols-[0.75rem_1fr] items-center gap-2 py-2 pr-4 pl-2.5 text-sm leading-4 outline-none select-none data-[highlighted]:relative data-[highlighted]:z-0 data-[highlighted]:text-white data-[highlighted]:before:absolute data-[highlighted]:before:inset-x-1 data-[highlighted]:before:inset-y-0 data-[highlighted]:before:z-[-1] data-[highlighted]:before:rounded-sm data-[highlighted]:before:bg-primary pointer-coarse:py-2.5 pointer-coarse:text-[0.925rem]"
                            >
                              <Select.ItemIndicator className="col-start-1">
                                <CheckIcon />
                              </Select.ItemIndicator>
                              <Select.ItemText className="col-start-2">{model.label}</Select.ItemText>
                            </Select.Item>
                          ))}
                        </Select.List>
                      </Select.Popup>
                    </Select.Positioner>
                  </Select.Portal>
                </Select.Root>
              )}
            </Field.Root>
          </div>

          <div className="flex items-center space-x-2">
            <input
              id="is_active"
              name="is_active"
              type="checkbox"
              checked={formData.is_active}
              onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
              disabled={isSubmitting}
              className="w-4 h-4 rounded border-dark-border bg-dark-bg-lighter"
            />
            <label htmlFor="is_active" className="text-sm text-dark-text-secondary">Activate Agent</label>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-dark-border bg-dark-bg-lighter flex space-x-3 rounded-b-xl">
          <Button
            onClick={onClose}
            disabled={isSubmitting}
            className="flex-1 h-10 px-4 bg-dark-bg border border-dark-border rounded-md text-sm font-medium hover:bg-dark-border-light data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed"
          >
            Cancel
          </Button>
          <Button
            onClick={() => void handleSubmit()}
            disabled={isSubmitting || !formData.name.trim()}
            className="flex-1 h-10 px-4 btn-accent rounded-md text-sm font-medium data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed"
          >
            {isSubmitting ? 'Saving...' : mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default AgentModal;
