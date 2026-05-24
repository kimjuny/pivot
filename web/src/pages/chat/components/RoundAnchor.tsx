import {
  useCallback,
  useEffect,
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

/**
 * Compact anchor dots on the right edge of the chat pane.
 * Dots are always visible outside the card. Hovering reveals a Card with
 * text labels to the left of the dots. The active dot tracks scroll position.
 */
export function RoundAnchor({
  rounds,
  onNavigateToRound,
  scrollContainerRef,
}: RoundAnchorProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<number | null>(null);
  const lastIndex = rounds.length - 1;
  const activeIndex = useActiveRoundIndex(rounds, scrollContainerRef);

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

  if (rounds.length < 2) return null;

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
              {rounds.map((round, index) => {
                const isItemHovered = hoveredIndex === index;

                return (
                  <button
                    key={round.taskId}
                    type="button"
                    className={`flex w-full items-center rounded-lg transition-colors ${
                      isItemHovered ? "bg-accent" : ""
                    }`}
                    style={{ height: ROW_H, paddingLeft: 4, paddingRight: 4 }}
                    onClick={() => {
                      onNavigateToRound(round.userMessageId);
                    }}
                    onMouseEnter={() => {
                      cancelHide();
                      setHoveredIndex(index);
                    }}
                    onMouseLeave={() => setHoveredIndex(null)}
                  >
                    <span
                      className={`min-w-0 flex-1 truncate text-left text-xs ${
                        isItemHovered
                          ? "text-accent-foreground"
                          : index === activeIndex
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
        <div className="flex flex-col" style={{ gap: ROW_GAP }}>
          {rounds.map((round, index) => {
            const isActive = index === activeIndex;
            const isItemHovered = hoveredIndex === index;

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
                  onNavigateToRound(round.userMessageId);
                }}
                onMouseEnter={() => {
                  cancelHide();
                  setHoveredIndex(index);
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
        </div>
      </div>
    </div>
  );
}
