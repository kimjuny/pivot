import { useEffect, useRef, useState } from "react";

import { Spinner } from "@/components/ui/spinner";

interface CompactStatusPillProps {
  message: string | null;
}

/**
 * Floating compact-status pill anchored just above the composer.
 *
 * Uses absolute positioning so it overlays the scrollable message area with no
 * opaque background — only the pill's own frosted-glass backdrop-blur is visible.
 */
export function CompactStatusPill({ message }: CompactStatusPillProps) {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (message) {
      setIsVisible(true);
    } else {
      setIsVisible(false);
    }
  }, [message]);

  return (
    <div
      className="pointer-events-none absolute inset-x-0 bottom-[12rem] z-10 flex items-center justify-center px-4 transition-[opacity,transform] duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
      style={{
        opacity: message ? 1 : 0,
        transform: message ? "translateY(0)" : "translateY(12px)",
      }}
      aria-live="polite"
    >
      <div className="pointer-events-auto flex max-w-[calc(100vw-2rem)] items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-2 text-sm text-foreground shadow-lg backdrop-blur-md">
        <Spinner size={16} className="shrink-0" />
        <span className="truncate">{message}</span>
      </div>
    </div>
  );
}
