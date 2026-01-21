import React, { useState, useEffect, MouseEvent, useRef } from 'react';
import { Input } from '@base-ui/react/input';
import { Button } from '@base-ui/react/button';
import { Field } from '@base-ui/react/field';

export interface ConnectionFormData {
  name: string;
  condition: string;
  from_subscene: string;
  to_subscene: string;
}

interface ConnectionModalProps {
  isOpen: boolean;
  mode: 'add' | 'edit';
  sceneId: number | null;
  initialData?: Partial<ConnectionFormData>;
  existingConnection?: { from: string; to: string };
  onClose: () => void;
  onSave: (data: ConnectionFormData) => void;
}

function ConnectionModal({
  isOpen,
  mode,
  sceneId,
  initialData,
  existingConnection,
  onClose,
  onSave
}: ConnectionModalProps) {
  const [formData, setFormData] = useState<ConnectionFormData>({
    name: '',
    condition: '',
    from_subscene: '',
    to_subscene: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          condition: initialData.condition || '',
          from_subscene: initialData.from_subscene || '',
          to_subscene: initialData.to_subscene || ''
        });
      } else if (mode === 'add' && initialData) {
        setFormData({
          name: '',
          condition: '',
          from_subscene: initialData.from_subscene || '',
          to_subscene: initialData.to_subscene || ''
        });
      }
      setServerError(null);
    }
  }, [isOpen, mode, initialData]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
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
  }, [isOpen, onClose]);

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      setServerError('Please enter a connection name');
      return;
    }

    onSave({
      name: formData.name,
      condition: formData.condition,
      from_subscene: formData.from_subscene,
      to_subscene: formData.to_subscene
    });

    setFormData({
      name: '',
      condition: '',
      from_subscene: '',
      to_subscene: ''
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
            {mode === 'add' ? 'Add Connection' : 'Edit Connection'}
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
          <div className="px-6 py-3 bg-red-500/10 border-b border-red-500/20">
            <p className="text-sm text-red-400">{serverError}</p>
          </div>
        )}

        <div className="p-6 space-y-4">
          <Field.Root>
            <Field.Label
              className="block text-sm font-medium text-dark-text-secondary mb-2"
              nativeLabel={false}
              render={<div />}
            >
              Connection Name
            </Field.Label>
            <Input
              value={formData.name}
              onValueChange={(value) => setFormData({ ...formData, name: value })}
              disabled={isSubmitting}
              className="h-10 w-full px-3.5 rounded-md border border-gray-200 bg-dark-bg-lighter text-base text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary"
              placeholder="Enter connection name"
            />
          </Field.Root>

          <div>
            <label htmlFor="condition" className="block text-sm font-medium text-dark-text-secondary mb-2">Condition</label>
            <textarea
              id="condition"
              name="condition"
              value={formData.condition}
              onChange={(e) => setFormData({ ...formData, condition: e.target.value })}
              className="w-full px-3.5 py-2.5 bg-dark-bg-lighter border border-gray-200 rounded-md text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary resize-none"
              rows={3}
              placeholder="Enter condition"
              disabled={isSubmitting}
            />
          </div>

          {mode === 'add' && (
            <>
              <div className="p-3 bg-dark-bg-lighter border border-dark-border rounded-lg">
                <p className="text-sm text-dark-text-secondary mb-1">From Subscene</p>
                <p className="text-xs text-dark-text-muted">{formData.from_subscene || 'Not specified'}</p>
              </div>

              <div className="p-3 bg-dark-bg-lighter border border-dark-border rounded-lg">
                <p className="text-sm text-dark-text-secondary mb-1">To Subscene</p>
                <p className="text-xs text-dark-text-muted">{formData.to_subscene || 'Not specified'}</p>
              </div>
            </>
          )}

          {mode === 'edit' && existingConnection && (
            <>
              <div className="p-3 bg-dark-bg-lighter border border-dark-border rounded-lg">
                <p className="text-sm text-dark-text-secondary mb-1">From Subscene</p>
                <p className="text-xs text-dark-text-muted">{existingConnection.from || 'Not specified'}</p>
              </div>

              <div className="p-3 bg-dark-bg-lighter border border-dark-border rounded-lg">
                <p className="text-sm font-medium text-dark-text-secondary mb-1">To Subscene</p>
                <p className="text-xs text-dark-text-muted">{existingConnection.to || 'Not specified'}</p>
              </div>
            </>
          )}
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

export default ConnectionModal;
