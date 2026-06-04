import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";

import type { ConversationRound } from "../hooks/useConversationRounds";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

interface RoundAnchorProps {
  rounds: ConversationRound[];
  onNavigateToRound: (round: ConversationRound) => void;
  scrollContainerRef: RefObject<HTMLElement | null>;
}

/** Visible anchor items at once — odd so center is symmetric. */
const WINDOW_SIZE = 7;
/** Center index within the visible window. */
const CENTER_INDEX = 3;
/** Each row height in px. */
const ROW_H = 28;
/** Gap between rows in px. */
const ROW_GAP = 4;
/** Vertical step per row. */
const STEP = ROW_H + ROW_GAP;
/** Extra buffer items rendered above/below for smooth animation. */
const BUFFER = 2;
/** Card fixed width. */
const CARD_W = 168;
/** Card inner padding. */
const PAD = 8;
/** Distance from screen right edge to dots. */
const DOT_OFFSET = 25;
/** Gap between the card and the dot column. */
const CARD_DOT_GAP = 8;

/**
 * Tracks which conversation round is currently visible in the scroll
 * container. The round whose user-message is closest to the 1/3 point
 * from the top of the container is considered active.
 */
function useActiveRoundIndex(
  rounds: ConversationRound[],
  scrollContainerRef: RefObject<HTMLElement | null>,
): number {
  const [activeIndex, setActiveIndex] = useState(() =>
    rounds.length > 0 ? rounds.length - 1 : 0,
  );
  const rafRef = useRef(0);

  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || rounds.length === 0) return;

    const update = () => {
      const containerRect = container.getBoundingClientRect();
      const refY = containerRect.top + 80;

      let active = 0;
      rounds.forEach((round, i) => {
        const el = container.querySelector(
          `[data-message-id="${round.userMessageId}"]`,
        );
        if (!el) return;
        const rect = el.getBoundingClientRect();
        if (rect.top <= refY) {
          active = i;
        }
      });

      setActiveIndex(active);
    };

    const onScroll = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(update);
    };

    container.addEventListener("scroll", onScroll, { passive: true });
    update();

    return () => {
      container.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(rafRef.current);
    };
  }, [rounds, scrollContainerRef]);

  return activeIndex;
}

/** Clamp windowStart so it stays within [0, total - WINDOW_SIZE]. */
function clampStart(start: number, total: number): number {
  if (total <= WINDOW_SIZE) return 0;
  return Math.max(0, Math.min(total - WINDOW_SIZE, start));
}

/** Dot diameter — uniform small, enlarged when focused or hovered. */
function dotSize(isFocused: boolean, isHovered: boolean): number {
  if (isFocused || isHovered) return 7;
  return 5;
}

/** Dot opacity — uniform dim, brighter when focused or hovered. Unloaded rounds are extra dim. */
function dotOpacity(isFocused: boolean, isHovered: boolean, isLoaded: boolean): number {
  if (isFocused) return 0.6;
  if (isHovered) return 0.5;
  if (!isLoaded) return 0.12;
  return 0.25;
}

/**
 * Fade factor for items near or outside the visible window edge.
 * Buffer items (outside 0..WINDOW_SIZE-1) are fully transparent
 * so they fade in smoothly as they slide into view via CSS transition.
 */
function edgeFade(localIdx: number): number {
  if (localIdx < 0 || localIdx >= WINDOW_SIZE) return 0;
  if (localIdx === 0 || localIdx === WINDOW_SIZE - 1) return 0.6;
  return 1;
}

/**
 * Compact anchor dots on the right edge of the chat pane with a
 * drum-rotation animation. Seven dots are visible at once; the focused
 * round is always kept at the center position (index 3).
 *
 * Clicks request navigation; scroll tracking remains the source of truth for
 * the focused round.
 */
export function RoundAnchor({
  rounds,
  onNavigateToRound,
  scrollContainerRef,
}: RoundAnchorProps) {
  const total = rounds.length;
  const [windowStart, setWindowStart] = useState(0);
  const [isExpanded, setIsExpanded] = useState(false);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  /**
   * When false, CSS transitions are disabled so the initial positioning
   * doesn't animate. Set to true after the first auto-follow snap.
   */
  const [hasInitialized, setHasInitialized] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<number | null>(null);
  const activeIndex = useActiveRoundIndex(rounds, scrollContainerRef);

  // Reset initialized state only when the set of round IDs changes (new session).
  const prevRoundIdsRef = useRef("");
  useEffect(() => {
    const ids = rounds.map((r) => r.taskId).join(",");
    if (ids !== prevRoundIdsRef.current) {
      prevRoundIdsRef.current = ids;
      setHasInitialized(false);
    }
  }, [rounds]);

  // Auto-follow: keep active item at center.
  useEffect(() => {
    setWindowStart((prev) => {
      const target = clampStart(activeIndex - CENTER_INDEX, total);
      if (prev === target) {
        if (!hasInitialized) setHasInitialized(true);
        return prev;
      }
      return target;
    });
    if (!hasInitialized) setHasInitialized(true);
  }, [activeIndex, total, hasInitialized]);

  // Rendered range includes buffer items above/below for smooth animation.
  const renderStart = Math.max(0, windowStart - BUFFER);
  const renderEnd = Math.min(total, windowStart + WINDOW_SIZE + BUFFER);
  const renderedRounds = useMemo(
    () => rounds.slice(renderStart, renderEnd),
    [rounds, renderStart, renderEnd],
  );

  /** CSS transition value — "none" for initial snap, smooth otherwise. */
  const transitionValue = hasInitialized
    ? "transform 300ms ease-out, opacity 300ms ease-out"
    : "none";

  const navigate = useCallback(
    (globalIndex: number) => {
      setHoveredIndex(null);
      setWindowStart(clampStart(globalIndex - CENTER_INDEX, total));
      onNavigateToRound(rounds[globalIndex]);
    },
    [rounds, total, onNavigateToRound],
  );

  const scheduleHide = useCallback(() => {
    if (hideTimerRef.current !== null) return;
    hideTimerRef.current = window.setTimeout(() => {
      setIsExpanded(false);
      setHoveredIndex(null);
      hideTimerRef.current = null;
    }, 120);
  }, []);

  const cancelHide = useCallback(() => {
    if (hideTimerRef.current !== null) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  if (total < 2) return null;

  const visibleHeight = WINDOW_SIZE * STEP - ROW_GAP;

  return (
    <div className="pointer-events-none absolute inset-0 z-10">
      <div
        ref={containerRef}
        className="pointer-events-auto absolute right-0 top-1/2 -translate-y-1/2 flex items-center justify-end"
        style={{ paddingRight: DOT_OFFSET }}
        onMouseEnter={() => {
          cancelHide();
          setIsExpanded(true);
        }}
        onMouseMove={() => {
          cancelHide();
        }}
        onMouseLeave={() => {
          scheduleHide();
        }}
      >
        {/* Card with text labels — appears to the left of dots */}
        {isExpanded && (
          <Card
            className="animate-in fade-in-0 border-border/50 bg-popover/95 shadow-md backdrop-blur-sm"
            style={{ width: CARD_W, padding: PAD, marginRight: CARD_DOT_GAP }}
          >
            <div
              className="relative overflow-hidden"
              style={{ height: visibleHeight }}
            >
              {renderedRounds.map((round) => {
                const globalIdx = renderStart + renderedRounds.indexOf(round);
                const localIdx = globalIdx - windowStart;
                const isItemHovered = hoveredIndex === globalIdx;
                const fade = edgeFade(localIdx);

                return (
                  <button
                    key={round.taskId}
                    type="button"
                    className="absolute left-0 right-0 flex w-full items-center rounded-lg transition-colors"
                    style={{
                      height: ROW_H,
                      paddingLeft: 4,
                      paddingRight: 4,
                      opacity: hasInitialized ? fade : fade > 0 ? 1 : 0,
                      transform: `translateY(${localIdx * STEP}px)`,
                      transition: transitionValue,
                    }}
                    onClick={() => {
                      navigate(globalIdx);
                    }}
                    onMouseEnter={() => {
                      cancelHide();
                      setHoveredIndex(globalIdx);
                    }}
                    onMouseLeave={() => setHoveredIndex(null)}
                  >
                    {round.isLoaded ? (
                      <span
                        className={`min-w-0 flex-1 truncate text-left text-xs ${
                          isItemHovered
                            ? "text-accent-foreground"
                            : globalIdx === activeIndex
                              ? "font-medium text-popover-foreground"
                              : "text-muted-foreground"
                        }`}
                      >
                        {round.preview}
                      </span>
                    ) : (
                      <span
                        className="flex min-w-0 flex-1 flex-col gap-1"
                        aria-hidden="true"
                      >
                        <Skeleton className="h-2 w-11/12" />
                        <Skeleton className="h-2 w-2/3" />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </Card>
        )}

        {/* Dots — drum rotation */}
        <div
          className="relative overflow-hidden"
          style={{ height: visibleHeight, width: 24 }}
        >
          {renderedRounds.map((round) => {
            const globalIdx = renderStart + renderedRounds.indexOf(round);
            const localIdx = globalIdx - windowStart;
            const isActive = globalIdx === activeIndex;
            const isItemHovered = hoveredIndex === globalIdx;
            const fade = edgeFade(localIdx);

            return (
              <button
                key={round.taskId}
                type="button"
                className="absolute left-0 right-0 flex items-center justify-end"
                style={{
                  height: ROW_H,
                  paddingRight: 1,
                  transform: `translateY(${localIdx * STEP}px)`,
                  transition: transitionValue,
                  opacity: dotOpacity(isActive, isItemHovered, round.isLoaded) * (hasInitialized ? fade : fade > 0 ? 1 : 0),
                }}
                onClick={() => {
                  navigate(globalIdx);
                }}
                onMouseEnter={() => {
                  cancelHide();
                  setHoveredIndex(globalIdx);
                }}
                onMouseLeave={() => setHoveredIndex(null)}
                aria-label={`Go to round ${round.roundNumber}`}
              >
                <span
                  className="rounded-full bg-foreground transition-all duration-300"
                  style={{
                    width: dotSize(isActive, isItemHovered),
                    height: dotSize(isActive, isItemHovered),
                  }}
                />
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
