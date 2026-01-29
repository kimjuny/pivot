import React from 'react';

export type ContextMenuContext = 'pane' | 'node' | 'edge';

interface SceneContextMenuProps {
  position: { x: number; y: number } | null;
  context: ContextMenuContext;
  element?: { id: string; data?: Record<string, unknown> };
  onAddSubscene: () => void;
  onRemoveNode?: (nodeId: string) => void;
  onRemoveEdge?: (edgeId: string) => void;
}

function SceneContextMenu({ position, context, element, onAddSubscene, onRemoveNode, onRemoveEdge }: SceneContextMenuProps) {
  if (!position) {
    return null;
  }

  const handleRemove = () => {
    if (context === 'node' && onRemoveNode && element) {
      onRemoveNode(element.id);
    } else if (context === 'edge' && onRemoveEdge && element) {
      onRemoveEdge(element.id);
    }
  };

  return (
    <div
      className="fixed z-50 bg-dark-bg-lighter border border-dark-border rounded-lg shadow-card-lg py-1 min-w-[160px]"
      style={{
        left: position.x,
        top: position.y
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {context === 'pane' && (
        <button
          onClick={onAddSubscene}
          className="w-full px-4 py-2 text-left text-sm text-dark-text-primary hover:bg-primary hover:text-white transition-colors flex items-center space-x-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H8" />
          </svg>
          <span>Add Subscene</span>
        </button>
      )}

      {(context === 'node' || context === 'edge') && (
        <button
          onClick={handleRemove}
          className="w-full px-4 py-2 text-left text-sm text-danger hover:bg-danger hover:text-white transition-colors flex items-center space-x-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span>Remove</span>
        </button>
      )}
    </div>
  );
}

export default SceneContextMenu;
