import React, { useState, ChangeEvent } from 'react';

interface CreateAgentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (agentData: {
    name: string;
    description?: string;
    model_name?: string;
    is_active?: boolean;
  }) => Promise<void>;
}

interface AgentFormData {
  name: string;
  description: string;
  model_name: string;
  is_active: boolean;
}

function CreateAgentModal({ isOpen, onClose, onCreate }: CreateAgentModalProps) {
  const [formData, setFormData] = useState<AgentFormData>({
    name: '',
    description: '',
    model_name: '',
    is_active: true
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleInputChange = (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleCheckboxChange = (e: ChangeEvent<HTMLInputElement>) => {
    const { name, checked } = e.target;
    setFormData((prev) => ({ ...prev, [name]: checked }));
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setError('Agent name is required');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await onCreate({
        name: formData.name.trim(),
        description: formData.description.trim() || undefined,
        model_name: formData.model_name.trim() || undefined,
        is_active: formData.is_active
      });
      setFormData({
        name: '',
        description: '',
        model_name: '',
        is_active: true
      });
    } catch (err) {
      setError((err as Error).message || 'Failed to create agent');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCreateClick = () => {
    void handleSubmit();
  };

  const handleCancel = () => {
    setFormData({
      name: '',
      description: '',
      model_name: '',
      is_active: true
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
        <div className="p-6">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-xl font-semibold text-dark-text-primary">Create New Agent</h3>
            <button
              onClick={handleCancel}
              className="p-2 rounded-lg hover:bg-dark-border-light transition-colors"
              disabled={isSubmitting}
            >
              <svg className="w-5 h-5 text-dark-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <label htmlFor="name" className="block text-sm font-medium text-dark-text-secondary mb-2">
                Agent Name <span className="text-red-400">*</span>
              </label>
              <input
                id="name"
                name="name"
                type="text"
                value={formData.name}
                onChange={handleInputChange}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
                placeholder="Enter agent name"
              />
            </div>

            <div>
              <label htmlFor="description" className="block text-sm font-medium text-dark-text-secondary mb-2">
                Description
              </label>
              <textarea
                id="description"
                name="description"
                value={formData.description}
                onChange={handleInputChange}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark resize-none"
                rows={3}
                placeholder="Enter agent description (optional)"
              />
            </div>

            <div>
              <label htmlFor="model_name" className="block text-sm font-medium text-dark-text-secondary mb-2">
                Model Name
              </label>
              <input
                id="model_name"
                name="model_name"
                type="text"
                value={formData.model_name}
                onChange={handleInputChange}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
                placeholder="e.g., gpt-4, claude-3 (optional)"
              />
            </div>

            <div className="flex items-center space-x-2">
              <input
                id="is_active"
                name="is_active"
                type="checkbox"
                checked={formData.is_active}
                onChange={handleCheckboxChange}
                disabled={isSubmitting}
                className="w-4 h-4 rounded border-dark-border bg-dark-bg-lighter"
              />
              <label htmlFor="is_active" className="text-sm text-dark-text-secondary">Activate Agent</label>
            </div>
          </div>

          {error && (
            <div className="mt-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <div className="flex space-x-3 mt-6">
            <button
              onClick={handleCancel}
              disabled={isSubmitting}
              className="flex-1 px-4 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-sm font-medium hover:bg-dark-border-light transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleCreateClick}
              disabled={isSubmitting || !formData.name.trim()}
              className="flex-1 px-4 py-2 btn-accent rounded-lg text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSubmitting ? 'Creating...' : 'Create'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CreateAgentModal;
