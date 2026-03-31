import { cn } from "@/lib/utils";
import { motion, type Transition } from "motion/react";
import { useEffect, useState } from "react";

const LOADING_TONES = [
  { id: "chart-1", className: "bg-chart-1" },
  { id: "chart-2", className: "bg-chart-2" },
  { id: "chart-3", className: "bg-chart-3" },
  { id: "chart-4", className: "bg-chart-4" },
] as const;

const INITIAL_ORDER = LOADING_TONES.map((_, index) => index);

const SPRING: Transition = {
  type: "spring",
  damping: 20,
  stiffness: 300,
};

/**
 * Props for the Motion reorder loading animation.
 */
export interface MotionReorderLoadingProps {
  /**
   * Optional size overrides for the square animation footprint.
   */
  className?: string;
  /**
   * Delay before the animation becomes visible.
   */
  revealDelayMs?: number;
  /**
   * Interval between reorder passes.
   */
  reorderIntervalMs?: number;
}

function shuffleOrder(order: number[]): number[] {
  const nextOrder = [...order];

  for (let index = nextOrder.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [nextOrder[index], nextOrder[swapIndex]] = [
      nextOrder[swapIndex],
      nextOrder[index],
    ];
  }

  return nextOrder;
}

/**
 * Recreates Motion's reorder example as a compact loading treatment.
 *
 * Why: delaying the reveal prevents fast page refreshes from flashing an
 * unnecessary loading animation, while longer waits still get a lively status
 * indicator that feels more intentional than a spinner.
 */
export function MotionReorderLoading({
  className,
  revealDelayMs = 1000,
  reorderIntervalMs = 1000,
}: MotionReorderLoadingProps) {
  const [order, setOrder] = useState<number[]>(INITIAL_ORDER);
  const [isVisible, setIsVisible] = useState(revealDelayMs <= 0);

  useEffect(() => {
    setOrder(INITIAL_ORDER);

    if (revealDelayMs <= 0) {
      setIsVisible(true);
      return undefined;
    }

    setIsVisible(false);
    const timeoutId = window.setTimeout(() => {
      setIsVisible(true);
    }, revealDelayMs);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [revealDelayMs]);

  useEffect(() => {
    if (!isVisible) {
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      setOrder((currentOrder) => shuffleOrder(currentOrder));
    }, reorderIntervalMs);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [isVisible, reorderIntervalMs]);

  const footprintClassName = cn("h-10 w-10", className);

  if (!isVisible) {
    return (
      <div
        aria-hidden="true"
        className={cn("opacity-0", footprintClassName)}
        data-testid="reorder-loading-placeholder"
      />
    );
  }

  return (
    <motion.ul
      animate={{ opacity: 1, scale: 1 }}
      className={cn(
        "m-0 flex list-none flex-wrap items-center justify-center gap-[12%] p-0",
        footprintClassName,
      )}
      data-testid="reorder-loading-animation"
      initial={{ opacity: 0, scale: 0.92 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
    >
      {order.map((toneIndex) => {
        const tone = LOADING_TONES[toneIndex];

        return (
          <motion.li
            key={tone.id}
            className={cn(
              "h-[44%] w-[44%] rounded-[30%] shadow-sm ring-1 ring-background/40",
              tone.className,
            )}
            layout
            transition={SPRING}
          />
        );
      })}
    </motion.ul>
  );
}
