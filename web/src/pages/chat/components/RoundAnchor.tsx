import { useCallback, useRef, useState } from "react";

import type { ConversationRound } from "../hooks/useConversationRounds";
import { Card } from "@/components/ui/card";

interface RoundAnchorProps {
  rounds: ConversationRound[];
  onNavigateToRound: (messageId: string) => void;
}

/** Each row height in px — matches sidebar list-item density. */
const ROW_H = 28;
/** Gap between rows — gives visual separation like sidebar gap-1. */
const ROW_GAP = 4;
/** Card fixed width — wide enough for ~15 CJK characters at text-xs. */
const CARD_W = 168;
/** Card inner padding / item left padding. */
const PAD = 8;
/** Container paddingRight — controls distance from screen right edge to dots. */
const DOT_OFFSET = 25;

/**
 * Compact anchor dots on the right edge of the chat pane.
 * The same dots are always visible. Hovering reveals a Card background
 * and text labels — the dots never move or re-render.
 */
export function RoundAnchor({ rounds, onNavigateToRound }: RoundAnchorProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<number | null>(null);
  const lastIndex = rounds.length - 1;

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
        {isExpanded && (
          <Card
            className="animate-in fade-in-0 absolute border-border/50 bg-popover/95 shadow-md backdrop-blur-sm"
            style={{
              width: CARD_W,
              padding: PAD,
              right: DOT_OFFSET - PAD,
              top: -PAD,
            }}
          >
            <div className="flex flex-col" style={{ gap: ROW_GAP }}>
              {rounds.map((_, i) => (
                <div key={i} style={{ height: ROW_H }} />
              ))}
            </div>
          </Card>
        )}

        {/* The only set of dots — always rendered */}
        <div className="relative flex flex-col" style={{ gap: ROW_GAP }}>
          {rounds.map((round, index) => {
            const isItemHovered = hoveredIndex === index;
            const isLastRound = index === lastIndex;

            return (
              <button
                key={round.taskId}
                type="button"
                className={`relative flex items-center transition-colors ${
                  isExpanded ? "rounded-lg" : ""
                } ${isExpanded && isItemHovered ? "bg-accent" : ""}`}
                style={{
                  height: ROW_H,
                  width: isExpanded ? CARD_W - PAD * 2 : "auto",
                  paddingLeft: isExpanded ? PAD : 0,
                  justifyContent: isExpanded ? undefined : "flex-end",
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
                {isExpanded && (
                  <span
                    className={`min-w-0 flex-1 truncate text-left text-xs ${
                      isItemHovered
                        ? "text-accent-foreground"
                        : isLastRound
                          ? "font-medium text-popover-foreground"
                          : "text-muted-foreground"
                    }`}
                  >
                    {round.preview}
                  </span>
                )}

                <span
                  className={`shrink-0 rounded-full transition-colors ${
                    isLastRound
                      ? "bg-foreground"
                      : isItemHovered
                        ? "bg-foreground/70"
                        : "bg-muted-foreground/60"
                  }`}
                  style={{
                    width: isLastRound ? 6 : 5,
                    height: isLastRound ? 6 : 5,
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
