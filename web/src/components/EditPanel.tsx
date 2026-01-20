import React, { useState, useEffect } from 'react';
import SubsceneModal, { SubsceneFormData } from './SubsceneModal';
import ConnectionModal, { ConnectionFormData } from './ConnectionModal';

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
  onNodeUpdate: (nodeId: string, data: SubsceneFormData) => void;
  onEdgeUpdate: (edgeId: string, data: ConnectionFormData) => void;
}

function EditPanel({ element, sceneId, onClose, onNodeUpdate, onEdgeUpdate }: EditPanelProps) {
  const [isSubsceneModalOpen, setIsSubsceneModalOpen] = useState(false);
  const [isConnectionModalOpen, setIsConnectionModalOpen] = useState(false);

  useEffect(() => {
    if (element) {
      if (element.type === 'node') {
        setIsSubsceneModalOpen(true);
      } else if (element.type === 'edge') {
        setIsConnectionModalOpen(true);
      }
    } else {
      setIsSubsceneModalOpen(false);
      setIsConnectionModalOpen(false);
    }
  }, [element]);

  const handleSubsceneModalClose = () => {
    setIsSubsceneModalOpen(false);
    onClose();
  };

  const handleConnectionModalClose = () => {
    setIsConnectionModalOpen(false);
    onClose();
  };

  const handleSubsceneSave = (data: SubsceneFormData) => {
    if (element && element.type === 'node') {
      onNodeUpdate(element.id, data);
    }
    setIsSubsceneModalOpen(false);
    onClose();
  };

  const handleConnectionSave = (data: ConnectionFormData) => {
    if (element && element.type === 'edge') {
      onEdgeUpdate(element.id, data);
    }
    setIsConnectionModalOpen(false);
    onClose();
  };

  const getSubsceneInitialData = (): Partial<SubsceneFormData> => {
    if (!element || element.type !== 'node') return {};
    return {
      name: (element.data.label as string) || '',
      type: (element.data.type as 'start' | 'normal' | 'end') || 'normal',
      mandatory: (element.data.mandatory as boolean) || false,
      objective: (element.data.objective as string) || ''
    };
  };

  const getConnectionInitialData = (): Partial<ConnectionFormData> => {
    if (!element || element.type !== 'edge') return {};
    return {
      name: (element.data.label as string) || '',
      condition: (element.data.condition as string) || '',
      from_subscene: (element.data.from_subscene as string) || '',
      to_subscene: (element.data.to_subscene as string) || ''
    };
  };

  return (
    <>
      {element?.type === 'node' && (
        <SubsceneModal
          isOpen={isSubsceneModalOpen}
          mode="edit"
          sceneId={sceneId}
          initialData={getSubsceneInitialData()}
          existingSubsceneName={element.id.replace('subscene-', '')}
          onClose={handleSubsceneModalClose}
          onSave={handleSubsceneSave}
        />
      )}

      {element?.type === 'edge' && (
        <ConnectionModal
          isOpen={isConnectionModalOpen}
          mode="edit"
          sceneId={sceneId}
          initialData={getConnectionInitialData()}
          existingConnection={{
            from: (element.data.from_subscene as string) || '',
            to: (element.data.to_subscene as string) || ''
          }}
          onClose={handleConnectionModalClose}
          onSave={handleConnectionSave}
        />
      )}
    </>
  );
}

export default EditPanel;
