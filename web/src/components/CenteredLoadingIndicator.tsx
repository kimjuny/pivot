import { Loader2 } from "@/lib/lucide";
import { cn } from "@/lib/utils";

/**
 * Props for the centered loading indicator.
 */
export interface CenteredLoadingIndicatorProps {
  /**
   * Accessible description announced while content is loading.
   */
  label?: string;
  /**
   * Optional container classes so the spinner can fill either the viewport
   * or an already constrained panel.
   */
  className?: string;
  /**
   * Optional size overrides for the loading icon footprint.
   *
   * Why: this keeps the legacy prop name stable for existing call sites while
   * letting the shared loading treatment stay drop-in compatible.
   */
  spinnerClassName?: string;
}

/**
 * Renders the minimal loading treatment shared across app surfaces.
 */
export function CenteredLoadingIndicator({
  label = "Loading",
  className,
  spinnerClassName,
}: CenteredLoadingIndicatorProps) {
  const containerClassName = cn(
    "flex items-center justify-center bg-background",
    className,
  );
  const iconClassName = cn(
    "h-6 w-6",
    spinnerClassName,
  );

  return (
    <div className={containerClassName} role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Loader2
        aria-hidden="true"
        className={cn(iconClassName, "animate-spin text-muted-foreground/70")}
        data-testid="centered-loading-spinner"
      />
    </div>
  );
}
