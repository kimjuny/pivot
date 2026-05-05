import { useEffect, useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { Info, Plus, Trash2 } from "@/lib/lucide";
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
import {
  getLLMAccess,
  getLLMAccessOptions,
  getLLMCreateAccessOptions,
  type LLMAccess,
} from '@/utils/api';
import ResourceAuthTab from '@/components/ResourceAuthTab';
import {
  THINKING_PROVIDER_OPTIONS,
  buildThinkingPolicyFromEditorState,
  getDefaultThinkingEditorState,
  getThinkingEditorStateFromPolicy,
  providerNeedsThinkingDetail,
  type ThinkingProvider,
} from '@/utils/llmThinking';

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
  thinking_policy: string;
  thinking_effort: string;
  thinking_budget_tokens: number | null;
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
  llmId?: number | null;
  creatorUserId?: number | null;
  initialData?: Partial<LLMFormData>;
  onClose: () => void;
  onSave: (data: LLMFormData, access: LLMAccess) => Promise<void>;
}

interface ExtraConfigEntry {
  id: string;
  key: string;
  value: string;
}

type LLMTabValue = 'general' | 'advanced' | 'auth';

const EMPTY_LLM_ACCESS: LLMAccess = {
  llm_id: 0,
  use_scope: 'all',
  use_user_ids: [],
  use_group_ids: [],
  edit_user_ids: [],
  edit_group_ids: [],
};

interface FormLabelProps {
  htmlFor?: string;
  label: string;
  tooltip: ReactNode;
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

function getThinkingTooltipContent(
  protocol: string,
  provider: ThinkingProvider,
  detailValue: string,
): ReactNode {
  let payloadHint = 'Current payload: no thinking override. Pivot sends nothing for this LLM.';

  if (protocol === 'openai_completion_llm') {
    if (provider === 'qwen') {
      payloadHint = 'Current payload: {"enable_thinking": true | false}';
    } else if (provider === 'completion_toggle') {
      payloadHint =
        'Current payload: {"thinking": {"type": "enabled" | "disabled"}}';
    }
  } else if (protocol === 'openai_response_llm') {
    if (provider === 'doubao') {
      payloadHint =
        'Current payload: {"thinking": {"type": "enabled" | "disabled"}}';
    } else if (provider === 'chatgpt') {
      payloadHint =
        'Current payload: {"reasoning": {"effort": "none" | "low" | "medium" | "high" | "xhigh"}}';
    }
  } else if (protocol === 'anthropic_compatible') {
    if (provider === 'mimo') {
      payloadHint =
        'Current payload: {"thinking": {"type": "enabled" | "disabled"}}';
    } else if (provider === 'claude') {
      payloadHint =
        detailValue === 'adaptive'
          ? 'Current payload: {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low" | "medium" | "high" | "max"}}'
          : 'Current payload: {"thinking": {"type": "enabled", "budget_tokens": number}}';
    }
  }

  return (
    <div className="space-y-2">
      <p>Choose a provider-specific thinking configuration. Auto means Pivot sends no thinking override for this LLM.</p>
      <code className="block whitespace-pre-wrap break-all rounded bg-muted px-2 py-1 text-[11px]">
        {payloadHint}
      </code>
    </div>
  );
}

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
          {typeof tooltip === 'string' ? <p>{tooltip}</p> : tooltip}
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
function LLMModal({
  isOpen,
  mode,
  llmId,
  creatorUserId,
  initialData,
  onClose,
  onSave,
}: LLMModalProps) {
  const [formData, setFormData] = useState<LLMFormData>({
    name: '',
    endpoint: '',
    model: '',
    api_key: '',
    protocol: 'openai_completion_llm',
    cache_policy: 'none',
    thinking_policy: 'auto',
    thinking_effort: '',
    thinking_budget_tokens: null,
    streaming: true,
    image_input: false,
    image_output: false,
    max_context: 128000,
    extra_config: '',
  });
  const [activeTab, setActiveTab] = useState<LLMTabValue>('general');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [access, setAccess] = useState<LLMAccess>(EMPTY_LLM_ACCESS);
  const [accessUsers, setAccessUsers] = useState<
    Awaited<ReturnType<typeof getLLMAccessOptions>>['users']
  >([]);
  const [accessGroups, setAccessGroups] = useState<
    Awaited<ReturnType<typeof getLLMAccessOptions>>['groups']
  >([]);
  const [isAccessLoading, setIsAccessLoading] = useState(false);
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
        thinking_policy: initialData.thinking_policy ?? 'auto',
        thinking_effort: initialData.thinking_effort ?? '',
        thinking_budget_tokens: initialData.thinking_budget_tokens ?? null,
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
        thinking_policy: 'auto',
        thinking_effort: '',
        thinking_budget_tokens: null,
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
    if (!isOpen) {
      setAccess(EMPTY_LLM_ACCESS);
      setAccessUsers([]);
      setAccessGroups([]);
      return;
    }

    let isCancelled = false;
    setIsAccessLoading(true);
    const accessRequest =
      mode === 'edit' && llmId
        ? Promise.all([getLLMAccess(llmId), getLLMAccessOptions(llmId)])
        : Promise.all([
            Promise.resolve(EMPTY_LLM_ACCESS),
            getLLMCreateAccessOptions(),
          ]);

    void accessRequest
      .then(([nextAccess, options]) => {
        if (isCancelled) {
          return;
        }
        setAccess(nextAccess);
        setAccessUsers(options.users);
        setAccessGroups(options.groups);
      })
      .catch((err) => {
        toast.error(err instanceof Error ? err.message : 'Failed to load auth');
      })
      .finally(() => {
        if (!isCancelled) {
          setIsAccessLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [isOpen, llmId, mode]);

  useEffect(() => {
    const options = CACHE_POLICY_OPTIONS[formData.protocol] ?? [{ value: 'none', label: 'None' }];
    const isCurrentValid = options.some((option) => option.value === formData.cache_policy);
    if (!isCurrentValid) {
      setFormData((prev) => ({ ...prev, cache_policy: 'none' }));
    }
  }, [formData.protocol, formData.cache_policy]);

  useEffect(() => {
    const currentState = getThinkingEditorStateFromPolicy(
      formData.protocol,
      formData.thinking_policy,
      formData.thinking_effort,
      formData.thinking_budget_tokens,
    );
    const options = THINKING_PROVIDER_OPTIONS[formData.protocol] ?? [
      { value: 'auto', label: 'Auto' },
    ];
    const isCurrentValid = options.some(
      (option) => option.value === currentState.provider,
    );
    if (isCurrentValid) {
      return;
    }

    const defaultState = getDefaultThinkingEditorState(formData.protocol, 'auto');
    const normalizedThinking = buildThinkingPolicyFromEditorState(
      formData.protocol,
      defaultState.provider,
      defaultState.detailValue,
      defaultState.effortValue,
      defaultState.budgetTokens,
    );
    setFormData((prev) => ({
      ...prev,
      ...normalizedThinking,
    }));
  }, [
    formData.protocol,
    formData.thinking_policy,
    formData.thinking_effort,
    formData.thinking_budget_tokens,
  ]);

  const updateFormField = <K extends keyof LLMFormData>(
    field: K,
    value: LLMFormData[K],
  ) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  const applyThinkingEditorState = (
    provider: ThinkingProvider,
    detailValue: string,
    effortValue: string,
    budgetTokens: number | null,
  ) => {
    const normalizedThinking = buildThinkingPolicyFromEditorState(
      formData.protocol,
      provider,
      detailValue,
      effortValue,
      budgetTokens,
    );
    setFormData((prev) => ({
      ...prev,
      ...normalizedThinking,
    }));
  };

  const handleThinkingProviderChange = (provider: ThinkingProvider) => {
    const defaultState = getDefaultThinkingEditorState(formData.protocol, provider);
    applyThinkingEditorState(
      defaultState.provider,
      defaultState.detailValue,
      defaultState.effortValue,
      defaultState.budgetTokens,
    );
  };

  const currentThinkingState = getThinkingEditorStateFromPolicy(
    formData.protocol,
    formData.thinking_policy,
    formData.thinking_effort,
    formData.thinking_budget_tokens,
  );
  const activeTabIndex = activeTab === 'general' ? 0 : activeTab === 'advanced' ? 1 : 2;

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
      await onSave(
        {
          ...formData,
          extra_config: normalized,
        },
        access,
      );
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
      <DialogContent className="flex max-h-[90vh] min-h-0 flex-col overflow-hidden sm:max-w-[860px]">
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
            orientation="vertical"
            className="flex min-h-0 flex-1 gap-3 py-2"
          >
            <TabsList className="relative flex h-[560px] max-h-[calc(90vh-150px)] w-24 shrink-0 flex-col items-stretch justify-start gap-1 bg-transparent p-0">
              <span
                className="absolute left-0 top-1.5 h-6 w-0.5 bg-foreground transition-transform duration-200 ease-out"
                style={{
                  transform: `translateY(${activeTabIndex * 40}px)`,
                }}
                aria-hidden="true"
              />
              <TabsTrigger
                value="general"
                className="h-9 justify-start rounded-none bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              >
                General
              </TabsTrigger>
              <TabsTrigger
                value="advanced"
                className="h-9 justify-start rounded-none bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              >
                Advanced
              </TabsTrigger>
              <TabsTrigger
                value="auth"
                className="h-9 justify-start rounded-none bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
              >
                Auth
              </TabsTrigger>
            </TabsList>

            <div className="min-w-0 flex-1">
            <TabsContent
              value="general"
              className="mt-0 h-[560px] max-h-[calc(90vh-150px)] overflow-y-auto pr-2"
            >
              <div className="space-y-4">
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
              </div>
            </TabsContent>

            <TabsContent
              value="advanced"
              className="mt-0 h-[560px] max-h-[calc(90vh-150px)] overflow-y-auto pr-2"
            >
              <div className="space-y-4">
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

              <div className="space-y-4 rounded-lg border border-border/60 p-4">
                <div className="space-y-2">
                  <FormLabel
                    htmlFor="thinking_provider"
                    label="Thinking"
                    tooltip={getThinkingTooltipContent(
                      formData.protocol,
                      currentThinkingState.provider,
                      currentThinkingState.detailValue,
                    )}
                  />
                  <Select
                    value={currentThinkingState.provider}
                    onValueChange={(value) =>
                      handleThinkingProviderChange(value as ThinkingProvider)
                    }
                    disabled={isSubmitting}
                  >
                    <SelectTrigger id="thinking_provider">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(THINKING_PROVIDER_OPTIONS[formData.protocol] ?? []).map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {providerNeedsThinkingDetail(currentThinkingState.provider) && (
                  <>
                    {currentThinkingState.provider === 'qwen' && (
                      <div className="space-y-2">
                        <FormLabel
                          htmlFor="thinking_qwen_enabled"
                          label="Enable Thinking"
                          tooltip="Qwen controls thinking through a boolean enable_thinking field."
                        />
                        <Select
                          value={currentThinkingState.detailValue}
                          onValueChange={(value) =>
                            applyThinkingEditorState(
                              currentThinkingState.provider,
                              value,
                              currentThinkingState.effortValue,
                              currentThinkingState.budgetTokens,
                            )
                          }
                          disabled={isSubmitting}
                        >
                          <SelectTrigger id="thinking_qwen_enabled">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="true">true</SelectItem>
                            <SelectItem value="false">false</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    )}

                    {['completion_toggle', 'doubao', 'mimo'].includes(
                      currentThinkingState.provider,
                    ) && (
                      <div className="space-y-2">
                        <FormLabel
                          htmlFor="thinking_type"
                          label="Thinking Type"
                          tooltip="Most provider-compatible thinking APIs use enabled or disabled as the protocol value, including Doubao, GLM, MiMo, Kimi, and DeepSeek on Completion."
                        />
                        <Select
                          value={currentThinkingState.detailValue}
                          onValueChange={(value) =>
                            applyThinkingEditorState(
                              currentThinkingState.provider,
                              value,
                              currentThinkingState.effortValue,
                              currentThinkingState.budgetTokens,
                            )
                          }
                          disabled={isSubmitting}
                        >
                          <SelectTrigger id="thinking_type">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="enabled">enabled</SelectItem>
                            <SelectItem value="disabled">disabled</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    )}

                    {currentThinkingState.provider === 'chatgpt' && (
                      <div className="space-y-2">
                        <FormLabel
                          htmlFor="thinking_effort"
                          label="Reasoning Effort"
                          tooltip="ChatGPT Responses reasoning is controlled through the reasoning.effort field."
                        />
                        <Select
                          value={currentThinkingState.effortValue}
                          onValueChange={(value) =>
                            applyThinkingEditorState(
                              currentThinkingState.provider,
                              currentThinkingState.detailValue,
                              value,
                              currentThinkingState.budgetTokens,
                            )
                          }
                          disabled={isSubmitting}
                        >
                          <SelectTrigger id="thinking_effort">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">none</SelectItem>
                            <SelectItem value="low">low</SelectItem>
                            <SelectItem value="medium">medium</SelectItem>
                            <SelectItem value="high">high</SelectItem>
                            <SelectItem value="xhigh">xhigh</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    )}

                    {currentThinkingState.provider === 'claude' && (
                      <>
                        <div className="space-y-2">
                          <FormLabel
                            htmlFor="thinking_claude_mode"
                            label="Thinking Mode"
                            tooltip="Claude supports extended thinking with budget tokens, or adaptive thinking with an effort level."
                          />
                          <Select
                            value={currentThinkingState.detailValue}
                            onValueChange={(value) =>
                              applyThinkingEditorState(
                                currentThinkingState.provider,
                                value,
                                value === 'adaptive'
                                  ? currentThinkingState.effortValue || 'high'
                                  : '',
                                value === 'enabled'
                                  ? currentThinkingState.budgetTokens ?? 10000
                                  : null,
                              )
                            }
                            disabled={isSubmitting}
                          >
                            <SelectTrigger id="thinking_claude_mode">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="enabled">enabled</SelectItem>
                              <SelectItem value="adaptive">adaptive</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>

                        {currentThinkingState.detailValue === 'enabled' && (
                          <div className="space-y-2">
                            <FormLabel
                              htmlFor="thinking_budget_tokens"
                              label="Budget Tokens"
                              tooltip="Claude extended thinking requires an explicit budget_tokens value."
                            />
                            <Input
                              id="thinking_budget_tokens"
                              type="number"
                              value={currentThinkingState.budgetTokens ?? ''}
                              onChange={(e) =>
                                applyThinkingEditorState(
                                  currentThinkingState.provider,
                                  currentThinkingState.detailValue,
                                  currentThinkingState.effortValue,
                                  Number.parseInt(e.target.value, 10) || 10000,
                                )
                              }
                              disabled={isSubmitting}
                              placeholder="10000"
                              autoComplete="off"
                            />
                          </div>
                        )}

                        {currentThinkingState.detailValue === 'adaptive' && (
                          <div className="space-y-2">
                            <FormLabel
                              htmlFor="thinking_adaptive_effort"
                              label="Effort"
                              tooltip="Claude adaptive thinking uses output_config.effort."
                            />
                            <Select
                              value={currentThinkingState.effortValue}
                              onValueChange={(value) =>
                                applyThinkingEditorState(
                                  currentThinkingState.provider,
                                  currentThinkingState.detailValue,
                                  value,
                                  null,
                                )
                              }
                              disabled={isSubmitting}
                            >
                              <SelectTrigger id="thinking_adaptive_effort">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="max">max</SelectItem>
                                <SelectItem value="high">high</SelectItem>
                                <SelectItem value="medium">medium</SelectItem>
                                <SelectItem value="low">low</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        )}
                      </>
                    )}
                  </>
                )}
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
              </div>
            </TabsContent>

            <TabsContent
              value="auth"
              className="mt-0 h-[560px] max-h-[calc(90vh-150px)] overflow-y-auto pr-2"
            >
              <ResourceAuthTab
                access={access}
                users={accessUsers}
                groups={accessGroups}
                loading={isAccessLoading}
                lockedEditUserIds={
                  mode === 'edit' &&
                  creatorUserId !== null &&
                  creatorUserId !== undefined
                    ? [creatorUserId]
                    : []
                }
                onAccessChange={(nextAccess) =>
                  setAccess((current) => ({
                    ...current,
                    ...nextAccess,
                  }))
                }
              />
            </TabsContent>
            </div>

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
              isAccessLoading ||
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
