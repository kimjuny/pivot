import React, { useState } from 'react';
import { Input } from '@base-ui/react/input';
import { Button } from '@base-ui/react/button';
import { Field } from '@base-ui/react/field';

interface SceneModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  initialData?: {
    name: string;
    description?: string;
  };
  onClose: () => void;
  onSave: (sceneData: {
    name: string;
    description?: string;
  }) => Promise<void>;
}

interface SceneFormData {
  name: string;
  description: string;
}

function SceneModal({ isOpen, mode, initialData, onClose, onSave }: SceneModalProps) {
  const [formData, setFormData] = useState<SceneFormData>({
    name: '',
    description: ''
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          description: initialData.description || ''
        });
      } else {
        setFormData({
          name: '',
          description: ''
        });
      }
      setError(null);
    }
  }, [isOpen, mode, initialData]);

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setError('Scene name is required');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await onSave({
        name: formData.name.trim(),
        description: formData.description.trim() || undefined
      });
      setFormData({
        name: '',
        description: ''
      });
      onClose();
    } catch (err) {
      setError((err as Error).message || 'Failed to save scene');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancel = () => {
    setFormData({
      name: '',
      description: ''
    });
    setError(null);
    onClose();
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-dark-bg border border-dark-border rounded-xl shadow-card-lg w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-dark-border flex items-center justify-between rounded-t-xl">
          <h3 className="text-lg font-semibold text-white">
            {mode === 'create' ? 'Create New Scene' : 'Edit Scene'}
          </h3>
          <Button
            onClick={handleCancel}
            disabled={isSubmitting}
            className="nav-hover-effect p-2 h-auto bg-transparent border-0 text-dark-text-secondary hover:text-dark-text-primary data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </Button>
        </div>

        <div className="p-6">
          <div className="space-y-4">
            <Field.Root>
              <Field.Label
                className="block text-sm font-medium text-dark-text-secondary mb-2"
                nativeLabel={false}
                render={<div />}
              >
                Scene Name <span className="text-danger">*</span>
              </Field.Label>
              <Input
                value={formData.name}
                onValueChange={(value) => setFormData({ ...formData, name: value })}
                disabled={isSubmitting}
                className="h-10 w-full px-3.5 rounded-md border border-gray-200 bg-dark-bg-lighter text-base text-dark-text-primary placeholder-dark-text-muted focus:outline focus:outline-2 focus:-outline-offset-1 focus:outline-primary"
                placeholder="Enter scene name"
              />
            </Field.Root>

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
                placeholder="Enter scene description (optional)"
              />
            </div>
          </div>

          {error && (
            <div className="mt-4 p-3 bg-danger-100 border border-danger-300 rounded-lg">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-dark-border flex space-x-3 rounded-b-xl">
          <Button
            onClick={handleCancel}
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

export default SceneModal;
