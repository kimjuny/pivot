import { useEffect, useState } from 'react';
import { Info, Plus, Trash2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/**
 * Editable LLM payload shared by the create and edit dialogs.
 */
export interface LLMFormData {
  name: string;
  endpoint: string;
  model: string;
  api_key: string;
  protocol: string;
  cache_policy: string;
  chat: boolean;
  system_role: boolean;
  /** Describes how the provider exposes tool invocation. */
  tool_calling: string;
  /** Describes how reliably the provider enforces JSON schema output. */
  json_schema: string;
  /** Controls provider-specific reasoning/thinking flags when supported. */
  thinking: string;
  streaming: boolean;
  image_input: boolean;
  image_output: boolean;
  max_context: number;
  /** Raw JSON object string merged into request kwargs at runtime. */
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

type LLMTabValue = 'general' | 'advanced' | 'others';

interface FormLabelProps {
  htmlFor?: string;
  label: string;
  tooltip: string;
  required?: boolean;
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
      const entries = Object.entries(parsed as Record<string, unknown>).map(
        ([key, value]) =>
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

function FormLabel({ htmlFor, label, tooltip, required = false }: FormLabelProps) {
  return (
    <div className="flex items-center gap-1.5">
      <Label htmlFor={htmlFor}>
        {label}
        {required && <span className="text-destructive"> *</span>}
      </Label>
      <Tooltip>
        <TooltipTrigger asChild>
          <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          <p>{tooltip}</p>
        </TooltipContent>
      </Tooltip>
    </div>
  );
}

function CapabilityToggle({
  id,
  label,
  checked,
  tooltip,
  disabled,
  onCheckedChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  tooltip: string;
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-border/60 px-4 py-3">
      <FormLabel htmlFor={id} label={label} tooltip={tooltip} />
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
      />
    </div>
  );
}

/**
 * Modal for creating or editing an LLM configuration.
 * Uses shadcn Dialog with tabbed sections for the main LLM properties.
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
  const [activeTab, setActiveTab] = useState<LLMTabValue>('general');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [extraConfigEntries, setExtraConfigEntries] = useState<ExtraConfigEntry[]>([
    createExtraConfigEntry(),
  ]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    setActiveTab('general');

    if (mode === 'edit' && initialData) {
      setFormData({
        name: initialData.name ?? '',
        endpoint: initialData.endpoint ?? '',
        model: initialData.model ?? '',
        api_key: initialData.api_key ?? '',
        protocol: initialData.protocol ?? 'openai_completion_llm',
        cache_policy: initialData.cache_policy ?? 'none',
        chat: initialData.chat ?? true,
        system_role: initialData.system_role ?? true,
        tool_calling: initialData.tool_calling ?? 'native',
        json_schema: initialData.json_schema ?? 'strong',
        thinking: initialData.thinking ?? 'auto',
        streaming: initialData.streaming ?? true,
        image_input: initialData.image_input ?? false,
        image_output: initialData.image_output ?? false,
        max_context: initialData.max_context ?? 128000,
        extra_config: initialData.extra_config ?? '',
      });
      setExtraConfigEntries(parseExtraConfigEntries(initialData.extra_config ?? ''));
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
  }, [initialData, isOpen, mode]);

  useEffect(() => {
    const options = CACHE_POLICY_OPTIONS[formData.protocol] ?? [{ value: 'none', label: 'None' }];
    const isCurrentValid = options.some((option) => option.value === formData.cache_policy);
    if (!isCurrentValid) {
      setFormData((prev) => ({ ...prev, cache_policy: 'none' }));
    }
  }, [formData.protocol, formData.cache_policy]);

  const updateFormField = <K extends keyof LLMFormData>(
    field: K,
    value: LLMFormData[K],
  ) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setServerError('LLM name is required');
      setActiveTab('general');
      return;
    }
    if (!formData.endpoint.trim()) {
      setServerError('Endpoint is required');
      setActiveTab('general');
      return;
    }
    if (!formData.model.trim()) {
      setServerError('Model is required');
      setActiveTab('general');
      return;
    }
    if (!formData.api_key.trim()) {
      setServerError('API Key is required');
      setActiveTab('general');
      return;
    }

    const { normalized, error } = validateAndNormalizeExtraConfigEntries(extraConfigEntries);
    if (error) {
      setServerError(error);
      setActiveTab('advanced');
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
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{mode === 'create' ? 'New LLM' : 'Edit LLM'}</DialogTitle>
        </DialogHeader>

        {serverError && (
          <div className="rounded-md border border-destructive/20 bg-destructive/10 px-4 py-3">
            <p className="text-sm text-destructive">{serverError}</p>
          </div>
        )}

        <TooltipProvider>
          <Tabs
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as LLMTabValue)}
            className="py-2"
          >
            <TabsList className="grid h-auto w-full grid-cols-3">
              <TabsTrigger value="general">General</TabsTrigger>
              <TabsTrigger value="advanced">Advanced</TabsTrigger>
              <TabsTrigger value="others">Others</TabsTrigger>
            </TabsList>

            <TabsContent value="general" className="space-y-4 pt-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <FormLabel
                    htmlFor="name"
                    label="Name"
                    tooltip="Unique logical name for the LLM in your platform. Used for agent selection, scheduling, and monitoring."
                    required
                  />
                  <Input
                    id="name"
                    value={formData.name}
                    onChange={(e) => updateFormField('name', e.target.value)}
                    disabled={isSubmitting}
                    placeholder="my-llm"
                    autoComplete="off"
                  />
                </div>

                <div className="space-y-2">
                  <FormLabel
                    htmlFor="model"
                    label="Model"
                    tooltip="Model identifier passed to the API. Completely defined by the LLM provider (for example gpt-4 or claude-3)."
                    required
                  />
                  <Input
                    id="model"
                    value={formData.model}
                    onChange={(e) => updateFormField('model', e.target.value)}
                    disabled={isSubmitting}
                    placeholder="gpt-4"
                    autoComplete="off"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <FormLabel
                  htmlFor="endpoint"
                  label="Endpoint"
                  tooltip="HTTP API base URL for the LLM service. It should not include the protocol-specific path suffix."
                  required
                />
                <Input
                  id="endpoint"
                  value={formData.endpoint}
                  onChange={(e) => updateFormField('endpoint', e.target.value)}
                  disabled={isSubmitting}
                  placeholder="https://api.openai.com/v1"
                  autoComplete="off"
                />
              </div>

              <div className="space-y-2">
                <FormLabel
                  htmlFor="api_key"
                  label="API Key"
                  tooltip="Authentication credential for calling the LLM. It should be stored securely and never echoed back in logs."
                  required
                />
                <Input
                  id="api_key"
                  type="password"
                  value={formData.api_key}
                  onChange={(e) => updateFormField('api_key', e.target.value)}
                  disabled={isSubmitting}
                  placeholder="sk-..."
                  autoComplete="off"
                />
              </div>

              <div className="space-y-2">
                <FormLabel
                  htmlFor="protocol"
                  label="Protocol"
                  tooltip="Request and response contract used by this provider. It determines paths, payload structure, and runtime compatibility."
                  required
                />
                <Select
                  value={formData.protocol}
                  onValueChange={(value) => updateFormField('protocol', value)}
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
                    <SelectItem value="anthropic_compatible">
                      Anthropic Compatible
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </TabsContent>

            <TabsContent value="advanced" className="space-y-4 pt-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <FormLabel
                    htmlFor="cache_policy"
                    label="Cache Control"
                    tooltip="Protocol-specific cache strategy. None means requests are always sent without reusable protocol cache hints."
                  />
                  <Select
                    value={formData.cache_policy}
                    onValueChange={(value) => updateFormField('cache_policy', value)}
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

                <div className="space-y-2">
                  <FormLabel
                    htmlFor="max_context"
                    label="Max Context"
                    tooltip="Maximum context token limit used by prompt-window estimation and truncation logic."
                  />
                  <Input
                    id="max_context"
                    type="number"
                    value={formData.max_context}
                    onChange={(e) =>
                      updateFormField(
                        'max_context',
                        Number.parseInt(e.target.value, 10) || 128000,
                      )
                    }
                    disabled={isSubmitting}
                    placeholder="128000"
                    autoComplete="off"
                  />
                </div>
              </div>

              <div className="space-y-3">
                <CapabilityToggle
                  id="streaming"
                  label="Streaming"
                  checked={formData.streaming}
                  tooltip="Whether the model supports chunked or event-stream style responses for real-time output."
                  disabled={isSubmitting}
                  onCheckedChange={(checked) => updateFormField('streaming', checked)}
                />
                <CapabilityToggle
                  id="image_input"
                  label="Image Input"
                  checked={formData.image_input}
                  tooltip="Whether the model accepts uploaded or pasted user images as part of input."
                  disabled={isSubmitting}
                  onCheckedChange={(checked) => updateFormField('image_input', checked)}
                />
                <CapabilityToggle
                  id="image_output"
                  label="Image Output"
                  checked={formData.image_output}
                  tooltip="Whether the model can generate or return images in responses."
                  disabled={isSubmitting}
                  onCheckedChange={(checked) => updateFormField('image_output', checked)}
                />
              </div>

              <div className="space-y-3 rounded-lg border border-border/60 p-4">
                <div className="flex items-center justify-between gap-3">
                  <FormLabel
                    label="Extra Config"
                    tooltip="Each key-value pair is sent as request params to the LLM API. Values can be JSON, numbers, booleans, arrays, or plain strings."
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={addExtraConfigEntry}
                    disabled={isSubmitting}
                    className="h-8 px-2"
                    aria-label="Add extra config row"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>

                <div className="space-y-2">
                  {extraConfigEntries.map((entry) => (
                    <div
                      key={entry.id}
                      className="grid grid-cols-[1fr_auto_2fr_auto] items-center gap-2"
                    >
                      <Input
                        value={entry.key}
                        onChange={(e) =>
                          updateExtraConfigEntry(entry.id, 'key', e.target.value)
                        }
                        disabled={isSubmitting}
                        placeholder="key (for example response_format)"
                        autoComplete="off"
                      />
                      <span
                        className="px-1 text-sm text-muted-foreground"
                        aria-hidden="true"
                      >
                        =
                      </span>
                      <Input
                        value={entry.value}
                        onChange={(e) =>
                          updateExtraConfigEntry(entry.id, 'value', e.target.value)
                        }
                        disabled={isSubmitting}
                        placeholder='value (for example {"type":"json_object"} or hello)'
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
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="others" className="space-y-4 pt-4">
              <div className="rounded-lg border border-dashed border-border/70 bg-muted/20 px-4 py-3">
                <p className="text-sm text-muted-foreground">
                  Temporary home for legacy capability flags. We can remove these
                  later after we confirm which ones still matter.
                </p>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <FormLabel
                    htmlFor="tool_calling"
                    label="Tool Calling"
                    tooltip="Tool calling support level. Native means structured tool calls, Prompt means simulated via prompt, None means unsupported."
                  />
                  <Select
                    value={formData.tool_calling}
                    onValueChange={(value) => updateFormField('tool_calling', value)}
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

                <div className="space-y-2">
                  <FormLabel
                    htmlFor="json_schema"
                    label="JSON Schema"
                    tooltip="Structured JSON output reliability. Strong means native schema constraints, Weak means prompt guidance, None means unreliable."
                  />
                  <Select
                    value={formData.json_schema}
                    onValueChange={(value) => updateFormField('json_schema', value)}
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
              </div>

              <div className="space-y-2">
                <FormLabel
                  htmlFor="thinking"
                  label="Thinking"
                  tooltip="Controls protocol-level thinking or reasoning flags. Auto sends nothing explicit, while Enabled and Disabled force a provider-specific mode."
                />
                <Select
                  value={formData.thinking}
                  onValueChange={(value) => updateFormField('thinking', value)}
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

              <div className="space-y-3">
                <CapabilityToggle
                  id="chat"
                  label="Multi-turn Chat"
                  checked={formData.chat}
                  tooltip="Whether the model supports multi-turn conversation with role-aware message arrays."
                  disabled={isSubmitting}
                  onCheckedChange={(checked) => updateFormField('chat', checked)}
                />
                <CapabilityToggle
                  id="system_role"
                  label="System Role"
                  checked={formData.system_role}
                  tooltip="Whether the model honors a distinct system role instead of flattening all instructions into user content."
                  disabled={isSubmitting}
                  onCheckedChange={(checked) => updateFormField('system_role', checked)}
                />
              </div>
            </TabsContent>
          </Tabs>
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
            disabled={
              isSubmitting ||
              !formData.name.trim() ||
              !formData.endpoint.trim() ||
              !formData.model.trim() ||
              !formData.api_key.trim()
            }
          >
            {isSubmitting ? 'Saving…' : mode === 'create' ? 'Create' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default LLMModal;
