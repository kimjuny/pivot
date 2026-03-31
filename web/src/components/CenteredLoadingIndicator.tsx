import { Loader2 } from "@/lib/lucide";

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
   * Optional size overrides for the spinner icon.
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
  const containerClassName = [
    "flex items-center justify-center bg-background",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const iconClassName = [
    "h-6 w-6 animate-spin text-muted-foreground",
    spinnerClassName,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={containerClassName}
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <Loader2 className={iconClassName} aria-hidden="true" />
    </div>
  );
}
