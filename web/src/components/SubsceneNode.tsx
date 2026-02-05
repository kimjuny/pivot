import React from 'react';
import { Handle, Position } from '@xyflow/react';

interface SubsceneNodeData {
  label: string;
  type: string;
  state?: string;
  mandatory?: boolean;
  objective?: string;
}

interface SubsceneNodeProps {
  data: SubsceneNodeData;
  onClick?: () => void;
}

function SubsceneNode({ data, onClick }: SubsceneNodeProps) {
  const getTypeColor = (type: string): string => {
    switch (type) {
      case 'start':
        return 'bg-white dark:bg-dark-bg border-success text-gray-900 dark:text-white';
      case 'end':
        return 'bg-white dark:bg-dark-bg border-danger text-gray-900 dark:text-white';
      case 'normal':
        return 'bg-white dark:bg-dark-bg border-primary text-gray-900 dark:text-white';
      default:
        return 'bg-white dark:bg-dark-bg border-gray-300 dark:border-dark-border text-gray-900 dark:text-white';
    }
  };

  const isActive = data.state?.toLowerCase() === 'active';
  const typeClasses = getTypeColor(data.type);
  const activeClass = isActive ? 'ring-2 ring-danger shadow-glow-sm' : '';

  return (
    <div
      onClick={onClick}
      className={`px-4 py-3 rounded-xl border-2 shadow-md ${typeClasses} ${activeClass} transition-all duration-200 hover:shadow-lg hover:scale-105 hover:brightness-110 cursor-pointer`}
    >
      <Handle
        type="source"
        position={Position.Right}
        id="right"
        className="w-4 h-4 bg-primary hover:bg-primary/90 rounded-full border-2 border-gray-200 dark:border-white shadow-md"
      />
      <Handle
        type="target"
        position={Position.Left}
        id="left"
        className="w-4 h-4 bg-primary hover:bg-primary/90 rounded-full border-2 border-gray-200 dark:border-white shadow-md"
      />
      <div className="font-semibold text-sm truncate">{data.label}</div>
      <div className="text-xs mt-1 capitalize opacity-80">{data.type}</div>
      {isActive && <div className="text-xs text-danger font-bold mt-1.5 flex items-center">
        <span className="inline-block w-2 h-2 bg-danger rounded-full animate-pulse mr-1.5"></span>
        ACTIVE
      </div>}
    </div>
  );
}

export default SubsceneNode;
