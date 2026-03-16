import {
  Check,
  Circle,
  Maximize2,
  Minimize2,
  ListTodo,
  Loader2,
  XCircle,
} from "lucide-react";
import { useState } from "react";

import type { TaskPlanSnapshot } from "../types";

interface ComposerTaskPlanProps {
  taskPlan: TaskPlanSnapshot;
}

/**
 * Renders the Codex-style task plan panel that grows out above the composer.
 */
export function ComposerTaskPlan({ taskPlan }: ComposerTaskPlanProps) {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);
  const completedCount = taskPlan.steps.filter(
    (step) => step.status === "done",
  ).length;

  return (
    <div className="mx-2 overflow-hidden rounded-[28px] rounded-b-none border border-border/70 border-b-0 bg-foreground/[0.03] shadow-[0_10px_28px_rgba(0,0,0,0.12)]">
      <div
        className={`flex items-center justify-between px-4 py-1.5 text-[12.5px] text-muted-foreground ${
          isExpanded ? "border-b border-border/60" : ""
        }`}
      >
        <div className="flex items-center gap-2">
          <ListTodo className="h-[15px] w-[15px]" />
          <span className="font-medium tracking-[0.01em]">
            {completedCount} out of {taskPlan.steps.length} tasks completed
          </span>
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded((previous) => !previous)}
          className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground/80 transition-colors duration-200 hover:bg-white/5 hover:text-foreground"
          aria-label={isExpanded ? "Collapse task plan" : "Expand task plan"}
          title={isExpanded ? "Collapse task plan" : "Expand task plan"}
        >
          <span className="relative h-3 w-3">
            <Minimize2
              className={`absolute inset-0 h-3 w-3 transition-all duration-[250ms] ease-out ${
                isExpanded
                  ? "rotate-0 scale-100 opacity-100"
                  : "-rotate-90 scale-75 opacity-0"
              }`}
            />
            <Maximize2
              className={`absolute inset-0 h-3 w-3 transition-all duration-[250ms] ease-out ${
                isExpanded
                  ? "rotate-90 scale-75 opacity-0"
                  : "rotate-0 scale-100 opacity-100"
              }`}
            />
          </span>
        </button>
      </div>

      <div
        aria-hidden={!isExpanded}
        data-testid="composer-task-plan-body"
        className={`grid transition-[grid-template-rows,opacity] duration-[250ms] ease-out ${
          isExpanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        }`}
      >
        <div className="overflow-hidden">
          <div className="space-y-0 px-4 py-1.5">
            {taskPlan.steps.map((step, index) => {
              const icon =
                step.status === "running" ? (
                  <Loader2 className="h-[14px] w-[14px] animate-spin text-foreground/85" />
                ) : step.status === "done" ? (
                  <span className="flex h-[14px] w-[14px] items-center justify-center rounded-full border border-muted-foreground/80 text-muted-foreground">
                    <Check className="h-[10px] w-[10px]" strokeWidth={3} />
                  </span>
                ) : step.status === "error" ? (
                  <XCircle className="h-[14px] w-[14px] text-danger" />
                ) : (
                  <Circle className="h-[14px] w-[14px] text-muted-foreground/80" />
                );

              return (
                <div
                  key={step.stepId}
                  className="flex items-start gap-2.5 py-[4px]"
                  title={step.description || step.completionCriteria || step.title}
                >
                  <div className="flex h-5 w-4 flex-shrink-0 items-center justify-center -translate-y-px">
                    {icon}
                  </div>
                  <div
                    className={`min-w-0 text-[12.5px] leading-[1.45] tracking-[0.005em] ${
                      step.status === "done"
                        ? "text-muted-foreground line-through decoration-muted-foreground/60"
                        : step.status === "error"
                          ? "text-danger"
                          : "text-foreground"
                    }`}
                  >
                    <span className="mr-2 text-muted-foreground/90">
                      {index + 1}.
                    </span>
                    <span>{step.title}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
