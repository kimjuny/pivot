import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  type ClientAutomationCreatePayload,
  createClientAutomation,
} from "@/client/api";
import type { Agent } from "@/types";

interface AutomationCreateDialogProps {
  open: boolean;
  agents: Agent[];
  defaultAgentId?: number;
  onClose: () => void;
  onCreated: () => void;
}

interface FormData {
  name: string;
  description: string;
  agentId: string;
  promptTemplate: string;
  frequency: string;
  customCron: string;
  timeHour: string;
  timeMinute: string;
  timezone: string;
  sessionStrategy: "reuse" | "isolate";
}

function buildDefaultFormData(): FormData {
  return {
    name: "",
    description: "",
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

const FREQUENCY_OPTIONS = [
  { value: "hourly", label: "Every hour" },
  { value: "daily", label: "Every day" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekly", label: "Every week" },
  { value: "monthly", label: "Every month" },
  { value: "custom", label: "Custom cron" },
];

/**
 * Dialog for creating a new automation with schedule and prompt configuration.
 */
export function AutomationCreateDialog({
  open,
  agents,
  defaultAgentId,
  onClose,
  onCreated,
}: AutomationCreateDialogProps) {
  const [formData, setFormData] = useState<FormData>(() => {
    const defaults = buildDefaultFormData();
    if (defaultAgentId !== undefined) {
      defaults.agentId = String(defaultAgentId);
    }
    return defaults;
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateField = <K extends keyof FormData>(key: K, value: FormData[K]) => {
    setFormData((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async () => {
    setError(null);

    if (!formData.name.trim()) {
      setError("Name is required");
      return;
    }
    if (!formData.agentId) {
      setError("Agent is required");
      return;
    }
    if (!formData.promptTemplate.trim()) {
      setError("Prompt template is required");
      return;
    }

    const cron = buildCronExpression(formData);
    if (!cron.trim()) {
      setError("Schedule configuration is required");
      return;
    }

    const payload: ClientAutomationCreatePayload = {
      name: formData.name.trim(),
      description: formData.description.trim() || null,
      agent_id: Number(formData.agentId),
      prompt_template: formData.promptTemplate.trim(),
      trigger_config: JSON.stringify({
        cron,
        timezone: formData.timezone,
      }),
      session_strategy: formData.sessionStrategy,
    };

    setIsSubmitting(true);
    try {
      await createClientAutomation(payload);
      toast.success("Automation created");
      setFormData(buildDefaultFormData());
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create automation");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-[640px] max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New Automation</DialogTitle>
        </DialogHeader>

        {error && (
          <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-5 py-2">
          {/* Name */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="auto-name">Name</Label>
            <Input
              id="auto-name"
              placeholder="Daily Report"
              value={formData.name}
              onChange={(e) => updateField("name", e.target.value)}
            />
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="auto-desc">Description</Label>
            <Input
              id="auto-desc"
              placeholder="Optional description"
              value={formData.description}
              onChange={(e) => updateField("description", e.target.value)}
            />
          </div>

          {/* Agent */}
          <div className="flex flex-col gap-1.5">
            <Label>Agent</Label>
            <Select
              value={formData.agentId}
              onValueChange={(val) => updateField("agentId", val)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select an agent" />
              </SelectTrigger>
              <SelectContent>
                {agents.map((agent) => (
                  <SelectItem key={agent.id} value={String(agent.id)}>
                    {agent.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Schedule */}
          <div className="flex flex-col gap-3">
            <Label>Schedule</Label>
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

              {formData.frequency !== "custom" && formData.frequency !== "hourly" ? (
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
              ) : formData.frequency === "custom" ? (
                <Input
                  placeholder="0 9 * * 1-5"
                  className="flex-1"
                  value={formData.customCron}
                  onChange={(e) => updateField("customCron", e.target.value)}
                />
              ) : (
                <span className="text-sm text-muted-foreground">
                  at :{formData.timeMinute || "0"}
                </span>
              )}
            </div>
          </div>

          {/* Prompt Template */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="auto-prompt">Prompt Template</Label>
            <textarea
              id="auto-prompt"
              className="flex min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              placeholder="Summarize workspace files changed today. Use {{date}} for the current date."
              value={formData.promptTemplate}
              onChange={(e) => updateField("promptTemplate", e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Variables: {"{{date}}"}, {"{{time}}"}, {"{{datetime}}"}, {"{{weekday}}"}
            </p>
          </div>

          {/* Session Strategy */}
          <div className="flex flex-col gap-2">
            <Label>Context Strategy</Label>
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
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
