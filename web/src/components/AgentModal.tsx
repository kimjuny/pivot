import { useState, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';
import { getModels } from '../utils/api';
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

export interface AgentFormData {
  name: string;
  description: string | undefined;
  model_name: string | undefined;
  is_active: boolean;
}

interface AgentModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  initialData?: Partial<AgentFormData>;
  onClose: () => void;
  onSave: (data: AgentFormData) => Promise<void>;
}

/**
 * Modal for creating or editing an agent.
 * Uses shadcn Dialog with form inputs for agent properties.
 */
function AgentModal({ isOpen, mode, initialData, onClose, onSave }: AgentModalProps) {
  const [formData, setFormData] = useState<AgentFormData>({
    name: '',
    description: '',
    model_name: '',
    is_active: true
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<{ label: string; value: string }[]>([]);
  const [loadingModels, setLoadingModels] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          description: initialData.description || '',
          model_name: initialData.model_name || '',
          is_active: initialData.is_active !== undefined ? initialData.is_active : true
        });
      } else {
        setFormData({
          name: '',
          description: '',
          model_name: '',
          is_active: true
        });
      }
      setServerError(null);
      void loadModels();
    }
  }, [isOpen, mode, initialData]);

  const loadModels = async () => {
    setLoadingModels(true);
    try {
      const models = await getModels();
      setAvailableModels(models.map((model) => ({ label: model, value: model })));
    } catch (err) {
      const error = err as Error;
      console.error('Failed to load models:', error);
    } finally {
      setLoadingModels(false);
    }
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setServerError('Agent name is required');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      await onSave({
        name: formData.name.trim(),
        description: formData.description?.trim() || undefined,
        model_name: formData.model_name?.trim() || undefined,
        is_active: formData.is_active
      });
      onClose();
    } catch (err) {
      const error = err as Error;
      setServerError(error.message || 'Failed to save agent');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {mode === 'create' ? 'Create New Agent' : 'Edit Agent'}
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
              Agent Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              disabled={isSubmitting}
              placeholder="Enter agent name…"
              autoComplete="off"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="description">Description</Label>
            <Textarea
              id="description"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              disabled={isSubmitting}
              rows={3}
              placeholder="Enter agent description (optional)…"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="model">Model Name</Label>
            {loadingModels ? (
              <div className="flex h-9 w-full items-center rounded-md border border-input bg-transparent px-3 py-2 text-sm text-muted-foreground">
                Loading models…
              </div>
            ) : (
              <Select
                value={formData.model_name || ''}
                onValueChange={(value) => setFormData({ ...formData, model_name: value || undefined })}
                disabled={isSubmitting}
              >
                <SelectTrigger id="model">
                  <SelectValue placeholder="Select a model (optional)…" />
                </SelectTrigger>
                <SelectContent>
                  {availableModels.map((model) => (
                    <SelectItem key={model.value} value={model.value}>
                      {model.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="flex items-center space-x-3">
            <Switch
              id="is_active"
              checked={formData.is_active}
              onCheckedChange={(checked) => setFormData({ ...formData, is_active: checked })}
              disabled={isSubmitting}
            />
            <Label htmlFor="is_active" className="cursor-pointer">Activate Agent</Label>
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
            {isSubmitting ? 'Saving…' : mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default AgentModal;
