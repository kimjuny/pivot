import { useEffect, useRef, useState } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";

/** Configuration for {@link useCountUp}. */
export interface UseCountUpOptions {
  /** Total tween duration in milliseconds. Defaults to 800ms. */
  duration?: number;
  /** Number of decimal places preserved in the displayed value. */
  decimals?: number;
}

/** Cubic easeOut — fast initial change that settles smoothly into the target. */
function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/**
 * Animates a numeric value from 0 up to `target` using requestAnimationFrame
 * so the final frame lands exactly on the target value at t == duration.
 *
 * Intermediate frames are floored rather than rounded so the value can only
 * reach `target` when the eased progress is exactly 1 — i.e. the last visual
 * tick is always pinned to the end of the tween. With rounding, a target of
 * 1 would flip from 0 to 1 around the halfway mark (eased >= 0.5 rounds up),
 * leaving the second half of the duration static; flooring preserves the
 * intended "last bump lands at duration" rhythm for any magnitude, including
 * single-digit values where there is only one increment to render.
 *
 * Consumers typically remount this hook (via a `key` prop on an ancestor)
 * to replay the count-up when the underlying dataset changes.
 *
 * Respects `prefers-reduced-motion`: when the user has opted out, the hook
 * snaps directly to the target.
 */
export function useCountUp(
  target: number,
  options: UseCountUpOptions = {},
): { value: number } {
  const { duration = 800, decimals = 0 } = options;
  const reduced = useReducedMotion();
  const [value, setValue] = useState<number>(reduced ? target : 0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    if (reduced) {
      setValue(target);
      return;
    }

    const from = 0;
    if (from === target) {
      setValue(target);
      return;
    }

    const factor = Math.pow(10, decimals);
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start;
      const t = Math.min(1, elapsed / duration);
      if (t >= 1) {
        setValue(target);
        rafRef.current = null;
        return;
      }
      const eased = easeOutCubic(t);
      const next = from + (target - from) * eased;
      // Floor (toward zero for the negative-target case) ensures the
      // displayed value never reaches `target` until the very last frame,
      // so the final visible tick is always anchored to t == duration.
      const truncated =
        target >= 0
          ? Math.floor(next * factor) / factor
          : Math.ceil(next * factor) / factor;
      setValue(truncated);
      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [target, duration, decimals, reduced]);

  return { value };
}
