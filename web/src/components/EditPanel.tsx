import React, { useState, useEffect, ChangeEvent, useRef, MouseEvent } from 'react';
import { updateSubscene, updateConnection } from '../utils/api';

interface EditPanelProps {
  element: {
    type: 'node' | 'edge';
    id: string;
    data: Record<string, unknown>;
    label?: string;
    clickPosition?: { x: number; y: number };
  } | null;
  sceneId: number | null;
  onClose: () => void;
  onSave: () => void;
  onNodeChange: (nodeId: string, data: Record<string, unknown>) => void;
  onEdgeChange: (edgeId: string, data: Record<string, unknown>) => void;
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

function EditPanel({ element, sceneId, onClose, onSave, onNodeChange, onEdgeChange }: EditPanelProps) {
  const [formData, setFormData] = useState<NodeFormData | EdgeFormData>({
    name: '',
    type: 'normal',
    mandatory: false,
    objective: '',
    condition: ''
  });

  const [position, setPosition] = useState(() => element?.clickPosition || { x: 20, y: 20 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (element) {
      if (element.type === 'node') {
        setFormData({
          name: (element.data.label as string) || '',
          type: (element.data.type as 'start' | 'normal' | 'end') || 'normal',
          mandatory: (element.data.mandatory as boolean) || false,
          objective: (element.data.objective as string) || ''
        });
      } else if (element.type === 'edge') {
        setFormData({
          name: (element.data.label as string) || '',
          condition: (element.data.condition as string) || ''
        });
      }
      setPosition(element.clickPosition || { x: 20, y: 20 });
    }
  }, [element]);

  const handleMouseDown = (e: MouseEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    setIsDragging(true);
    setDragOffset({
      x: e.clientX - position.x,
      y: e.clientY - position.y
    });
  };

  const handleMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    if (!isDragging) return;
    const newX = e.clientX - dragOffset.x;
    const newY = e.clientY - dragOffset.y;
    setPosition({ x: newX, y: newY });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
  };

  useEffect(() => {
    if (isDragging) {
      const handleGlobalMouseMove = (e: globalThis.MouseEvent) => {
        const newX = e.clientX - dragOffset.x;
        const newY = e.clientY - dragOffset.y;
        setPosition({ x: newX, y: newY });
      };

      const handleGlobalMouseUp = () => {
        setIsDragging(false);
      };

      document.addEventListener('mousemove', handleGlobalMouseMove);
      document.addEventListener('mouseup', handleGlobalMouseUp);

      return () => {
        document.removeEventListener('mousemove', handleGlobalMouseMove);
        document.removeEventListener('mouseup', handleGlobalMouseUp);
      };
    }
  }, [isDragging, dragOffset]);

  const handleSave = async () => {
    if (!sceneId || !element) return;

    try {
      if (element.type === 'node') {
        const subsceneName = element.id.replace('subscene-', '');
        const nodeData = formData as NodeFormData;
        
        await updateSubscene(sceneId, subsceneName, {
          name: nodeData.name,
          type: nodeData.type,
          mandatory: nodeData.mandatory,
          objective: nodeData.objective
        });
        
        onNodeChange(element.id, formData as unknown as Record<string, unknown>);
      } else if (element.type === 'edge') {
        const edgeData = formData as EdgeFormData;
        const fromSubscene = element.data.from_subscene as string;
        const toSubscene = element.data.to_subscene as string;
        
        if (fromSubscene && toSubscene) {
          await updateConnection(sceneId, fromSubscene, toSubscene, {
            name: edgeData.name,
            condition: edgeData.condition
          });
        }
        
        onEdgeChange(element.id, formData as unknown as Record<string, unknown>);
      }
      onSave();
    } catch (error) {
      console.error('Failed to save:', error);
      alert('Failed to save changes. Please try again.');
    }
  };

  if (!element) {
    return null;
  }

  return (
    <div
      ref={panelRef}
      className="fixed w-80 bg-dark-bg border border-dark-border shadow-card-lg rounded-xl overflow-hidden"
      style={{
        left: position.x,
        top: position.y,
        zIndex: 40,
        cursor: isDragging ? 'grabbing' : 'default'
      }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      <div
        className="bg-dark-bg-lighter px-4 py-3 border-b border-dark-border cursor-grab hover:bg-dark-border-light transition-colors"
        onMouseDown={handleMouseDown}
      >
        <div className="flex justify-between items-center">
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
      </div>
      
      <div className="p-4 max-h-[70vh] overflow-y-auto">

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
              <p className="text-xs text-dark-text-muted">{(element.data.from_subscene as string) || 'Not specified'}</p>
            </div>

            <div className="p-3 bg-dark-bg-lighter border border-dark-border rounded-lg">
              <p className="text-sm text-dark-text-secondary mb-2">To Subscene</p>
              <p className="text-xs text-dark-text-muted">{(element.data.to_subscene as string) || 'Not specified'}</p>
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
            onClick={() => void handleSave()}
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
