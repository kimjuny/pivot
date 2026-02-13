import { useState, useEffect } from 'react';
import { ChevronDown, Plus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { getLLMs } from '../utils/api';
import type { LLM } from '../types';
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
import { Separator } from '@/components/ui/separator';
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
  llm_id: number | undefined;
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
  const navigate = useNavigate();
  const [formData, setFormData] = useState<AgentFormData>({
    name: '',
    description: '',
    llm_id: undefined,
    is_active: true
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [availableLLMs, setAvailableLLMs] = useState<LLM[]>([]);
  const [loadingLLMs, setLoadingLLMs] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          description: initialData.description || '',
          llm_id: initialData.llm_id,
          is_active: initialData.is_active !== undefined ? initialData.is_active : true
        });
      } else {
        setFormData({
          name: '',
          description: '',
          llm_id: undefined,
          is_active: true
        });
      }
      setServerError(null);
      void loadLLMs();
    }
  }, [isOpen, mode, initialData]);

  const loadLLMs = async () => {
    setLoadingLLMs(true);
    try {
      const llms = await getLLMs();
      setAvailableLLMs(llms);
    } catch (err) {
      const error = err as Error;
      console.error('Failed to load LLMs:', error);
    } finally {
      setLoadingLLMs(false);
    }
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setServerError('Agent name is required');
      return;
    }
    if (!formData.llm_id) {
      setServerError('LLM selection is required');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      await onSave({
        name: formData.name.trim(),
        description: formData.description?.trim() || undefined,
        llm_id: formData.llm_id,
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
            {mode === 'create' ? 'New Agent' : 'Edit Agent'}
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
            <Label htmlFor="llm">
              LLM <span className="text-destructive">*</span>
            </Label>
            {loadingLLMs ? (
              <div className="flex h-9 w-full items-center rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm text-muted-foreground">
                Loading LLMs…
              </div>
            ) : (
              <Select
                value={formData.llm_id?.toString() || ''}
                onValueChange={(value) => {
                  if (value === '__add_new__') {
                    // Navigate to LLMs page to create new LLM
                    navigate('/llms');
                    onClose();
                  } else {
                    setFormData({ ...formData, llm_id: value ? parseInt(value) : undefined });
                  }
                }}
                disabled={isSubmitting}
              >
                <SelectTrigger id="llm">
                  <SelectValue placeholder="Select an LLM…" />
                </SelectTrigger>
                <SelectContent>
                  {availableLLMs.length === 0 ? (
                    <div className="px-2 py-6 text-center text-sm text-muted-foreground">
                      No LLMs available
                    </div>
                  ) : (
                    availableLLMs.map((llm) => (
                      <SelectItem key={llm.id} value={llm.id.toString()}>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{llm.name}</span>
                          <span className="text-xs text-muted-foreground">({llm.model})</span>
                        </div>
                      </SelectItem>
                    ))
                  )}
                  <Separator className="my-1" />
                  <SelectItem 
                    value="__add_new__"
                    className="text-muted-foreground hover:text-foreground focus:text-foreground"
                  >
                    <div className="flex items-center gap-2">
                      <Plus className="w-3.5 h-3.5" />
                      <span>Add New LLM</span>
                    </div>
                  </SelectItem>
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
            disabled={isSubmitting || !formData.name.trim() || !formData.llm_id}
          >
            {isSubmitting ? 'Saving…' : mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default AgentModal;
