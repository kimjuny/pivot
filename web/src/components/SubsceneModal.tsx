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
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export interface SubsceneFormData {
  name: string;
  type: 'start' | 'normal' | 'end';
  mandatory: boolean;
  objective: string;
}

interface SubsceneModalProps {
  isOpen: boolean;
  mode: 'add' | 'edit';
  sceneId: number | null;
  initialData?: Partial<SubsceneFormData>;
  existingSubsceneName?: string;
  onClose: () => void;
  onSave: (data: SubsceneFormData) => void;
}

/**
 * Modal for adding or editing a subscene.
 * Uses shadcn Dialog with form inputs for subscene properties.
 */
function SubsceneModal({
  isOpen,
  mode,
  sceneId,
  initialData,
  existingSubsceneName,
  onClose,
  onSave
}: SubsceneModalProps) {
  const [formData, setFormData] = useState<SubsceneFormData>({
    name: '',
    type: 'normal',
    mandatory: false,
    objective: ''
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          type: initialData.type || 'normal',
          mandatory: initialData.mandatory || false,
          objective: initialData.objective || ''
        });
      } else {
        setFormData({
          name: '',
          type: 'normal',
          mandatory: false,
          objective: ''
        });
      }
      setServerError(null);
    }
  }, [isOpen, mode, initialData]);

  const handleSubmit = () => {
    if (!formData.name.trim()) {
      setServerError('Subscene name is required');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      onSave({
        name: formData.name.trim(),
        type: formData.type,
        mandatory: formData.mandatory,
        objective: formData.objective.trim()
      });
      onClose();
    } catch (err) {
      const error = err as Error;
      setServerError(error.message || 'Failed to save subscene');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {mode === 'add' ? 'Add Subscene' : 'Edit Subscene'}
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
              Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              disabled={isSubmitting}
              placeholder="Enter subscene name…"
              autoComplete="off"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="type">Type</Label>
            <Select
              value={formData.type}
              onValueChange={(value) => setFormData({ ...formData, type: value as 'start' | 'normal' | 'end' })}
              disabled={isSubmitting}
            >
              <SelectTrigger id="type">
                <SelectValue placeholder="Select type…" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="start">Start</SelectItem>
                <SelectItem value="normal">Normal</SelectItem>
                <SelectItem value="end">End</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center space-x-3">
            <Switch
              id="mandatory"
              checked={formData.mandatory}
              onCheckedChange={(checked) => setFormData({ ...formData, mandatory: checked })}
              disabled={isSubmitting}
            />
            <Label htmlFor="mandatory" className="cursor-pointer">Mandatory</Label>
          </div>

          <div className="space-y-2">
            <Label htmlFor="objective">Objective</Label>
            <Textarea
              id="objective"
              value={formData.objective}
              onChange={(e) => setFormData({ ...formData, objective: e.target.value })}
              disabled={isSubmitting}
              rows={3}
              placeholder="Enter objective (optional)…"
            />
          </div>
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

export default SubsceneModal;
