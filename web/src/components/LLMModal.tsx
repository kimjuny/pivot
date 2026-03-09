import { useState, useEffect } from 'react';
import { Info, ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react';
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
  cache_policy: string;
  chat: boolean;
  system_role: boolean;
  tool_calling: string;
  json_schema: string;
  thinking: string;
  streaming: boolean;
  image_input: boolean;
  image_output: boolean;
  max_context: number;
  extra_config: string;
}

interface LLMModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  initialData?: Partial<LLMFormData>;
  onClose: () => void;
  onSave: (data: LLMFormData) => Promise<void>;
}

interface ExtraConfigEntry {
  id: string;
  key: string;
  value: string;
}

function createExtraConfigEntry(key = '', value = ''): ExtraConfigEntry {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    key,
    value,
  };
}

/**
 * Parses raw JSON object string into editable key/value rows.
 *
 * Why: row-based editor is easier to use than free-form JSON for most users.
 */
function parseExtraConfigEntries(rawExtraConfig: string): ExtraConfigEntry[] {
  const trimmed = rawExtraConfig.trim();
  if (!trimmed) {
    return [createExtraConfigEntry()];
  }

  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const entries = Object.entries(parsed as Record<string, unknown>).map(([key, value]) =>
        createExtraConfigEntry(
          key,
          typeof value === 'string' ? value : JSON.stringify(value),
        ),
      );
      return entries.length > 0 ? entries : [createExtraConfigEntry()];
    }
  } catch {
    return [createExtraConfigEntry('', rawExtraConfig)];
  }

  return [createExtraConfigEntry('', rawExtraConfig)];
}

/**
 * Validates and normalizes row-based extra config entries.
 *
 * Why: callers can type plain strings or JSON blocks as values, and each row
 * must become a payload key-value pair sent to LLM request parameters.
 */
function validateAndNormalizeExtraConfigEntries(
  entries: ExtraConfigEntry[],
): { normalized: string; error: string | null } {
  const normalizedObject: Record<string, unknown> = {};

  for (const entry of entries) {
    const key = entry.key.trim();
    if (!key) {
      if (entry.value.trim()) {
        return { normalized: '', error: 'Extra Config key cannot be empty' };
      }
      continue;
    }
    if (key in normalizedObject) {
      return { normalized: '', error: `Duplicate Extra Config key: ${key}` };
    }

    const rawValue = entry.value.trim();
    if (!rawValue) {
      normalizedObject[key] = '';
      continue;
    }

    try {
      normalizedObject[key] = JSON.parse(rawValue) as unknown;
      continue;
    } catch {
      // Keep non-JSON value as plain string for user-friendly editing.
    }

    if (rawValue.startsWith('{') || rawValue.startsWith('[')) {
      return {
        normalized: '',
        error: `Extra Config value for "${key}" looks like JSON but is invalid`,
      };
    }

    normalizedObject[key] = entry.value;
  }

  if (Object.keys(normalizedObject).length === 0) {
    return { normalized: '', error: null };
  }

  return { normalized: JSON.stringify(normalizedObject), error: null };
}

const CACHE_POLICY_OPTIONS: Record<string, { value: string; label: string }[]> = {
  openai_completion_llm: [
    { value: 'none', label: 'None' },
    { value: 'qwen-completion-block-cache', label: 'Qwen Completion Block Cache' },
    {
      value: 'kimi-completion-prompt-cache-key',
      label: 'Kimi Completion Prompt Cache Key',
    },
  ],
  openai_response_llm: [
    { value: 'none', label: 'None' },
    {
      value: 'openai-response-prompt-cache-key',
      label: 'OpenAI Response Prompt Cache Key',
    },
    { value: 'doubao-response-previous-id', label: 'Doubao Response Previous ID' },
  ],
  anthropic_compatible: [
    { value: 'none', label: 'None' },
    { value: 'anthropic-auto-cache', label: 'Anthropic Auto Cache' },
    { value: 'anthropic-block-cache', label: 'Anthropic Block Cache' },
  ],
};

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
    protocol: 'openai_completion_llm',
    cache_policy: 'none',
    chat: true,
    system_role: true,
    tool_calling: 'native',
    json_schema: 'strong',
    thinking: 'auto',
    streaming: true,
    image_input: false,
    image_output: false,
    max_context: 128000,
    extra_config: '',
  });
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [showCacheControl, setShowCacheControl] = useState<boolean>(true);
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [extraConfigEntries, setExtraConfigEntries] = useState<ExtraConfigEntry[]>([
    createExtraConfigEntry(),
  ]);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          endpoint: initialData.endpoint || '',
          model: initialData.model || '',
          api_key: initialData.api_key || '',
          protocol: initialData.protocol || 'openai_completion_llm',
          cache_policy: initialData.cache_policy || 'none',
          chat: initialData.chat !== undefined ? initialData.chat : true,
          system_role: initialData.system_role !== undefined ? initialData.system_role : true,
          tool_calling: initialData.tool_calling || 'native',
          json_schema: initialData.json_schema || 'strong',
          thinking: initialData.thinking || 'auto',
          streaming: initialData.streaming !== undefined ? initialData.streaming : true,
          image_input: initialData.image_input !== undefined ? initialData.image_input : false,
          image_output: initialData.image_output !== undefined ? initialData.image_output : false,
          max_context: initialData.max_context || 128000,
          extra_config: initialData.extra_config || '',
        });
        setExtraConfigEntries(parseExtraConfigEntries(initialData.extra_config || ''));
      } else {
        setFormData({
          name: '',
          endpoint: '',
          model: '',
          api_key: '',
          protocol: 'openai_completion_llm',
          cache_policy: 'none',
          chat: true,
          system_role: true,
          tool_calling: 'native',
          json_schema: 'strong',
          thinking: 'auto',
          streaming: true,
          image_input: false,
          image_output: false,
          max_context: 128000,
          extra_config: '',
        });
        setExtraConfigEntries([createExtraConfigEntry()]);
      }
      setServerError(null);
    }
  }, [isOpen, mode, initialData]);

  useEffect(() => {
    const options = CACHE_POLICY_OPTIONS[formData.protocol] ?? [{ value: 'none', label: 'None' }];
    const isCurrentValid = options.some((option) => option.value === formData.cache_policy);
    if (!isCurrentValid) {
      setFormData((prev) => ({ ...prev, cache_policy: 'none' }));
    }
  }, [formData.protocol, formData.cache_policy]);

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
    const { normalized, error } = validateAndNormalizeExtraConfigEntries(extraConfigEntries);
    if (error) {
      setServerError(error);
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      await onSave({
        ...formData,
        extra_config: normalized,
      });
      onClose();
    } catch (err) {
      const error = err as Error;
      setServerError(error.message || 'Failed to save LLM');
    } finally {
      setIsSubmitting(false);
    }
  };

  const updateExtraConfigEntry = (
    id: string,
    field: 'key' | 'value',
    value: string,
  ) => {
    setExtraConfigEntries((prev) =>
      prev.map((entry) => (entry.id === id ? { ...entry, [field]: value } : entry)),
    );
  };

  const addExtraConfigEntry = () => {
    setExtraConfigEntries((prev) => [...prev, createExtraConfigEntry()]);
  };

  const removeExtraConfigEntry = (id: string) => {
    setExtraConfigEntries((prev) => {
      const next = prev.filter((entry) => entry.id !== id);
      return next.length > 0 ? next : [createExtraConfigEntry()];
    });
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
                  <SelectItem value="openai_completion_llm">
                    OpenAI Completion LLM
                  </SelectItem>
                  <SelectItem value="openai_response_llm">
                    OpenAI Response LLM
                  </SelectItem>
                  <SelectItem value="anthropic_compatible">Anthropic Compatible</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Cache Control Toggle */}
            <button
              type="button"
              onClick={() => setShowCacheControl(!showCacheControl)}
              className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              {showCacheControl ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              <span>Cache Control</span>
            </button>

            {showCacheControl && (
              <div className="space-y-2">
                <div className="flex items-center gap-1.5">
                  <Label htmlFor="cache_policy">Cache Policy</Label>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      <p>Protocol-specific caching strategy. None means non-cached communication.</p>
                    </TooltipContent>
                  </Tooltip>
                </div>
                <Select
                  value={formData.cache_policy}
                  onValueChange={(value) => setFormData({ ...formData, cache_policy: value })}
                  disabled={isSubmitting}
                >
                  <SelectTrigger id="cache_policy">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(CACHE_POLICY_OPTIONS[formData.protocol] ?? []).map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

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

                <div className="space-y-2">
                  <div className="flex items-center gap-1.5">
                    <Label htmlFor="thinking">Thinking</Label>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                      </TooltipTrigger>
                      <TooltipContent side="top" className="max-w-xs">
                        <p>Controls protocol-level thinking/reasoning flags. Auto passes no explicit parameter; Enabled/Disabled sets explicit provider flags.</p>
                      </TooltipContent>
                    </Tooltip>
                  </div>
                  <Select
                    value={formData.thinking}
                    onValueChange={(value) => setFormData({ ...formData, thinking: value })}
                    disabled={isSubmitting}
                  >
                    <SelectTrigger id="thinking">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">Auto</SelectItem>
                      <SelectItem value="enabled">Enabled</SelectItem>
                      <SelectItem value="disabled">Disabled</SelectItem>
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

                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="image_input" className="cursor-pointer">Image Input</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Whether the model accepts uploaded or pasted user images as part of chat input.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Switch
                      id="image_input"
                      checked={formData.image_input}
                      onCheckedChange={(checked) => setFormData({ ...formData, image_input: checked })}
                      disabled={isSubmitting}
                    />
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Label htmlFor="image_output" className="cursor-pointer">Image Output</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Whether the model can generate or return images in its responses.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Switch
                      id="image_output"
                      checked={formData.image_output}
                      onCheckedChange={(checked) => setFormData({ ...formData, image_output: checked })}
                      disabled={isSubmitting}
                    />
                  </div>
                </div>

                {/* Extra Config */}
                <div className="space-y-2 pt-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Label>Extra Config</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                        </TooltipTrigger>
                        <TooltipContent side="top" className="max-w-xs">
                          <p>Each key-value pair is sent as request params to the LLM API. Value supports JSON (object/array/number/boolean) or plain string.</p>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={addExtraConfigEntry}
                      disabled={isSubmitting}
                      className="h-8 px-2"
                      aria-label="Add extra config row"
                    >
                      <Plus className="w-4 h-4" />
                    </Button>
                  </div>
                  <div className="space-y-2">
                    {extraConfigEntries.map((entry) => (
                      <div key={entry.id} className="grid grid-cols-[1fr_auto_2fr_auto] gap-2 items-center">
                        <Input
                          value={entry.key}
                          onChange={(e) => updateExtraConfigEntry(entry.id, 'key', e.target.value)}
                          disabled={isSubmitting}
                          placeholder="key (e.g. response_format)"
                          autoComplete="off"
                        />
                        <span className="text-muted-foreground text-sm px-1" aria-hidden="true">
                          =
                        </span>
                        <Input
                          value={entry.value}
                          onChange={(e) => updateExtraConfigEntry(entry.id, 'value', e.target.value)}
                          disabled={isSubmitting}
                          placeholder='value (e.g. {"type":"json_object"} or hello)'
                          className="font-mono"
                          autoComplete="off"
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => removeExtraConfigEntry(entry.id)}
                          disabled={isSubmitting}
                          className="h-9 w-9 p-0"
                          aria-label="Remove extra config row"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    ))}
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
