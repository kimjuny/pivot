import React, { useState, useEffect, ChangeEvent, MouseEvent, useRef } from 'react';

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
        <div className="px-6 py-4 border-b border-dark-border bg-dark-bg-lighter">
          <h3 className="text-lg font-semibold text-white">
            {mode === 'add' ? 'Add Connection' : 'Edit Connection'}
          </h3>
        </div>

        {serverError && (
          <div className="px-6 py-3 bg-red-500/10 border-b border-red-500/20">
            <p className="text-sm text-red-400">{serverError}</p>
          </div>
        )}

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-dark-text-secondary mb-2">Connection Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
              placeholder="Enter connection name"
              disabled={isSubmitting}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-dark-text-secondary mb-2">Condition</label>
            <textarea
              value={formData.condition}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setFormData({ ...formData, condition: e.target.value })}
              className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark resize-none"
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

        <div className="px-6 py-4 border-t border-dark-border bg-dark-bg-lighter flex space-x-3">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 bg-dark-bg border border-dark-border rounded-lg text-sm font-medium hover:bg-dark-border-light transition-colors"
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            onClick={() => void handleSubmit()}
            className="flex-1 px-4 py-2 btn-accent rounded-lg text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isSubmitting || !formData.name.trim()}
          >
            {mode === 'add' ? 'Add' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConnectionModal;
