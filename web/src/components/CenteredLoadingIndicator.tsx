import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

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
}: CenteredLoadingIndicatorProps) {
  const containerClassName = cn(
    "flex items-center justify-center bg-background",
    className,
  );

  return (
    <div className={containerClassName} role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Spinner
        aria-hidden="true"
        size={20}
        data-testid="centered-loading-spinner"
      />
    </div>
  );
}
