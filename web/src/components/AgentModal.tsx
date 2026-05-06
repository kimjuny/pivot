import { useCallback, useEffect, useState } from 'react';
import { Bot, Plus } from "@/lib/lucide";
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/auth-core';
import {
  getAgentAccess,
  getAgentAccessOptions,
  getAgentCreateAccessOptions,
  getUsableLLMs,
} from '../utils/api';
import type {
  AgentAccess,
  AgentAccessGroupOption,
  AgentAccessUserOption,
} from '../utils/api';
import type { LLMUsable } from '../types';
import { LLMBrandAvatar } from './LLMBrandAvatar';
import ResourceAuthTab from '@/components/ResourceAuthTab';
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
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { TooltipProvider } from '@/components/ui/tooltip';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

/**
 * Editable agent payload shared by the create and edit dialogs.
 */
export interface AgentFormData {
  name: string;
  description: string | undefined;
  llm_id: number | undefined;
  /** Minutes of inactivity before chat starts a fresh session. */
  session_idle_timeout_minutes: number;
  /** Seconds to wait for sandbox-manager before surfacing a timeout. */
  sandbox_timeout_seconds: number;
  /** Context percentage that triggers automatic compaction. */
  compact_threshold_percent: number;
  /** Maximum ReAct iterations allowed for one task. */
  max_iteration: number;
  /** End-user access rules for Web, Desktop, and Channel clients. */
  access: AgentAccess;
}

interface AgentModalProps {
  isOpen: boolean;
  mode: 'create' | 'edit';
  agentId?: number;
  creatorUserId?: number | null;
  initialData?: Partial<AgentFormData>;
  onClose: () => void;
  onSave: (data: AgentFormData) => Promise<void>;
}

type AgentTabValue = 'general' | 'advanced' | 'auth';

const EMPTY_AGENT_ACCESS: AgentAccess = {
  agent_id: 0,
  use_scope: 'selected',
  use_user_ids: [],
  use_group_ids: [],
  edit_user_ids: [],
  edit_group_ids: [],
};

function createDefaultFormData(): AgentFormData {
  return {
    name: '',
    description: '',
    llm_id: undefined,
    session_idle_timeout_minutes: 15,
    sandbox_timeout_seconds: 60,
    compact_threshold_percent: 60,
    max_iteration: 50,
    access: { ...EMPTY_AGENT_ACCESS },
  };
}

/**
 * Modal for creating or editing an agent.
 * Uses shadcn Dialog with form inputs for agent properties.
 */
function AgentModal({
  isOpen,
  mode,
  agentId,
  creatorUserId,
  initialData,
  onClose,
  onSave,
}: AgentModalProps) {
  const navigate = useNavigate();
  const { user: currentUser } = useAuth();
  const [formData, setFormData] = useState<AgentFormData>(createDefaultFormData());
  const [activeTab, setActiveTab] = useState<AgentTabValue>('general');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [availableLLMs, setAvailableLLMs] = useState<LLMUsable[]>([]);
  const [loadingLLMs, setLoadingLLMs] = useState<boolean>(false);
  const [accessUsers, setAccessUsers] = useState<AgentAccessUserOption[]>([]);
  const [accessGroups, setAccessGroups] = useState<AgentAccessGroupOption[]>([]);
  const [loadingAccess, setLoadingAccess] = useState<boolean>(false);
  const activeTabIndex = activeTab === 'general' ? 0 : activeTab === 'advanced' ? 1 : 2;
  const effectiveCreatorUserId =
    creatorUserId !== null && creatorUserId !== undefined
      ? creatorUserId
      : currentUser?.id;

  const loadLLMs = useCallback(async () => {
    setLoadingLLMs(true);
    try {
      const llms = await getUsableLLMs();
      setAvailableLLMs(llms);
    } catch (err) {
      const error = err as Error;
      console.error('Failed to load LLMs:', error);
    } finally {
      setLoadingLLMs(false);
    }
  }, []);

  const loadAccess = useCallback(async () => {
    setLoadingAccess(true);
    try {
      if (mode === 'edit' && agentId) {
        const [access, options] = await Promise.all([
          getAgentAccess(agentId),
          getAgentAccessOptions(agentId),
        ]);
        setFormData((current) => ({ ...current, access }));
        setAccessUsers(options.users);
        setAccessGroups(options.groups);
        return;
      }

      const options = await getAgentCreateAccessOptions();
      setAccessUsers(options.users);
      setAccessGroups(options.groups);
      setFormData((current) => ({
        ...current,
        access: {
          ...EMPTY_AGENT_ACCESS,
          edit_user_ids:
            effectiveCreatorUserId !== null && effectiveCreatorUserId !== undefined
              ? [effectiveCreatorUserId]
              : [],
        },
      }));
    } catch (err) {
      const error = err as Error;
      console.error('Failed to load agent access:', error);
    } finally {
      setLoadingAccess(false);
    }
  }, [agentId, effectiveCreatorUserId, mode]);

  useEffect(() => {
    if (isOpen) {
      if (mode === 'edit' && initialData) {
        setFormData({
          name: initialData.name || '',
          description: initialData.description || '',
          llm_id: initialData.llm_id,
          session_idle_timeout_minutes:
            initialData.session_idle_timeout_minutes ?? 15,
          sandbox_timeout_seconds: initialData.sandbox_timeout_seconds ?? 60,
          compact_threshold_percent:
            initialData.compact_threshold_percent ?? 60,
          max_iteration: initialData.max_iteration ?? 50,
          access: initialData.access ?? { ...EMPTY_AGENT_ACCESS },
        });
      } else {
        setFormData(createDefaultFormData());
      }
      setActiveTab('general');
      setServerError(null);
      void loadLLMs();
      void loadAccess();
    }
  }, [isOpen, mode, initialData, loadLLMs, loadAccess]);

  const handleSubmit = async () => {
    if (!formData.name.trim()) {
      setActiveTab('general');
      setServerError('Agent name is required');
      return;
    }
    if (!formData.llm_id) {
      setActiveTab('general');
      setServerError('LLM selection is required');
      return;
    }
    if (
      !Number.isInteger(formData.session_idle_timeout_minutes) ||
      formData.session_idle_timeout_minutes < 1
    ) {
      setActiveTab('advanced');
      setServerError('Session idle timeout must be at least 1 minute');
      return;
    }
    if (
      !Number.isInteger(formData.sandbox_timeout_seconds) ||
      formData.sandbox_timeout_seconds < 1
    ) {
      setActiveTab('advanced');
      setServerError('Sandbox timeout must be at least 1 second');
      return;
    }
    if (
      !Number.isInteger(formData.compact_threshold_percent) ||
      formData.compact_threshold_percent < 1 ||
      formData.compact_threshold_percent > 100
    ) {
      setActiveTab('advanced');
      setServerError('Compact threshold must be between 1% and 100%');
      return;
    }
    if (
      !Number.isInteger(formData.max_iteration) ||
      formData.max_iteration < 1
    ) {
      setActiveTab('advanced');
      setServerError('Max iteration must be at least 1');
      return;
    }

    setIsSubmitting(true);
    setServerError(null);

    try {
      await onSave({
        name: formData.name.trim(),
        description: formData.description?.trim() || undefined,
        llm_id: formData.llm_id,
        session_idle_timeout_minutes: formData.session_idle_timeout_minutes,
        sandbox_timeout_seconds: formData.sandbox_timeout_seconds,
        compact_threshold_percent: formData.compact_threshold_percent,
        max_iteration: formData.max_iteration,
        access: {
          ...formData.access,
          use_user_ids:
            formData.access.use_scope === 'all' ? [] : formData.access.use_user_ids,
          use_group_ids:
            formData.access.use_scope === 'all' ? [] : formData.access.use_group_ids,
          edit_user_ids: [],
          edit_group_ids: [],
        },
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
      <DialogContent className="flex max-h-[90vh] min-h-0 flex-col overflow-hidden sm:max-w-[720px]">
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

        <TooltipProvider>
          <Tabs
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as AgentTabValue)}
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
                Primary <span className="text-destructive">*</span>
              </Label>
              {loadingLLMs ? (
                <div className="flex h-9 w-full items-center rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm text-muted-foreground">
                  Loading LLMs…
                </div>
              ) : (
                <Select
                  value={formData.llm_id?.toString() || '__none__'}
                  onValueChange={(value) => {
                    if (value === '__add_new__') {
                      // Why: creating the dependency in-place avoids forcing users to abandon the flow.
                      navigate('/studio/assets/models');
                      onClose();
                    } else {
                      setFormData({
                        ...formData,
                        llm_id: value === '__none__' ? undefined : Number.parseInt(value, 10),
                      });
                    }
                  }}
                  disabled={isSubmitting}
                >
                  <SelectTrigger id="llm">
                    <SelectValue placeholder="None" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__none__">None</SelectItem>
                    {availableLLMs.length === 0 ? (
                      <div className="px-2 py-6 text-center text-sm text-muted-foreground">
                        No LLMs available
                      </div>
                    ) : (
                      availableLLMs.map((llm) => (
                        <SelectItem key={llm.id} value={llm.id.toString()}>
                          <div className="flex min-w-0 items-center gap-2">
                            <LLMBrandAvatar
                              model={llm.model}
                              containerClassName="flex size-5 shrink-0 items-center justify-center rounded-md bg-primary/10"
                              imageClassName="size-3.5"
                              fallback={<Bot className="size-3.5 text-primary" aria-hidden="true" />}
                            />
                            <span className="shrink-0 font-medium">{llm.name}</span>
                            <span className="min-w-0 truncate text-xs text-muted-foreground">({llm.model})</span>
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
                        <Plus className="h-3.5 w-3.5" />
                        <span>Add New LLM</span>
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              )}
            </div>

            </div>
          </TabsContent>

          <TabsContent
            value="advanced"
            className="mt-0 h-[560px] max-h-[calc(90vh-150px)] overflow-y-auto pr-2"
          >
            <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="session_idle_timeout_minutes">
                Session Idle Timeout
              </Label>
              <Input
                id="session_idle_timeout_minutes"
                type="number"
                min={1}
                step={1}
                value={formData.session_idle_timeout_minutes}
                onChange={(e) => {
                  const nextValue = Number.parseInt(e.target.value, 10);
                  setFormData({
                    ...formData,
                    session_idle_timeout_minutes: Number.isNaN(nextValue)
                      ? 0
                      : nextValue,
                  });
                }}
                disabled={isSubmitting}
                placeholder="15"
                autoComplete="off"
              />
              <p className="text-sm text-muted-foreground">
                Start a new chat session after this many idle minutes. Default is
                15.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="sandbox_timeout_seconds">
                Sandbox Timeout (seconds)
              </Label>
              <Input
                id="sandbox_timeout_seconds"
                type="number"
                min={1}
                step={1}
                value={formData.sandbox_timeout_seconds}
                onChange={(e) => {
                  const nextValue = Number.parseInt(e.target.value, 10);
                  setFormData({
                    ...formData,
                    sandbox_timeout_seconds: Number.isNaN(nextValue)
                      ? 0
                      : nextValue,
                  });
                }}
                disabled={isSubmitting}
                placeholder="60"
                autoComplete="off"
              />
              <p className="text-sm text-muted-foreground">
                Wait this many seconds for sandbox-backed function calls before
                surfacing a timeout error. Default is 60.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="max_iteration">
                Max Iteration
              </Label>
              <Input
                id="max_iteration"
                type="number"
                min={1}
                step={1}
                value={formData.max_iteration}
                onChange={(e) => {
                  const nextValue = Number.parseInt(e.target.value, 10);
                  setFormData({
                    ...formData,
                    max_iteration: Number.isNaN(nextValue)
                      ? 0
                      : nextValue,
                  });
                }}
                disabled={isSubmitting}
                placeholder="50"
                autoComplete="off"
              />
              <p className="text-sm text-muted-foreground">
                Limit how many ReAct iterations one task can use before the agent
                is forced to stop. Default is 50.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="compact_threshold_percent">
                Compact Threshold (%)
              </Label>
              <Input
                id="compact_threshold_percent"
                type="number"
                min={1}
                max={100}
                step={1}
                value={formData.compact_threshold_percent}
                onChange={(e) => {
                  const nextValue = Number.parseInt(e.target.value, 10);
                  setFormData({
                    ...formData,
                    compact_threshold_percent: Number.isNaN(nextValue)
                      ? 0
                      : nextValue,
                  });
                }}
                disabled={isSubmitting}
                placeholder="60"
                autoComplete="off"
              />
              <p className="text-sm text-muted-foreground">
                Automatically compact the runtime context when usage reaches this percentage.
              </p>
            </div>
            </div>
          </TabsContent>
          <TabsContent
            value="auth"
            className="mt-0 h-[560px] max-h-[calc(90vh-150px)] overflow-y-auto pr-2"
          >
            <ResourceAuthTab
              access={formData.access}
              users={accessUsers}
              groups={accessGroups}
              loading={loadingAccess}
              editDisabled
              editTooltip="Agent Edit is limited to the creator and admins in this version. Client Use does not require Studio Use on the Agent's configured LLM, Skills, Tools, Extensions, or Providers."
              editDisabledMessage="Only the creator can edit this Agent. Admins can manage it through system-level permissions."
              lockedEditUserIds={
                effectiveCreatorUserId !== null && effectiveCreatorUserId !== undefined
                  ? [effectiveCreatorUserId]
                  : []
              }
              useTitle="Who can use this Agent"
              useEveryoneDescription="All active client users can see and run this Agent from Web, Desktop, and Channel clients."
              useSelectedDescription="Only selected users and groups can see and run this Agent from client surfaces."
              useEveryoneMessage="Everyone can see and run this Agent from client surfaces. Studio-only resource permissions on its LLM, Skills, Tools, Extensions, and Providers are not checked again at runtime."
              onAccessChange={(nextAccess) =>
                setFormData((current) => ({
                  ...current,
                  access: {
                    ...current.access,
                    ...nextAccess,
                    edit_user_ids: current.access.edit_user_ids,
                    edit_group_ids: [],
                  },
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
