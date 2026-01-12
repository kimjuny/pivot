import React, { useState, useEffect, ChangeEvent } from 'react';

interface EditPanelProps {
  element: {
    type: 'node' | 'edge';
    id: string;
    data: any;
    label?: string;
  } | null;
  onClose: () => void;
  onSave: () => void;
  onNodeChange: (nodeId: string, data: any) => void;
  onEdgeChange: (edgeId: string, data: any) => void;
}

interface NodeFormData {
  name: string;
  type: 'start' | 'normal' | 'end';
  mandatory: boolean;
  objective: string;
}

interface EdgeFormData {
  name: string;
  condition: string;
}

function EditPanel({ element, onClose, onSave, onNodeChange, onEdgeChange }: EditPanelProps) {
  const [formData, setFormData] = useState<NodeFormData | EdgeFormData>({
    name: '',
    type: 'normal',
    mandatory: false,
    objective: '',
    condition: ''
  });

  useEffect(() => {
    if (element) {
      console.log('EditPanel element:', element);
      if (element.type === 'node') {
        setFormData({
          name: element.data.label || '',
          type: element.data.type || 'normal',
          mandatory: element.data.mandatory || false,
          objective: element.data.objective || ''
        });
      } else if (element.type === 'edge') {
        setFormData({
          name: element.data.label || '',
          condition: element.data.condition || ''
        });
      }
    }
  }, [element]);

  const handleSave = () => {
    if (element?.type === 'node') {
      onNodeChange(element.id, formData as NodeFormData);
    } else if (element?.type === 'edge') {
      onEdgeChange(element.id, formData as EdgeFormData);
    }
    onSave();
  };

  if (!element) {
    return null;
  }

  return (
    <div className="absolute top-0 right-0 h-full w-80 bg-dark-bg border-l border-dark-border shadow-card-lg overflow-y-auto">
      <div className="p-4">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold text-white">
            {element.type === 'node' ? 'Edit Node' : 'Edit Connection'}
          </h3>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-dark-border-light transition-colors"
          >
            <svg className="w-5 h-5 text-dark-text-secondary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {element.type === 'node' && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-dark-text-secondary mb-2">Name</label>
              <input
                type="text"
                value={(formData as NodeFormData).name}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
                placeholder="Enter node name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-dark-text-secondary mb-2">Type</label>
              <select
                value={(formData as NodeFormData).type}
                onChange={(e: ChangeEvent<HTMLSelectElement>) => setFormData({ ...formData, type: e.target.value as 'start' | 'normal' | 'end' })}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
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
                checked={(formData as NodeFormData).mandatory}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, mandatory: e.target.checked })}
                className="w-4 h-4 rounded border-dark-border bg-dark-bg-lighter"
              />
              <label htmlFor="mandatory" className="text-sm text-dark-text-secondary">Mandatory</label>
            </div>

            <div>
              <label className="block text-sm font-medium text-dark-text-secondary mb-2">Objective</label>
              <textarea
                value={(formData as NodeFormData).objective}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setFormData({ ...formData, objective: e.target.value })}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark resize-none"
                rows={3}
                placeholder="Enter objective"
              />
            </div>
          </div>
        )}

        {element.type === 'edge' && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-dark-text-secondary mb-2">Connection Name</label>
              <input
                type="text"
                value={(formData as EdgeFormData).name}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark"
                placeholder="Enter connection name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-dark-text-secondary mb-2">Condition</label>
              <textarea
                value={(formData as EdgeFormData).condition}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setFormData({ ...formData, condition: e.target.value })}
                className="w-full px-3 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-dark-text-primary input-dark resize-none"
                rows={3}
                placeholder="Enter condition"
              />
            </div>

            <div className="p-3 bg-dark-bg-lighter border border-dark-border rounded-lg">
              <p className="text-sm text-dark-text-secondary mb-2">From Subscene</p>
              <p className="text-xs text-dark-text-muted">{element.data.from_subscene || 'Not specified'}</p>
            </div>

            <div className="p-3 bg-dark-bg-lighter border border-dark-border rounded-lg">
              <p className="text-sm text-dark-text-secondary mb-2">To Subscene</p>
              <p className="text-xs text-dark-text-muted">{element.data.to_subscene || 'Not specified'}</p>
            </div>
          </div>
        )}

        <div className="flex space-x-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 bg-dark-bg-lighter border border-dark-border rounded-lg text-sm font-medium hover:bg-dark-border-light transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="flex-1 px-4 py-2 btn-accent rounded-lg text-sm font-medium"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

export default EditPanel;
