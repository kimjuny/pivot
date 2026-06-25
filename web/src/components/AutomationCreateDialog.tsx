import { useEffect, useRef, useState } from "react";
import {
  Bot,
  ChevronRight,
  CircleAlert,
  Clock,
  Info,
  Loader2,
  MessageCircle,
  Timer,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { LLMBrandAvatar } from "@/components/LLMBrandAvatar";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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

type SessionStrategy = "reuse" | "isolate" | "this_session";

interface FormData {
  name: string;
  agentId: string;
  promptTemplate: string;
  frequency: string;
  customCron: string;
  timeHour: string;
  timeMinute: string;
  sessionStrategy: SessionStrategy;
  timeoutSeconds: string;
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
    sessionStrategy: "reuse",
    timeoutSeconds: "300",
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
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekly", label: "Weekly" },
  { value: "monthly", label: "Monthly" },
  { value: "custom", label: "Custom" },
];

const SESSION_STRATEGY_OPTIONS: Array<{
  value: SessionStrategy;
  label: string;
  disabled: boolean;
}> = [
  { value: "reuse", label: "Continuous", disabled: false },
  { value: "isolate", label: "Independent", disabled: false },
  { value: "this_session", label: "Channel session", disabled: true },
] as const;

function getFrequencyLabel(value: string): string {
  return FREQUENCY_OPTIONS.find((option) => option.value === value)?.label ?? "Custom cron";
}

const MENU_ITEM_CLASS = "my-0.5 flex min-h-8 items-center px-2 py-0.5";
const SELECTED_MENU_ITEM_CLASS = `${MENU_ITEM_CLASS} bg-accent font-medium`;
const MENU_CONTENT_CLASS = "w-auto px-2 py-1";
const MENU_HEADER_CLASS = "flex h-6 items-center justify-between gap-3 px-0 py-0 text-xs leading-none";
const MENU_SEPARATOR_CLASS = "-mx-2 my-0";

function MenuHeader({
  label,
  description,
}: {
  label: string;
  description: string;
}) {
  return (
    <DropdownMenuLabel className={MENU_HEADER_CLASS}>
      <span>{label}</span>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            className="flex size-4 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
          >
            <CircleAlert className="size-3.5" aria-hidden="true" />
            <span className="sr-only">{label} help</span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="right" align="start" className="max-w-56 text-xs">
          {description}
        </TooltipContent>
      </Tooltip>
    </DropdownMenuLabel>
  );
}

function getScheduleLabel(data: FormData): string {
  if (data.frequency === "custom") return data.customCron.trim() || "Custom";
  if (data.frequency === "hourly") {
    return `Hourly at :${data.timeMinute.padStart(2, "0")}`;
  }
  return `${getFrequencyLabel(data.frequency)} at ${data.timeHour.padStart(2, "0")}:${data.timeMinute.padStart(2, "0")}`;
}

function getSessionStrategyLabel(value: FormData["sessionStrategy"]): string {
  return SESSION_STRATEGY_OPTIONS.find((option) => option.value === value)?.label ?? "Continuous";
}

function normalizeTimePart(value: string, max: number): string {
  const digits = value.replace(/\D/g, "").slice(0, 2);
  if (!digits) return "";
  const numericValue = Number(digits);
  if (Number.isNaN(numericValue)) return "";
  return String(Math.min(numericValue, max)).padStart(2, "0");
}

interface TimeSlotInputProps {
  hour: string;
  minute: string;
  disabledHour?: boolean;
  onChange: (next: { hour: string; minute: string }) => void;
}

function TimeSlotInput({
  hour,
  minute,
  disabledHour = false,
  onChange,
}: TimeSlotInputProps) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = `${normalizeTimePart(hour || "0", 23)}${normalizeTimePart(minute || "0", 59)}`.padEnd(4, "0");

  const updateDigit = (index: number, value: string) => {
    const nextChar = value.replace(/\D/g, "").slice(-1);
    if (!nextChar) return;
    const nextDigits = digits.split("");
    nextDigits[index] = nextChar;
    onChange({
      hour: normalizeTimePart(nextDigits.slice(0, 2).join(""), 23),
      minute: normalizeTimePart(nextDigits.slice(2, 4).join(""), 59),
    });
    refs.current[index + 1]?.focus();
  };

  return (
    <div className="flex h-10 items-center justify-center gap-0.5">
      {[0, 1].map((index) => (
        <input
          key={index}
          ref={(element) => {
            refs.current[index] = element;
          }}
          value={digits[index]}
          disabled={disabledHour}
          inputMode="numeric"
          maxLength={1}
          onChange={(event) => updateDigit(index, event.target.value)}
          className="flex size-7 rounded-md border border-input bg-background text-center text-xs shadow-sm outline-none transition-colors focus:border-ring disabled:cursor-not-allowed disabled:opacity-45"
        />
      ))}
      <span className="px-0.5 text-xs text-muted-foreground">:</span>
      {[2, 3].map((index) => (
        <input
          key={index}
          ref={(element) => {
            refs.current[index] = element;
          }}
          value={digits[index]}
          inputMode="numeric"
          maxLength={1}
          onChange={(event) => updateDigit(index, event.target.value)}
          className="flex size-7 rounded-md border border-input bg-background text-center text-xs shadow-sm outline-none transition-colors focus:border-ring"
        />
      ))}
    </div>
  );
}

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
    const timeoutSeconds = Number(formData.timeoutSeconds);
    if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1) {
      errors.timeoutSeconds = "Timeout must be a positive whole number";
    }

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
          trigger_config: JSON.stringify({ cron }),
          session_strategy: formData.sessionStrategy,
          timeout_seconds: timeoutSeconds,
        });
        toast.success("Automation updated");
        onUpdated?.();
      } else {
        const payload: ClientAutomationCreatePayload = {
          name: formData.name.trim(),
          agent_id: Number(formData.agentId),
          prompt_template: formData.promptTemplate.trim(),
          trigger_config: JSON.stringify({ cron }),
          session_strategy: formData.sessionStrategy,
          timeout_seconds: timeoutSeconds,
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

  const selectedAgent = agents.find((agent) => String(agent.id) === formData.agentId);
  const agentLabel = isEdit
    ? automation?.agent_name ?? selectedAgent?.name ?? "Agent"
    : selectedAgent?.name ?? "Agent";
  const submitTimeoutSeconds = Number(formData.timeoutSeconds);
  const canSubmit =
    formData.name.trim().length > 0 &&
    formData.promptTemplate.trim().length > 0 &&
    (isEdit || formData.agentId.length > 0) &&
    Number.isInteger(submitTimeoutSeconds) &&
    submitTimeoutSeconds > 0 &&
    (formData.frequency !== "custom" ||
      (formData.customCron.trim().length > 0 &&
        validateCron(formData.customCron) === null));

  return (
    <TooltipProvider delayDuration={200}>
      <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="flex max-h-[86vh] w-[min(860px,calc(100vw-2rem))] max-w-none flex-col gap-0 overflow-hidden rounded-2xl border bg-card p-0 shadow-2xl sm:max-w-[860px] sm:rounded-3xl">
        <DialogHeader className="sr-only">
          <DialogTitle>{isEdit ? "Edit automation" : "New automation"}</DialogTitle>
        </DialogHeader>

        <div className="flex min-h-[360px] flex-1 flex-col px-7 pb-4 pt-7">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1 space-y-3">
              <Input
                id="auto-name"
                placeholder="Automation title"
                aria-invalid={validationErrors.name ? true : undefined}
                value={formData.name}
                onChange={(e) => updateField("name", e.target.value)}
                className="h-auto border-0 bg-transparent px-0 py-0 text-base font-medium shadow-none outline-none placeholder:text-muted-foreground/70 focus-visible:ring-0 focus-visible:ring-offset-0 aria-[invalid=true]:text-destructive md:text-base"
              />
              {validationErrors.name && (
                <p className="text-xs text-destructive">{validationErrors.name}</p>
              )}
            </div>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" className="h-9 rounded-xl px-3">
                  <Info className="mr-2 size-4" aria-hidden="true" />
                  Variables
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-auto min-w-56 max-w-64">
                <DropdownMenuLabel>Template variables</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {[
                  ["{{date}}", "Current date"],
                  ["{{time}}", "Current time"],
                  ["{{datetime}}", "Current date and time"],
                  ["{{weekday}}", "Day of the week"],
                  ["{{agent_name}}", "Agent name"],
                  ["{{run_number}}", "Run sequence number"],
                ].map(([token, description]) => (
                  <DropdownMenuItem
                    key={token}
                    onSelect={(event) => {
                      event.preventDefault();
                      updateField("promptTemplate", `${formData.promptTemplate}${token}`);
                    }}
                  >
                    <code className="rounded bg-foreground/10 px-1 py-0.5 font-mono text-xs">
                      {token}
                    </code>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {description}
                    </span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <textarea
            id="auto-prompt"
            className="mt-5 min-h-[96px] max-h-72 resize-none overflow-y-auto border-0 bg-transparent p-0 text-sm leading-6 outline-none placeholder:text-muted-foreground/50 focus-visible:outline-none aria-[invalid=true]:placeholder:text-destructive/70 [field-sizing:content]"
            placeholder="Add prompt e.g. look for crashes in $sentry"
            aria-invalid={validationErrors.promptTemplate ? true : undefined}
            value={formData.promptTemplate}
            onChange={(e) => updateField("promptTemplate", e.target.value)}
          />
          {validationErrors.promptTemplate && (
            <p className="mt-2 text-xs text-destructive">
              {validationErrors.promptTemplate}
            </p>
          )}

          <div className="mt-auto flex flex-col gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-wrap items-center gap-1 overflow-hidden sm:flex-1 sm:flex-nowrap">
              <DropdownMenu>
                <DropdownMenuTrigger asChild disabled={isEdit}>
                  <Button
                    variant="ghost"
                    className="group h-8 max-w-[145px] rounded-full px-2.5 text-xs"
                    aria-invalid={validationErrors.agentId ? true : undefined}
                  >
                    <UserRound className="mr-0.5 size-3.5 shrink-0" aria-hidden="true" />
                    <span className="truncate">{agentLabel}</span>
                    {!isEdit && (
                      <ChevronRight className="ml-0.5 size-3.5 shrink-0 transition-transform duration-150 ease-out group-data-[state=open]:rotate-90" aria-hidden="true" />
                    )}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className={`${MENU_CONTENT_CLASS} min-w-44 max-w-64`}
                >
                  <MenuHeader
                    label="Agent"
                    description="Choose which agent runs this automation."
                  />
                  <DropdownMenuSeparator className={MENU_SEPARATOR_CLASS} />
                  {agents.map((agent) => (
                    <DropdownMenuItem
                      key={agent.id}
                      className={MENU_ITEM_CLASS}
                      onSelect={() => updateField("agentId", String(agent.id))}
                    >
                      <LLMBrandAvatar
                        model={agent.model_name}
                        fallback={<Bot className="size-3.5" aria-hidden="true" />}
                        containerClassName="flex size-5 shrink-0 items-center justify-center rounded-md bg-primary/10"
                        imageClassName="size-3.5"
                      />
                      <span className="truncate">{agent.name}</span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    className="group h-8 max-w-[185px] rounded-full px-2.5 text-xs"
                    aria-invalid={validationErrors.schedule ? true : undefined}
                  >
                    <Clock className="mr-0.5 size-3.5 shrink-0" aria-hidden="true" />
                    <span className="truncate">{getScheduleLabel(formData)}</span>
                    <ChevronRight className="ml-0.5 size-3.5 shrink-0 transition-transform duration-150 ease-out group-data-[state=open]:rotate-90" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className={`${MENU_CONTENT_CLASS} min-w-36`}
                >
                  <MenuHeader
                    label="Schedule"
                    description="Set when this automation runs. Times use your system timezone."
                  />
                  <DropdownMenuSeparator className={MENU_SEPARATOR_CLASS} />
                  {FREQUENCY_OPTIONS.map((option) => (
                    <DropdownMenuItem
                      key={option.value}
                      className={
                        formData.frequency === option.value
                          ? SELECTED_MENU_ITEM_CLASS
                          : MENU_ITEM_CLASS
                      }
                      onSelect={(event) => {
                        event.preventDefault();
                        updateField("frequency", option.value);
                      }}
                    >
                      {option.label}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuSeparator className={MENU_SEPARATOR_CLASS} />
                  {formData.frequency === "custom" ? (
                    <div className="flex h-11 items-center">
                      <Input
                        placeholder="0 9 * * 1-5"
                        className="h-8 text-xs md:text-xs"
                        value={formData.customCron}
                        aria-invalid={validationErrors.schedule ? true : undefined}
                        onChange={(e) => updateField("customCron", e.target.value)}
                      />
                    </div>
                  ) : (
                    <TimeSlotInput
                      hour={formData.timeHour}
                      minute={formData.timeMinute}
                      disabledHour={formData.frequency === "hourly"}
                      onChange={({ hour, minute }) => {
                        updateField("timeHour", hour);
                        updateField("timeMinute", minute);
                      }}
                    />
                  )}
                  {validationErrors.schedule && (
                    <p className="mt-2 text-xs text-destructive">
                      {validationErrors.schedule}
                    </p>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    className="group h-8 max-w-[155px] rounded-full px-2.5 text-xs"
                  >
                    <MessageCircle className="mr-0.5 size-3.5" aria-hidden="true" />
                    <span className="truncate">
                      {getSessionStrategyLabel(formData.sessionStrategy)}
                    </span>
                    <ChevronRight className="ml-0.5 size-3.5 transition-transform duration-150 ease-out group-data-[state=open]:rotate-90" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className={`${MENU_CONTENT_CLASS} min-w-40`}
                >
                  <MenuHeader
                    label="Context"
                    description="Choose whether runs continue the same conversation context or start fresh."
                  />
                  <DropdownMenuSeparator className={MENU_SEPARATOR_CLASS} />
                  {SESSION_STRATEGY_OPTIONS.map((option) => (
                    <DropdownMenuItem
                      key={option.value}
                      disabled={option.disabled}
                      className={
                        formData.sessionStrategy === option.value
                          ? SELECTED_MENU_ITEM_CLASS
                          : MENU_ITEM_CLASS
                      }
                      onSelect={() => updateField("sessionStrategy", option.value)}
                    >
                      {option.label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    className="group h-8 rounded-full px-2.5 text-xs"
                    aria-invalid={validationErrors.timeoutSeconds ? true : undefined}
                  >
                    <Timer className="mr-0.5 size-3.5" aria-hidden="true" />
                    {formData.timeoutSeconds || "300"}s
                    <ChevronRight className="ml-0.5 size-3.5 transition-transform duration-150 ease-out group-data-[state=open]:rotate-90" aria-hidden="true" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  className={`${MENU_CONTENT_CLASS} min-w-36`}
                >
                  <MenuHeader
                    label="Timeout"
                    description="Maximum time each automation run can spend before it stops."
                  />
                  <DropdownMenuSeparator className={MENU_SEPARATOR_CLASS} />
                  <div className="flex h-11 items-center">
                    <InputGroup className="h-8 w-40">
                      <InputGroupInput
                        type="number"
                        min="1"
                        className="h-8 text-xs md:text-xs"
                        value={formData.timeoutSeconds}
                        aria-invalid={validationErrors.timeoutSeconds ? true : undefined}
                        onChange={(e) => updateField("timeoutSeconds", e.target.value)}
                      />
                      <InputGroupAddon align="inline-end" className="pr-2 text-xs">
                        seconds
                      </InputGroupAddon>
                    </InputGroup>
                  </div>
                  {validationErrors.timeoutSeconds && (
                    <p className="mt-2 text-xs text-destructive">
                      {validationErrors.timeoutSeconds}
                    </p>
                  )}
                </DropdownMenuContent>
              </DropdownMenu>

            </div>

            <div className="flex items-center justify-end gap-2">
              <Button variant="ghost" onClick={onClose} disabled={isSubmitting}>
                Cancel
              </Button>
              <Button
                onClick={() => void handleSubmit()}
                disabled={isSubmitting || !canSubmit}
              >
                {isSubmitting && <Loader2 className="mr-2 size-4 animate-spin" />}
                {isEdit ? "Save" : "Create"}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}

/** Apply a proposal's fields into an existing FormData object. */
function applyProposal(data: FormData, proposal: AutomationProposal): void {
  data.name = proposal.name;
  data.promptTemplate = proposal.promptTemplate;
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
    const config = JSON.parse(automation.trigger_config) as { cron?: string };
    const parsed = parseCronForForm(config.cron ?? "");
    return {
      name: automation.name,
      agentId: String(automation.agent_id),
      promptTemplate: automation.prompt_template,
      frequency: parsed.frequency,
      customCron: parsed.customCron,
      timeHour: parsed.timeHour,
      timeMinute: parsed.timeMinute,
      sessionStrategy: automation.session_strategy,
      timeoutSeconds: String(automation.timeout_seconds),
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
      sessionStrategy: automation.session_strategy,
      timeoutSeconds: String(automation.timeout_seconds),
    };
  }
}
