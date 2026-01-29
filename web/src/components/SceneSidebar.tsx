import React from 'react';
import type { Scene } from '../types';

interface SceneSidebarProps {
  scenes: Scene[];
  selectedScene: Scene | null;
  isCollapsed: boolean;
  onSceneSelect: (scene: Scene) => void;
  onToggleCollapse: () => void;
  onCreateScene: () => void;
  onDeleteScene: (scene: Scene) => void;
}

function SceneSidebar({ scenes, selectedScene, isCollapsed, onSceneSelect, onToggleCollapse, onCreateScene, onDeleteScene }: SceneSidebarProps) {
  return (
    <div
      className={`border-r border-dark-border bg-dark-bg overflow-hidden relative ${isCollapsed ? 'w-0' : 'w-64'
        } transition-all duration-300 ease-in-out`}
    >
      <div
        className={`p-4 overflow-y-auto h-full transition-opacity duration-150 ease-in-out ${isCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'
          }`}
      >
        <h3 className="text-md font-semibold mb-3 text-dark-text-secondary tracking-tight">Scenes</h3>
        <div className="space-y-2">
          {scenes && scenes.map((scene, index) => (
            <div
              key={`scene-${index}`}
              className="group"
            >
              <div
                onClick={() => onSceneSelect(scene)}
                className={`p-3 rounded-lg cursor-pointer transition-all flex justify-between items-center ${selectedScene?.name === scene.name
                  ? 'bg-primary/20 border border-primary shadow-glow-sm'
                  : 'bg-dark-bg-lighter border border-dark-border hover:bg-dark-border-light hover:border-dark-border'}`}
              >
                <div className="font-medium text-dark-text-primary">{scene.name}</div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteScene(scene);
                  }}
                  className="opacity-0 group-hover:opacity-100 text-danger hover:text-danger-600 transition-opacity p-1"
                  title="Delete scene"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>
        <button
          onClick={onCreateScene}
          className="w-full p-3 mt-4 flex items-center justify-center space-x-2 border-2 border-dashed border-primary/50 rounded-lg hover:border-primary hover:bg-primary/10 transition-all duration-200"
        >
          <svg className="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H8" />
          </svg>
          <span className="text-sm font-medium text-primary">Add Scene</span>
        </button>
      </div>
    </div>
  );
}

export default SceneSidebar;
