import { useState, useEffect } from 'react';
import { Info, ChevronDown, ChevronUp } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

export interface LLMFormData {
  name: string;
  endpoint: string;
  model: string;
  api_key: string;
  protocol: string;
  chat: boolean;
  system_role: boolean;
  tool_calling: string;
  json_schema: string;
  streaming: boolean;
  max_context: number;
}

interface LLMModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  initialData?: Partial<LLMFormData>;
  onClose: () => void;
  onSave: (data: LLMFormData) => Promise<void>;
}

/**
 * Modal for creating or editing an LLM configuration.
 * Uses shadcn Dialog with form inputs for LLM properties.
 */
function LLMModal({ isOpen, mode, initialData, onClose, onSave }: LLMModalProps) {
  const [formData, setFormData] = useState<LLMFormData>({
    name: '',
    endpoint: '',
    model: '',
    api_key: '',
    protocol: 'openai_compatible',
    chat: true,
    system_role: true,
    tool_calling: 'native',
    json_schema: 'strong',
    streaming: true,
    max_context: 128000,
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          endpoint: initialData.endpoint || '',
          model: initialData.model || '',
          api_key: initialData.api_key || '',
          protocol: initialData.protocol || 'openai_compatible',
          chat: initialData.chat !== undefined ? initialData.chat : true,
          system_role: initialData.system_role !== undefined ? initialData.system_role : true,
          tool_calling: initialData.tool_calling || 'native',
          json_schema: initialData.json_schema || 'strong',
          streaming: initialData.streaming !== undefined ? initialData.streaming : true,
          max_context: initialData.max_context || 128000,
        });
      } else {
        setFormData({
          name: '',
          endpoint: '',
          model: '',
          api_key: '',
          protocol: 'openai_compatible',
          chat: true,
          system_role: true,
          tool_calling: 'native',
          json_schema: 'strong',
          streaming: true,
          max_context: 128000,
        });
      }
      setServerError(null);
    }
  }, [isOpen, mode, initialData]);

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setServerError('LLM name is required');
      return;
    }
    if (!formData.endpoint.trim()) {
      setServerError('Endpoint is required');
      return;
    }
    if (!formData.model.trim()) {
      setServerError('Model is required');
      return;
    }
    if (!formData.api_key.trim()) {
      setServerError('API Key is required');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      await onSave(formData);
      onClose();
    } catch (err) {
      const error = err as Error;
      setServerError(error.message || 'Failed to save LLM');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {mode === 'create' ? 'New LLM' : 'Edit LLM'}
          </DialogTitle>
        </DialogHeader>

        {serverError && (
          <div className="rounded-md bg-destructive/10 border border-destructive/20 px-4 py-3">
            <p className="text-sm text-destructive">{serverError}</p>
          </div>
        )}

        <TooltipProvider>
          <div className="space-y-4 py-4">
            {/* Required Fields */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <div className="flex items-center gap-1.5">
                  <Label htmlFor="name">
                    Name <span className="text-destructive">*</span>
                  </Label>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      <p>Unique logical name for the LLM in your platform. Used for agent selection, scheduling, and monitoring.</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                <Input
                  id="name"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  disabled={isSubmitting}
                  placeholder="my-llm"
                  autoComplete="off"
                />
              </div>

              <div className="space-y-2">
                <div className="flex items-center gap-1.5">
                  <Label htmlFor="model">
                    Model <span className="text-destructive">*</span>
                  </Label>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      <p>Model identifier passed to the API. Completely defined by the LLM provider (e.g., gpt-4, claude-3).</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                <Input
                  id="model"
                  value={formData.model}
                  onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                  disabled={isSubmitting}
                  placeholder="gpt-4"
                  autoComplete="off"
                />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="endpoint">
                  Endpoint <span className="text-destructive">*</span>
                </Label>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <p>HTTP API Base URL for the LLM service. Does not include specific paths (determined by protocol).</p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <Input
                id="endpoint"
                value={formData.endpoint}
                onChange={(e) => setFormData({ ...formData, endpoint: e.target.value })}
                disabled={isSubmitting}
                placeholder="https://api.openai.com/v1"
                autoComplete="off"
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="api_key">
                  API Key <span className="text-destructive">*</span>
                </Label>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <p>Authentication credential for calling the LLM. Should be encrypted in storage and never echoed back.</p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <Input
                id="api_key"
                type="password"
                value={formData.api_key}
                onChange={(e) => setFormData({ ...formData, api_key: e.target.value })}
                disabled={isSubmitting}
                placeholder="sk-..."
                autoComplete="off"
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center gap-1.5">
                <Label htmlFor="protocol">
                  Protocol <span className="text-destructive">*</span>
                </Label>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs">
                    <p>Request/response protocol specification. Determines API paths, payload structure, and tool calling format.</p>
                  </TooltipContent>
                </Tooltip>
              </div>
              <Select
                value={formData.protocol}
                onValueChange={(value) => setFormData({ ...formData, protocol: value })}
                disabled={isSubmitting}
              >
                <SelectTrigger id="protocol">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="openai_compatible">OpenAI Compatible</SelectItem>
                  <SelectItem value="anthropic_compatible">Anthropic Compatible</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Advanced Options Toggle */}
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              {showAdvanced ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              <span>Advanced Options</span>
            </button>

            {/* Advanced Fields */}
            {showAdvanced && (
              <div className="space-y-4 pt-2">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="max_context">Max Context</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Maximum context token limit. Affects history truncation, RAG chunk count, and memory management.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Input
                      id="max_context"
                      type="number"
                      value={formData.max_context}
                      onChange={(e) => setFormData({ ...formData, max_context: parseInt(e.target.value) || 128000 })}
                      disabled={isSubmitting}
                      placeholder="128000"
                      autoComplete="off"
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="tool_calling">Tool Calling</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Tool calling support level. Native: structured tool calls; Prompt: simulated via prompt; None: no tool support.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Select
                      value={formData.tool_calling}
                      onValueChange={(value) => setFormData({ ...formData, tool_calling: value })}
                      disabled={isSubmitting}
                    >
                      <SelectTrigger id="tool_calling">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="native">Native</SelectItem>
                        <SelectItem value="prompt">Prompt-based</SelectItem>
                        <SelectItem value="none">None</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Label htmlFor="json_schema">JSON Schema</Label>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs">
                        <p>Structured JSON output reliability. Strong: native schema constraints; Weak: prompt-based; None: unreliable.</p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <Select
                    value={formData.json_schema}
                    onValueChange={(value) => setFormData({ ...formData, json_schema: value })}
                    disabled={isSubmitting}
                  >
                    <SelectTrigger id="json_schema">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="strong">Strong</SelectItem>
                      <SelectItem value="weak">Weak</SelectItem>
                      <SelectItem value="none">None</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-3 pt-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="chat" className="cursor-pointer">Multi-turn Chat</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Whether the model supports multi-turn conversation with message roles (messages[] vs single prompt).</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Switch
                      id="chat"
                      checked={formData.chat}
                      onCheckedChange={(checked) => setFormData({ ...formData, chat: checked })}
                      disabled={isSubmitting}
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="system_role" className="cursor-pointer">System Role</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Whether the model truly distinguishes system role with higher instruction priority vs merging into user messages.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Switch
                      id="system_role"
                      checked={formData.system_role}
                      onCheckedChange={(checked) => setFormData({ ...formData, system_role: checked })}
                      disabled={isSubmitting}
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="streaming" className="cursor-pointer">Streaming</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Whether the model supports streaming responses (chunk/event stream) for real-time output.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Switch
                      id="streaming"
                      checked={formData.streaming}
                      onCheckedChange={(checked) => setFormData({ ...formData, streaming: checked })}
                      disabled={isSubmitting}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </TooltipProvider>

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
            disabled={isSubmitting || !formData.name.trim() || !formData.endpoint.trim() || !formData.model.trim() || !formData.api_key.trim()}
          >
            {isSubmitting ? 'Saving…' : mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default LLMModal;
