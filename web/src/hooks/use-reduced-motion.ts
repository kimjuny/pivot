import { useEffect, useState } from "react";

/**
 * Subscribes to the `prefers-reduced-motion` media query so animation-heavy
 * components can render terminal states immediately when users opt out of
 * motion at the OS level. This is the accessibility default for dashboards
 * with frequent count-ups, chart reveals, and color-flash highlights.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = (event: MediaQueryListEvent) => setReduced(event.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return reduced;
}
