import React from 'react';

interface ControlButtonsProps {
  mode: 'edit' | 'preview';
  onModeChange: (mode: 'edit' | 'preview') => void;
  isSidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}

function ControlButtons({ mode, onModeChange, isSidebarCollapsed, onToggleSidebar }: ControlButtonsProps) {
  return (
    <>
      <div className="absolute top-4 right-4 z-10 flex space-x-2">
        <button
          onClick={() => onModeChange('preview')}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
            mode === 'preview'
              ? 'bg-primary text-white shadow-glow-sm'
              : 'bg-dark-bg-lighter border border-dark-border hover:bg-primary hover:border-primary hover:shadow-glow-sm'
          }`}
          title={mode === 'preview' ? 'Exit Preview' : 'Enter Preview'}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542 7z" />
          </svg>
          <span>Preview</span>
        </button>
        <button
          onClick={() => onModeChange('edit')}
          className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 ${
            mode === 'edit'
              ? 'bg-primary text-white shadow-glow-sm'
              : 'bg-dark-bg-lighter border border-dark-border hover:bg-primary hover:border-primary hover:shadow-glow-sm'
          }`}
          title={mode === 'edit' ? 'Exit Edit' : 'Enter Edit'}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 0L21 8M21 3l-9 9m0 0l-3 3m3-3l3 3" />
          </svg>
          <span>Edit</span>
        </button>
      </div>

      <button
        onClick={onToggleSidebar}
        className={`absolute top-1/2 -translate-y-1/2 z-10 p-2.5 rounded-lg transition-all duration-200 group ${
          isSidebarCollapsed
            ? 'left-2 bg-dark-bg-lighter border border-dark-border hover:bg-primary hover:border-primary hover:shadow-glow-sm'
            : '-left-3 bg-dark-bg border border-dark-border hover:bg-primary hover:border-primary hover:shadow-glow-sm'
        }`}
        title={isSidebarCollapsed ? 'Expand Scenes' : 'Collapse Scenes'}
      >
        <svg
          className={`w-5 h-5 text-dark-text-secondary transition-transform duration-200 ${isSidebarCollapsed ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M11 19l-7-7 7-7m8 14l-7-7 7-7"
          />
        </svg>
      </button>
    </>
  );
}

export default ControlButtons;
