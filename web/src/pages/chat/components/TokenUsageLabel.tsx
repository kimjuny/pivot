import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import type { TokenUsage } from "../types";
import { formatTokenCount } from "../utils/chatSelectors";

interface TokenUsageLabelProps {
  tokens: TokenUsage;
  label: string;
  className?: string;
}

/**
 * Shows a compact token label with a hover breakdown of input, cached input, output, and total usage.
 */
export function TokenUsageLabel({
  tokens,
  label,
  className,
}: TokenUsageLabelProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={
              className ??
              "cursor-help whitespace-nowrap text-xs tabular-nums text-muted-foreground underline decoration-dotted underline-offset-2"
            }
          >
            {label}
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs leading-relaxed">
          <div>Input: {formatTokenCount(tokens.prompt_tokens)}</div>
          <div>
            Cached Input: {formatTokenCount(tokens.cached_input_tokens ?? 0)}
          </div>
          <div>Output: {formatTokenCount(tokens.completion_tokens)}</div>
          <div>Total: {formatTokenCount(tokens.total_tokens)}</div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
