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

interface RoundAnchorProps {
  rounds: ConversationRound[];
  onNavigateToRound: (messageId: string) => void;
  scrollContainerRef: RefObject<HTMLElement | null>;
}

/** Maximum visible anchor items at once. */
const WINDOW_SIZE = 5;
/** Each row height in px — matches sidebar list-item density. */
const ROW_H = 28;
/** Gap between rows — visual separation between items. */
const ROW_GAP = 4;
/** Card fixed width — wide enough for ~15 CJK characters at text-xs. */
const CARD_W = 168;
/** Card inner padding. */
const PAD = 8;
/** Container paddingRight — controls distance from screen right edge to dots. */
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
  const [activeIndex, setActiveIndex] = useState(0);
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

/**
 * Compact anchor dots on the right edge of the chat pane with a sliding
 * window of at most WINDOW_SIZE items. Clicking the topmost visible item
 * shifts the window up so it lands at position 3; clicking the bottommost
 * shifts it down so it lands at position 1.
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
  const containerRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<number | null>(null);
  const activeIndex = useActiveRoundIndex(rounds, scrollContainerRef);
  const pagingTargetRef = useRef<number | null>(null);
  const pendingNavRef = useRef<number | null>(null);

  // Cleanup pending navigation timeout on unmount.
  useEffect(() => {
    return () => {
      if (pendingNavRef.current !== null) {
        clearTimeout(pendingNavRef.current);
      }
    };
  }, []);

  // Auto-follow: keep active item inside the visible window.
  // Suppressed while a page navigation is in progress.
  useEffect(() => {
    if (pagingTargetRef.current !== null) return;
    setWindowStart((prev) => {
      const clamped = clampStart(prev, total);
      if (activeIndex < clamped) return clampStart(activeIndex, total);
      if (activeIndex >= clamped + WINDOW_SIZE) {
        return clampStart(activeIndex - WINDOW_SIZE + 1, total);
      }
      return clamped;
    });
  }, [activeIndex, total]);

  const windowRounds = useMemo(
    () => rounds.slice(windowStart, windowStart + WINDOW_SIZE),
    [rounds, windowStart],
  );
  const hasMoreAbove = windowStart > 0;
  const hasMoreBelow = windowStart + WINDOW_SIZE < total;

  const navigate = useCallback(
    (globalIndex: number) => {
      const localIndex = globalIndex - windowStart;
      const maxLocal = windowRounds.length - 1;
      const isPageUp = localIndex === 0 && hasMoreAbove;
      const isPageDown = localIndex === maxLocal && hasMoreBelow;

      if (isPageUp) {
        // Shift up: clicked item moves to position 3.
        const shift = Math.min(3, globalIndex);
        setWindowStart(clampStart(globalIndex - shift, total));
      } else if (isPageDown) {
        // Shift down: clicked item moves to position 1.
        setWindowStart(clampStart(globalIndex - 1, total));
      }

      if (isPageUp || isPageDown) {
        // Lock auto-follow, delay scroll so the anchor window settles first.
        pagingTargetRef.current = globalIndex;
        if (pendingNavRef.current !== null) {
          clearTimeout(pendingNavRef.current);
        }
        pendingNavRef.current = window.setTimeout(() => {
          pendingNavRef.current = null;
          onNavigateToRound(rounds[globalIndex].userMessageId);
        }, 200);
      } else {
        onNavigateToRound(rounds[globalIndex].userMessageId);
      }
    },
    [windowStart, windowRounds.length, hasMoreAbove, hasMoreBelow, rounds, total, onNavigateToRound],
  );

  // Release paging lock once scroll reaches the target.
  useEffect(() => {
    if (
      pagingTargetRef.current !== null &&
      activeIndex === pagingTargetRef.current
    ) {
      pagingTargetRef.current = null;
    }
  }, [activeIndex]);

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
            <div className="flex flex-col" style={{ gap: ROW_GAP }}>
              {windowRounds.map((round, localIdx) => {
                const globalIdx = windowStart + localIdx;
                const isItemHovered = hoveredIndex === globalIdx;

                return (
                  <button
                    key={round.taskId}
                    type="button"
                    className={`flex w-full items-center rounded-lg transition-colors ${
                      isItemHovered ? "bg-accent" : ""
                    }`}
                    style={{ height: ROW_H, paddingLeft: 4, paddingRight: 4 }}
                    onClick={() => {
                      navigate(globalIdx);
                    }}
                    onMouseEnter={() => {
                      cancelHide();
                      setHoveredIndex(globalIdx);
                    }}
                    onMouseLeave={() => setHoveredIndex(null)}
                  >
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
                  </button>
                );
              })}
            </div>
          </Card>
        )}

        {/* Dots — always visible, positioned to the right of the card */}
        <div className="flex flex-col items-end" style={{ gap: ROW_GAP }}>
          {/* "More above" indicator — always rendered to keep layout stable. */}
          <span
            className={`block h-2 w-1 rounded-full transition-opacity ${hasMoreAbove ? "bg-foreground/20 opacity-100" : "opacity-0"}`}
          />

          {windowRounds.map((round, localIdx) => {
            const globalIdx = windowStart + localIdx;
            const isActive = globalIdx === activeIndex;
            const isItemHovered = hoveredIndex === globalIdx;

            return (
              <button
                key={round.taskId}
                type="button"
                style={{
                  height: ROW_H,
                  width: 24,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  paddingRight: 1,
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
                  className="rounded-full bg-foreground transition-all"
                  style={{
                    width: isActive ? 6 : 4,
                    height: isActive ? 6 : 4,
                    opacity: isActive ? 0.5 : isItemHovered ? 0.4 : 0.2,
                  }}
                />
              </button>
            );
          })}

          {/* "More below" indicator — always rendered to keep layout stable. */}
          <span
            className={`block h-2 w-1 rounded-full transition-opacity ${hasMoreBelow ? "bg-foreground/20 opacity-100" : "opacity-0"}`}
          />
        </div>
      </div>
    </div>
  );
}
