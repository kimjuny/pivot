import { CheckCircle2, Loader2 } from "@/lib/lucide";

import type { SkillSelectionState } from "../types";
import { formatTokenCount } from "../utils/chatSelectors";
import { TokenUsageLabel } from "./TokenUsageLabel";

interface SkillSelectionCardProps {
  skillSelection: SkillSelectionState;
}

/**
 * Surfaces the pre-execution skill matching state before recursive reasoning begins.
 */
export function SkillSelectionCard({
  skillSelection,
}: SkillSelectionCardProps) {
  return (
    <div className="overflow-hidden rounded-md border border-border bg-muted/20">
      <div className="flex w-full items-center justify-between px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {skillSelection.status === "loading" ? (
            <>
              <Loader2 className="h-3.5 w-3.5 flex-shrink-0 animate-spin text-primary" />
              <span
                className="animate-thinking-wave truncate text-xs font-semibold"
                style={{
                  background:
                    "linear-gradient(90deg, #9ca3af 0%, #e5e7eb 25%, #f3f4f6 50%, #e5e7eb 75%, #9ca3af 100%)",
                  backgroundClip: "text",
                  backgroundSize: "400% 100%",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                }}
              >
                Matching Skills...
              </span>
            </>
          ) : (
            <>
              <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 text-success" />
              <span className="text-xs text-muted-foreground">
                Matched skills:{" "}
                {skillSelection.count > 0
                  ? skillSelection.selectedSkills.join(", ")
                  : "None"}
              </span>
            </>
          )}
        </div>
        {skillSelection.status === "done" && (
          <div className="flex flex-shrink-0 items-center gap-2.5">
            {typeof skillSelection.durationMs === "number" && (
              <span className="text-xs tabular-nums text-muted-foreground">
                {(skillSelection.durationMs / 1000).toFixed(1)}s
              </span>
            )}
            {skillSelection.tokens && (
              <TokenUsageLabel
                tokens={skillSelection.tokens}
                label={`${formatTokenCount(skillSelection.tokens.total_tokens)} tokens`}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
