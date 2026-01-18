import React, { useState, useEffect, ChangeEvent, MouseEvent, useRef } from 'react';
import { createSubscene, updateSubscene } from '../utils/api';

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
  existingSubsceneName?: string; // For edit mode
  onClose: () => void;
  onSave: (subsceneName?: string) => void;
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
        // Reset form for add mode
        setFormData({
          name: '',
          type: 'normal',
          mandatory: false,
          objective: ''
        });
      }
      // Reset error when opening modal
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

  const handleSubmit = async () => {
    if (!sceneId) return;
    if (!formData.name.trim()) {
      setServerError('Please enter a subscene name');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);
    try {
      if (mode === 'add') {
        await createSubscene(sceneId, {
          name: formData.name,
          type: formData.type,
          mandatory: formData.mandatory,
          objective: formData.objective || ''
        });
      } else if (mode === 'edit' && existingSubsceneName) {
        await updateSubscene(sceneId, existingSubsceneName, {
          name: formData.name,
          type: formData.type,
          mandatory: formData.mandatory,
          objective: formData.objective
        });
      }
      // Only close and call onSave after successful submission
      // Pass the subscene name in add mode for precise positioning
      onSave(mode === 'add' ? formData.name : undefined);
    } catch (error) {
      console.error('Failed to save subscene:', error);
      // Extract error message from response if available
      const errorMessage = error instanceof Error && 'message' in error
        ? (error as { message: string }).message
        : 'Failed to save subscene. Please try again.';
      setServerError(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isOpen) {
    return null;
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center">
      <div ref={modalRef} className="bg-dark-bg border border-dark-border rounded-xl shadow-card-lg w-full max-w-md mx-4 overflow-hidden">
        <div className="px-6 py-4 border-b border-dark-border bg-dark-bg-lighter">
          <h3 className="text-lg font-semibold text-white">
            {mode === 'add' ? 'Add Subscene' : 'Edit Subscene'}
          </h3>
        </div>

        {/* Server Error Display */}
        {serverError && (
          <div className="px-6 py-3 bg-red-500/10 border-b border-red-500/20">
            <p className="text-sm text-red-400">{serverError}</p>
          </div>
        )}

        <div className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-dark-text-secondary mb-2">Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
              placeholder="Enter subscene name"
              disabled={isSubmitting}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-dark-text-secondary mb-2">Type</label>
            <select
              value={formData.type}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => setFormData({ ...formData, type: e.target.value as 'start' | 'normal' | 'end' })}
              className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
              disabled={isSubmitting}
            >
              <option value="start">Start</option>
              <option value="normal">Normal</option>
              <option value="end">End</option>
            </select>
          </div>

          <div className="flex items-center space-x-2">
            <input
              type="checkbox"
              id="mandatory"
              checked={formData.mandatory}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, mandatory: e.target.checked })}
              className="w-4 h-4 rounded border-dark-border bg-dark-bg-lighter"
              disabled={isSubmitting}
            />
            <label htmlFor="mandatory" className="text-sm text-dark-text-secondary">Mandatory</label>
          </div>

          <div>
            <label className="block text-sm font-medium text-dark-text-secondary mb-2">Objective</label>
            <textarea
              value={formData.objective}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setFormData({ ...formData, objective: e.target.value })}
              className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark resize-none"
              rows={3}
              placeholder="Enter objective"
              disabled={isSubmitting}
            />
          </div>
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
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Saving...' : mode === 'add' ? 'Add' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default SubsceneModal;
