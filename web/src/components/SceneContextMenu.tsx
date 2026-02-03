import React from 'react';
import { Plus, Trash2 } from 'lucide-react';

export type ContextMenuContext = 'pane' | 'node' | 'edge';

interface SceneContextMenuProps {
  position: { x: number; y: number } | null;
  context: ContextMenuContext;
  element?: { id: string; data?: Record<string, unknown> };
  onAddSubscene: () => void;
  onRemoveNode?: (nodeId: string) => void;
  onRemoveEdge?: (edgeId: string) => void;
}

/**
 * Context menu for React Flow canvas interactions.
 * Uses shadcn-style components but with imperative positioning for ReactFlow compatibility.
 */
function SceneContextMenu({
  position,
  context,
  element,
  onAddSubscene,
  onRemoveNode,
  onRemoveEdge
}: SceneContextMenuProps) {
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
      className="fixed z-50 min-w-[7rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95 duration-200"
      style={{
        left: position.x,
        top: position.y
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {context === 'pane' && (
        <div
          onClick={onAddSubscene}
          className="relative flex cursor-default select-none items-center gap-1.5 rounded-sm px-1.5 py-1 text-xs outline-none transition-colors hover:bg-accent hover:text-accent-foreground [&>svg]:size-3.5 [&>svg]:shrink-0"
        >
          <Plus />
          <span>Add Subscene</span>
        </div>
      )}

      {(context === 'node' || context === 'edge') && (
        <div
          onClick={handleRemove}
          className="relative flex cursor-default select-none items-center gap-1.5 rounded-sm px-1.5 py-1 text-xs outline-none transition-colors text-danger hover:bg-danger/10 hover:text-danger [&>svg]:size-3.5 [&>svg]:shrink-0"
        >
          <Trash2 />
          <span>Remove {context === 'node' ? 'Subscene' : 'Connection'}</span>
        </div>
      )}
    </div>
  );
}

export default SceneContextMenu;
