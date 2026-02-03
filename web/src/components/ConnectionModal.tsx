import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';

export interface ConnectionFormData {
  name: string;
  condition: string;
  from_subscene: string;
  to_subscene: string;
}

interface ConnectionModalProps {
  isOpen: boolean;
  mode: 'add' | 'edit';
  sceneId: number | null;
  initialData?: Partial<ConnectionFormData>;
  existingConnection?: { from: string; to: string };
  onClose: () => void;
  onSave: (data: ConnectionFormData) => void;
}

/**
 * Modal for adding or editing a connection between subscenes.
 * Uses shadcn Dialog with form inputs for connection properties.
 */
function ConnectionModal({
  isOpen,
  mode,
  sceneId,
  initialData,
  existingConnection,
  onClose,
  onSave
}: ConnectionModalProps) {
  const [formData, setFormData] = useState<ConnectionFormData>({
    name: '',
    condition: '',
    from_subscene: '',
    to_subscene: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          condition: initialData.condition || '',
          from_subscene: initialData.from_subscene || '',
          to_subscene: initialData.to_subscene || ''
        });
      } else if (mode === 'add' && initialData) {
        setFormData({
          name: '',
          condition: '',
          from_subscene: initialData.from_subscene || '',
          to_subscene: initialData.to_subscene || ''
        });
      }
      setServerError(null);
    }
  }, [isOpen, mode, initialData]);

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      setServerError('Connection name is required');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      onSave({
        name: formData.name.trim(),
        condition: formData.condition.trim(),
        from_subscene: formData.from_subscene,
        to_subscene: formData.to_subscene
      });
      onClose();
    } catch (err) {
      const error = err as Error;
      setServerError(error.message || 'Failed to save connection');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {mode === 'add' ? 'Add Connection' : 'Edit Connection'}
          </DialogTitle>
        </DialogHeader>

        {serverError && (
          <div className="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-3">
            <p className="text-sm text-destructive">{serverError}</p>
          </div>
        )}

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="name">
              Connection Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              disabled={isSubmitting}
              placeholder="Enter connection name…"
              autoComplete="off"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="condition">Condition</Label>
            <Textarea
              id="condition"
              value={formData.condition}
              onChange={(e) => setFormData({ ...formData, condition: e.target.value })}
              disabled={isSubmitting}
              rows={3}
              placeholder="Enter condition (optional)…"
            />
          </div>

          {mode === 'add' && (
            <>
              <div className="space-y-2">
                <Label>From Subscene</Label>
                <div className="rounded-md border border-input bg-muted px-3 py-2">
                  <p className="text-sm text-muted-foreground">
                    {formData.from_subscene || 'Not specified'}
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <Label>To Subscene</Label>
                <div className="rounded-md border border-input bg-muted px-3 py-2">
                  <p className="text-sm text-muted-foreground">
                    {formData.to_subscene || 'Not specified'}
                  </p>
                </div>
              </div>
            </>
          )}

          {mode === 'edit' && existingConnection && (
            <>
              <div className="space-y-2">
                <Label>From Subscene</Label>
                <div className="rounded-md border border-input bg-muted px-3 py-2">
                  <p className="text-sm text-muted-foreground">
                    {existingConnection.from || 'Not specified'}
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <Label>To Subscene</Label>
                <div className="rounded-md border border-input bg-muted px-3 py-2">
                  <p className="text-sm text-muted-foreground">
                    {existingConnection.to || 'Not specified'}
                  </p>
                </div>
              </div>
            </>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => void handleSubmit()}
            disabled={isSubmitting || !formData.name.trim()}
          >
            {isSubmitting ? 'Saving…' : mode === 'add' ? 'Add' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ConnectionModal;
