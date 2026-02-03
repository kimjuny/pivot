import { Eye, X } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ControlButtonsProps {
  mode: 'edit' | 'preview';
  onModeChange: (mode: 'edit' | 'preview') => void;
}

/**
 * Control buttons for switching between edit and preview modes.
 * Shows Preview button in edit mode, Close button in preview mode.
 * Positioned at top-right of the main content area.
 */
function ControlButtons({ mode, onModeChange }: ControlButtonsProps) {
  return (
    <div className="absolute top-3 right-3 z-10 flex gap-2">
      {mode === 'edit' ? (
        <Button
          variant="default"
          size="sm"
          onClick={() => onModeChange('preview')}
          className="gap-1.5"
        >
          <Eye className="h-3.5 w-3.5" />
          Preview
        </Button>
      ) : (
        <Button
          variant="outline"
          size="sm"
          onClick={() => onModeChange('edit')}
          className="gap-1.5"
        >
          <X className="h-3.5 w-3.5" />
          Close Preview
        </Button>
      )}
    </div>
  );
}

export default ControlButtons;
