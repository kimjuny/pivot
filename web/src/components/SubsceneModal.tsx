import React, { useState, useEffect, MouseEvent, useRef } from 'react';
import { Input } from '@base-ui/react/input';
import { Button } from '@base-ui/react/button';
import { Select } from '@base-ui/react/select';
import { Field } from '@base-ui/react/field';
import { ChevronUp, ChevronDown, Check } from 'lucide-react';

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

export interface SubsceneFormData {
  name: string;
  type: 'start' | 'normal' | 'end';
  mandatory: boolean;
  objective: string;
}

interface SubsceneModalProps {
  isOpen: boolean;
  mode: 'add' | 'edit';
  sceneId: number | null;
  initialData?: Partial<SubsceneFormData>;
  existingSubsceneName?: string;
  onClose: () => void;
  onSave: (data: SubsceneFormData) => void;
}

function SubsceneModal({
  isOpen,
  mode,
  sceneId,
  initialData,
  existingSubsceneName,
  onClose,
  onSave
}: SubsceneModalProps) {
  const [formData, setFormData] = useState<SubsceneFormData>({
    name: '',
    type: 'normal',
    mandatory: false,
    objective: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSelectOpen, setIsSelectOpen] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          type: initialData.type || 'normal',
          mandatory: initialData.mandatory || false,
          objective: initialData.objective || ''
        });
      } else {
        setFormData({
          name: '',
          type: 'normal',
          mandatory: false,
          objective: ''
        });
      }
      setServerError(null);
    }
  }, [isOpen, mode, initialData]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (isSelectOpen) {
        return;
      }

      if (modalRef.current && !modalRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside as unknown as EventListener);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside as unknown as EventListener);
      };
    }
  }, [isOpen, onClose, isSelectOpen]);

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      setServerError('Please enter a subscene name');
      return;
    }

    onSave({
      name: formData.name,
      type: formData.type,
      mandatory: formData.mandatory,
      objective: formData.objective
    });

    setFormData({
      name: '',
      type: 'normal',
      mandatory: false,
      objective: ''
    });
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center">
      <div ref={modalRef} className="bg-dark-bg border border-dark-border rounded-xl shadow-card-lg w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 py-4 border-b border-dark-border flex items-center justify-between">
          <h3 className="text-lg font-semibold text-white">
            {mode === 'add' ? 'Add Subscene' : 'Edit Subscene'}
          </h3>
          <Button
            onClick={onClose}
            disabled={isSubmitting}
            className="nav-hover-effect p-2 h-auto bg-transparent border-0 text-dark-text-secondary hover:text-dark-text-primary data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </Button>
        </div>

        {serverError && (
          <div className="px-6 py-3 bg-danger-100 border-b border-danger-200">
            <p className="text-sm text-danger">{serverError}</p>
          </div>
        )}

        <div className="p-6 space-y-4">
          <Field.Root>
            <Field.Label
              className="block text-sm font-medium text-dark-text-secondary mb-2"
              nativeLabel={false}
              render={<div />}
            >
              Name
            </Field.Label>
            <Input
              value={formData.name}
              onValueChange={(value) => setFormData({ ...formData, name: value })}
              disabled={isSubmitting}
              className="h-10 w-full px-3.5 rounded-md border border-gray-200 bg-dark-bg-lighter text-base text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary"
              placeholder="Enter subscene name"
            />
          </Field.Root>

          <Field.Root>
            <Field.Label
              className="block text-sm font-medium text-dark-text-secondary mb-2"
              nativeLabel={false}
              render={<div />}
            >
              Type
            </Field.Label>
            <Select.Root
              items={[
                { value: 'start', label: 'Start' },
                { value: 'normal', label: 'Normal' },
                { value: 'end', label: 'End' }
              ]}
              value={formData.type}
              onValueChange={(value) => setFormData({ ...formData, type: value as 'start' | 'normal' | 'end' })}
              onOpenChange={setIsSelectOpen}
              disabled={isSubmitting}
              modal={false}
            >
              <Select.Trigger className="flex h-10 w-full items-center justify-between gap-3 rounded-md border border-gray-200 bg-dark-bg-lighter px-3.5 text-base text-dark-text-primary placeholder-dark-text-muted select-none hover:bg-dark-border-light focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-primary data-[popup-open]:bg-dark-border-light">
                <Select.Value className="data-[placeholder]:opacity-60" placeholder="Select type" />
                <Select.Icon className="flex">
                  <ChevronUpDownIcon />
                </Select.Icon>
              </Select.Trigger>
              <Select.Portal>
                <Select.Positioner className="outline-none select-none z-[100]" sideOffset={8} alignItemWithTrigger={false}>
                  <Select.Popup className="group min-w-[var(--anchor-width)] origin-[var(--transform-origin)] bg-clip-padding rounded-md bg-dark-bg-lighter text-dark-text-primary shadow-lg outline outline-1 outline-dark-border transition-[transform,scale,opacity] overflow-y-auto data-[ending-style]:scale-90 data-[ending-style]:opacity-0 data-[starting-style]:scale-90 data-[starting-style]:opacity-0 data-[side=none]:min-w-[calc(var(--anchor-width)+1rem)]">
                    <Select.List className="relative py-1 scroll-py-6 max-h-[var(--available-height)]">
                      {['start', 'normal', 'end'].map((type) => (
                        <Select.Item
                          key={type}
                          value={type}
                          className="grid cursor-default grid-cols-[0.75rem_1fr] items-center gap-2 py-2 pr-4 pl-2.5 text-sm leading-4 outline-none select-none data-[highlighted]:relative data-[highlighted]:z-0 data-[highlighted]:text-white data-[highlighted]:before:absolute data-[highlighted]:before:inset-x-1 data-[highlighted]:before:inset-y-0 data-[highlighted]:before:z-[-1] data-[highlighted]:before:rounded-sm data-[highlighted]:before:bg-primary pointer-coarse:py-2.5 pointer-coarse:text-[0.925rem]"
                        >
                          <Select.ItemIndicator className="col-start-1">
                            <CheckIcon />
                          </Select.ItemIndicator>
                          <Select.ItemText className="col-start-2">{type.charAt(0).toUpperCase() + type.slice(1)}</Select.ItemText>
                        </Select.Item>
                      ))}
                    </Select.List>
                  </Select.Popup>
                </Select.Positioner>
              </Select.Portal>
            </Select.Root>
          </Field.Root>

          <div className="flex items-center space-x-2">
            <input
              type="checkbox"
              id="mandatory"
              checked={formData.mandatory}
              onChange={(e) => setFormData({ ...formData, mandatory: e.target.checked })}
              className="w-4 h-4 rounded border-dark-border bg-dark-bg-lighter"
              disabled={isSubmitting}
            />
            <label htmlFor="mandatory" className="text-sm text-dark-text-secondary">Mandatory</label>
          </div>

          <div>
            <label htmlFor="objective" className="block text-sm font-medium text-dark-text-secondary mb-2">Objective</label>
            <textarea
              id="objective"
              name="objective"
              value={formData.objective}
              onChange={(e) => setFormData({ ...formData, objective: e.target.value })}
              className="w-full px-3.5 py-2.5 bg-dark-bg-lighter border border-gray-200 rounded-md text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary resize-none"
              rows={3}
              placeholder="Enter objective"
              disabled={isSubmitting}
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-dark-border flex space-x-3">
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
            {mode === 'add' ? 'Add' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  );
}

export default SubsceneModal;
