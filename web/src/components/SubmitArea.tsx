import React from 'react';

interface SubmitAreaProps {
  hasUnsavedChanges: boolean;
  isSubmitting: boolean;
  onSubmit: () => void | Promise<void>;
  onDiscard: () => void;
}

function SubmitArea({ hasUnsavedChanges, isSubmitting, onSubmit, onDiscard }: SubmitAreaProps) {
  if (!hasUnsavedChanges) {
    return null;
  }

  return (
    <div className="fixed bottom-8 left-1/2 transform -translate-x-1/2 z-50">
      <div className="bg-dark-bg border border-dark-border rounded-xl shadow-2xl px-6 py-4 flex items-center space-x-4">
        <span className="text-sm text-gray-400">
          You have unsaved changes
        </span>
        <button
          onClick={onDiscard}
          disabled={isSubmitting}
          className="px-4 py-2 bg-dark-surface text-gray-300 rounded-lg hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
        >
          Discard
        </button>
        <button
          onClick={() => void onSubmit()}
          disabled={isSubmitting}
          className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
        >
          {isSubmitting ? 'Submitting...' : 'Submit'}
        </button>
      </div>
    </div>
  );
}

export default SubmitArea;
