import { useEffect, useState } from "react";
import { Bot, Info, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { LLMBrandAvatar } from "@/components/LLMBrandAvatar";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type ClientAutomation,
  type ClientAutomationCreatePayload,
  createClientAutomation,
  updateClientAutomation,
} from "@/client/api";
import type { Agent } from "@/types";

export interface AutomationProposal {
  name: string;
  promptTemplate: string;
  cron: string;
  timezone?: string;
  sessionStrategy?: "reuse" | "isolate" | "this_session";
}

interface AutomationDialogProps {
  open: boolean;
  agents: Agent[];
  defaultAgentId?: number;
  /** Agent-proposed automation that pre-fills the form. */
  proposal?: AutomationProposal;
  /** Existing automation to edit. When provided, dialog runs in edit mode. */
  automation?: ClientAutomation;
  onClose: () => void;
  /** Called after a new automation is created. */
  onCreated?: () => void;
  /** Called after an existing automation is updated. */
  onUpdated?: () => void;
}

interface FormData {
  name: string;
  agentId: string;
  promptTemplate: string;
  frequency: string;
  customCron: string;
  timeHour: string;
  timeMinute: string;
  timezone: string;
  sessionStrategy: "reuse" | "isolate" | "this_session";
}

function buildDefaultFormData(): FormData {
  return {
    name: "",
    agentId: "",
    promptTemplate: "",
    frequency: "daily",
    customCron: "",
    timeHour: "9",
    timeMinute: "0",
    timezone: "UTC",
    sessionStrategy: "reuse",
  };
}

function buildCronExpression(data: FormData): string {
  if (data.frequency === "custom") return data.customCron;

  const hour = data.timeHour;
  const minute = data.timeMinute;

  switch (data.frequency) {
    case "hourly":
      return `${minute} * * * *`;
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekdays":
      return `${minute} ${hour} * * 1-5`;
    case "weekly":
      return `${minute} ${hour} * * 1`;
    case "monthly":
      return `${minute} ${hour} 1 * *`;
    default:
      return `${minute} ${hour} * * *`;
  }
}

/** Try to reverse a cron expression back into frequency + time fields. */
function parseCronForForm(cron: string): Pick<FormData, "frequency" | "customCron" | "timeHour" | "timeMinute"> {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) {
    return { frequency: "custom", customCron: cron, timeHour: "9", timeMinute: "0" };
  }

  const [minute, hour, dayOfMonth, , dayOfWeek] = parts;

  const hasIntervalMinute = /^\*\/\d+$/.test(minute);
  const hasIntervalHour = /^\*\/\d+$/.test(hour);

  if (dayOfWeek === "1-5" && dayOfMonth === "*" && !hasIntervalMinute && !hasIntervalHour) {
    return { frequency: "weekdays", customCron: "", timeHour: hour, timeMinute: minute };
  }
  if (dayOfWeek === "1" && dayOfMonth === "*" && !hasIntervalMinute && !hasIntervalHour) {
    return { frequency: "weekly", customCron: "", timeHour: hour, timeMinute: minute };
  }
  if (dayOfMonth === "1" && dayOfWeek === "*" && !hasIntervalMinute && !hasIntervalHour) {
    return { frequency: "monthly", customCron: "", timeHour: hour, timeMinute: minute };
  }
  if (hour === "*" && !hasIntervalMinute) {
    return { frequency: "hourly", customCron: "", timeHour: "9", timeMinute: minute };
  }
  if (dayOfMonth === "*" && dayOfWeek === "*" && !hasIntervalMinute && !hasIntervalHour) {
    return { frequency: "daily", customCron: "", timeHour: hour, timeMinute: minute };
  }
  return { frequency: "custom", customCron: cron, timeHour: "9", timeMinute: "0" };
}

/**
 * Validate a standard 5-field cron expression.
 * Returns an error message or null if valid.
 */
function validateCron(cron: string): string | null {
  const trimmed = cron.trim();
  if (!trimmed) return "Cron expression is required";

  const parts = trimmed.split(/\s+/);
  if (parts.length !== 5) return "Must have exactly 5 fields: minute hour day month weekday";

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

  const fieldRules: [string, string, number, number][] = [
    ["Minute", minute, 0, 59],
    ["Hour", hour, 0, 23],
    ["Day of month", dayOfMonth, 1, 31],
    ["Month", month, 1, 12],
    ["Day of week", dayOfWeek, 0, 7],
  ];

  for (const [label, field, min, max] of fieldRules) {
    if (!isValidCronField(field, min, max)) {
      return `${label} is invalid (range ${min}–${max})`;
    }
  }

  return null;
}

// Supports: *, */n, n, n-m, n,m, and combinations.
function isValidCronField(field: string, min: number, max: number): boolean {
  if (field === "*") return true;
  if (/^\*\/\d+$/.test(field)) {
    const step = parseInt(field.slice(2), 10);
    return step >= 1 && step <= max;
  }
  const atoms = field.split(",");
  return atoms.every((atom) => {
    if (/^\d+$/.test(atom)) {
      const v = parseInt(atom, 10);
      return v >= min && v <= max;
    }
    const rangeMatch = /^(\d+)-(\d+)$/.exec(atom);
    if (rangeMatch) {
      const lo = parseInt(rangeMatch[1], 10);
      const hi = parseInt(rangeMatch[2], 10);
      return lo >= min && hi <= max && lo <= hi;
    }
    if (/^\d+-\d+\/\d+$/.test(atom)) {
      const [range, stepStr] = atom.split("/");
      const [lo, hi] = range.split("-").map(Number);
      const step = parseInt(stepStr, 10);
      return lo >= min && hi <= max && lo <= hi && step >= 1;
    }
    return false;
  });
}

const FREQUENCY_OPTIONS = [
  { value: "hourly", label: "Every hour" },
  { value: "daily", label: "Every day" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekly", label: "Every week" },
  { value: "monthly", label: "Every month" },
  { value: "custom", label: "Custom cron" },
];

/**
 * Dialog for creating or editing an automation.
 * Pass `automation` to open in edit mode.
 */
export function AutomationCreateDialog({
  open,
  agents,
  defaultAgentId,
  proposal,
  automation,
  onClose,
  onCreated,
  onUpdated,
}: AutomationDialogProps) {
  const isEdit = automation !== undefined;

  const [formData, setFormData] = useState<FormData>(() => {
    if (automation) return buildEditFormData(automation);
    const defaults = buildDefaultFormData();
    if (defaultAgentId !== undefined) defaults.agentId = String(defaultAgentId);
    if (proposal) applyProposal(defaults, proposal);
    return defaults;
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // Re-initialize form when the dialog opens.
  useEffect(() => {
    if (!open) return;
    if (automation) {
      setFormData(buildEditFormData(automation));
    } else {
      const defaults = buildDefaultFormData();
      if (defaultAgentId !== undefined) defaults.agentId = String(defaultAgentId);
      if (proposal) applyProposal(defaults, proposal);
      setFormData(defaults);
    }
    setValidationErrors({});
  }, [open, automation, proposal, defaultAgentId]);

  const updateField = <K extends keyof FormData>(key: K, value: FormData[K]) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async () => {
    const errors: Record<string, string> = {};

    if (!formData.name.trim()) errors.name = "Name is required";
    if (!isEdit && !formData.agentId) errors.agentId = "Agent is required";
    if (!formData.promptTemplate.trim()) errors.promptTemplate = "Prompt template is required";

    const cron = buildCronExpression(formData);
    if (formData.frequency === "custom") {
      if (!cron.trim()) {
        errors.schedule = "Schedule configuration is required";
      } else {
        const cronErr = validateCron(cron);
        if (cronErr) errors.schedule = cronErr;
      }
    }

    setValidationErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setIsSubmitting(true);
    try {
      if (isEdit && automation) {
        await updateClientAutomation(automation.automation_id, {
          name: formData.name.trim(),
          prompt_template: formData.promptTemplate.trim(),
          trigger_config: JSON.stringify({ cron, timezone: formData.timezone }),
          session_strategy: formData.sessionStrategy,
        });
        toast.success("Automation updated");
        onUpdated?.();
      } else {
        const payload: ClientAutomationCreatePayload = {
          name: formData.name.trim(),
          agent_id: Number(formData.agentId),
          prompt_template: formData.promptTemplate.trim(),
          trigger_config: JSON.stringify({ cron, timezone: formData.timezone }),
          session_strategy: formData.sessionStrategy,
        };
        await createClientAutomation(payload);
        toast.success("Automation created");
        setFormData(buildDefaultFormData());
        onCreated?.();
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Failed to ${isEdit ? "update" : "create"} automation`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-[640px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Automation" : "New Automation"}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-5 py-2">
          {/* Name */}
          <Field data-invalid={validationErrors.name ? "" : undefined}>
            <FieldLabel htmlFor="auto-name">Name<span className="text-destructive ml-0.5">*</span></FieldLabel>
            <Input
              id="auto-name"
              placeholder="Daily Report"
              aria-invalid={validationErrors.name ? true : undefined}
              value={formData.name}
              onChange={(e) => updateField("name", e.target.value)}
            />
            {validationErrors.name && <FieldError>{validationErrors.name}</FieldError>}
          </Field>

          {/* Agent — only shown when creating */}
          {!isEdit && (
            <Field data-invalid={validationErrors.agentId ? "" : undefined}>
              <FieldLabel>Agent<span className="text-destructive ml-0.5">*</span></FieldLabel>
              <Select
                value={formData.agentId}
                onValueChange={(val) => updateField("agentId", val)}
              >
                <SelectTrigger aria-invalid={validationErrors.agentId ? true : undefined}>
                  <SelectValue placeholder="Select an agent" />
                </SelectTrigger>
                <SelectContent>
                  {agents.map((agent) => (
                    <SelectItem key={agent.id} value={String(agent.id)}>
                      <div className="flex items-center gap-2">
                        <LLMBrandAvatar
                          model={agent.model_name}
                          fallback={<Bot className="size-3.5" aria-hidden="true" />}
                          containerClassName="flex size-5 shrink-0 items-center justify-center rounded-md bg-primary/10"
                          imageClassName="size-3.5"
                        />
                        <span>{agent.name}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {validationErrors.agentId && <FieldError>{validationErrors.agentId}</FieldError>}
            </Field>
          )}

          {/* Schedule */}
          <Field data-invalid={validationErrors.schedule ? "" : undefined}>
            <FieldLabel>Schedule<span className="text-destructive ml-0.5">*</span></FieldLabel>
            {formData.frequency === "custom" ? (
              <>
                <div className="flex items-center gap-2">
                  <Select
                    value={formData.frequency}
                    onValueChange={(val) => updateField("frequency", val)}
                  >
                    <SelectTrigger className="w-[160px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {FREQUENCY_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    placeholder="0 9 * * 1-5"
                    className="flex-1"
                    aria-invalid={validationErrors.schedule ? true : undefined}
                    value={formData.customCron}
                    onChange={(e) => updateField("customCron", e.target.value)}
                  />
                </div>
                {validationErrors.schedule && <FieldError>{validationErrors.schedule}</FieldError>}
              </>
            ) : (
              <div className="flex items-center gap-2">
                <Select
                  value={formData.frequency}
                  onValueChange={(val) => updateField("frequency", val)}
                >
                  <SelectTrigger className="w-[160px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FREQUENCY_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {formData.frequency !== "hourly" ? (
                  <>
                    <span className="text-sm text-muted-foreground">at</span>
                    <Input
                      type="number"
                      min="0"
                      max="23"
                      className="w-16"
                      value={formData.timeHour}
                      onChange={(e) => updateField("timeHour", e.target.value)}
                    />
                    <span className="text-sm text-muted-foreground">:</span>
                    <Input
                      type="number"
                      min="0"
                      max="59"
                      className="w-16"
                      value={formData.timeMinute}
                      onChange={(e) => updateField("timeMinute", e.target.value)}
                    />
                  </>
                ) : (
                  <span className="text-sm text-muted-foreground">
                    at :{formData.timeMinute || "0"}
                  </span>
                )}
              </div>
            )}
          </Field>

          {/* Prompt Template */}
          <Field data-invalid={validationErrors.promptTemplate ? "" : undefined}>
            <FieldLabel htmlFor="auto-prompt" className="flex items-center gap-1">
              Prompt Template<span className="text-destructive ml-0.5">*</span>
              <TooltipProvider delayDuration={200}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info className="h-3 w-3 cursor-help text-muted-foreground/60" />
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-72 text-xs leading-relaxed">
                    <p className="font-medium mb-1.5">Available template variables:</p>
                    <ul className="space-y-1">
                      <li><code className="rounded bg-foreground/10 px-1 py-0.5 font-mono">{`{{date}}`}</code> — Current date</li>
                      <li><code className="rounded bg-foreground/10 px-1 py-0.5 font-mono">{`{{time}}`}</code> — Current time</li>
                      <li><code className="rounded bg-foreground/10 px-1 py-0.5 font-mono">{`{{datetime}}`}</code> — Current date and time</li>
                      <li><code className="rounded bg-foreground/10 px-1 py-0.5 font-mono">{`{{weekday}}`}</code> — Day of the week</li>
                      <li><code className="rounded bg-foreground/10 px-1 py-0.5 font-mono">{`{{agent_name}}`}</code> — Agent name</li>
                      <li><code className="rounded bg-foreground/10 px-1 py-0.5 font-mono">{`{{run_number}}`}</code> — Run sequence number</li>
                    </ul>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </FieldLabel>
            <textarea
              id="auto-prompt"
              className="flex min-h-[100px] w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-destructive aria-[invalid=true]:focus-visible:ring-destructive"
              placeholder="Summarize workspace files changed today. Use {{date}} for the current date."
              aria-invalid={validationErrors.promptTemplate ? true : undefined}
              value={formData.promptTemplate}
              onChange={(e) => updateField("promptTemplate", e.target.value)}
            />
            {validationErrors.promptTemplate && <FieldError>{validationErrors.promptTemplate}</FieldError>}
          </Field>

          {/* Session Strategy */}
          <Field>
            <FieldLabel>Context Strategy</FieldLabel>
            <div className="flex flex-col gap-2 rounded-md border p-3">
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="sessionStrategy"
                  checked={formData.sessionStrategy === "reuse"}
                  onChange={() => updateField("sessionStrategy", "reuse")}
                  className="mt-1"
                />
                <div>
                  <p className="text-sm font-medium">Continuous</p>
                  <p className="text-xs text-muted-foreground">
                    Agent remembers previous runs, can compare and track changes.
                  </p>
                </div>
              </label>
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="sessionStrategy"
                  checked={formData.sessionStrategy === "isolate"}
                  onChange={() => updateField("sessionStrategy", "isolate")}
                  className="mt-1"
                />
                <div>
                  <p className="text-sm font-medium">Independent</p>
                  <p className="text-xs text-muted-foreground">
                    Each run starts fresh, no memory of previous executions.
                  </p>
                </div>
              </label>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <label className="flex items-start gap-2 cursor-not-allowed opacity-50">
                      <input
                        type="radio"
                        name="sessionStrategy"
                        checked={formData.sessionStrategy === "this_session"}
                        onChange={() => updateField("sessionStrategy", "this_session")}
                        className="mt-1"
                        disabled
                      />
                      <div>
                        <p className="text-sm font-medium">Channel Session</p>
                        <p className="text-xs text-muted-foreground">
                          Run within the current channel conversation. Results are
                          delivered back to the channel.
                        </p>
                      </div>
                    </label>
                  </TooltipTrigger>
                  <TooltipContent>
                    Only available when created from a channel conversation
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
          </Field>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Apply a proposal's fields into an existing FormData object. */
function applyProposal(data: FormData, proposal: AutomationProposal): void {
  data.name = proposal.name;
  data.promptTemplate = proposal.promptTemplate;
  data.timezone = proposal.timezone ?? "UTC";
  data.sessionStrategy = proposal.sessionStrategy ?? "reuse";

  const parsed = parseCronForForm(proposal.cron);
  data.frequency = parsed.frequency;
  data.customCron = parsed.customCron;
  data.timeHour = parsed.timeHour;
  data.timeMinute = parsed.timeMinute;
}

/** Build FormData from an existing automation for edit mode. */
function buildEditFormData(automation: ClientAutomation): FormData {
  try {
    const config = JSON.parse(automation.trigger_config) as { cron?: string; timezone?: string };
    const parsed = parseCronForForm(config.cron ?? "");
    return {
      name: automation.name,
      agentId: String(automation.agent_id),
      promptTemplate: automation.prompt_template,
      frequency: parsed.frequency,
      customCron: parsed.customCron,
      timeHour: parsed.timeHour,
      timeMinute: parsed.timeMinute,
      timezone: config.timezone ?? "UTC",
      sessionStrategy: automation.session_strategy,
    };
  } catch {
    return {
      name: automation.name,
      agentId: String(automation.agent_id),
      promptTemplate: automation.prompt_template,
      frequency: "custom",
      customCron: "",
      timeHour: "9",
      timeMinute: "0",
      timezone: "UTC",
      sessionStrategy: automation.session_strategy,
    };
  }
}
