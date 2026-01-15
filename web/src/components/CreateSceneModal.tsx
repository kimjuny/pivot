import React, { useState, ChangeEvent } from 'react';

interface CreateSceneModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (sceneData: {
    name: string;
    description?: string;
    agent_id: number;
  }) => Promise<void>;
}

interface SceneFormData {
  name: string;
  description: string;
  agent_id: number;
}

function CreateSceneModal({ isOpen, onClose, onCreate }: CreateSceneModalProps) {
  const [formData, setFormData] = useState<SceneFormData>({
    name: '',
    description: '',
    agent_id: 0
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const handleInputChange = (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setError('Scene name is required');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await onCreate({
        name: formData.name.trim(),
        description: formData.description.trim() || undefined,
        agent_id: formData.agent_id
      });
      setFormData({
        name: '',
        description: '',
        agent_id: 0
      });
      onClose();
    } catch (err) {
      setError((err as Error).message || 'Failed to create scene');
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
      agent_id: 0
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
            <h3 className="text-xl font-semibold text-dark-text-primary">Create New Scene</h3>
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
                Scene Name <span className="text-red-400">*</span>
              </label>
              <input
                id="name"
                name="name"
                type="text"
                value={formData.name}
                onChange={handleInputChange}
                disabled={isSubmitting}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
                placeholder="Enter scene name"
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
                placeholder="Enter scene description (optional)"
              />
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

export default CreateSceneModal;
