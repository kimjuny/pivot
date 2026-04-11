import { motion } from "motion/react";
import { useEffect, useState } from "react";

import { getThinkingEasterEggWords } from "../../../utils/easteregg";

const DEFAULT_TYPING_DELAY_MS = 75;
const DEFAULT_DELETING_DELAY_MS = 35;
const DEFAULT_HOLD_DELAY_MS = 2200;
const DEFAULT_SWITCH_DELAY_MS = 120;

type ThinkingTickerPhase = "typing" | "holding" | "deleting" | "switching";

function readThinkingWordsFromKey(wordKey: string): string[] {
  return wordKey.length > 0 ? wordKey.split("\u0000") : ["Thinking"];
}

function pickNextThinkingWord(
  words: readonly string[],
  currentWord: string | null,
): string {
  if (words.length === 0) {
    return "Thinking";
  }

  if (words.length === 1) {
    return words[0] ?? "Thinking";
  }

  let nextWord = currentWord ?? words[0] ?? "Thinking";

  while (nextWord === currentWord) {
    const nextIndex = Math.floor(Math.random() * words.length);
    nextWord = words[nextIndex] ?? "Thinking";
  }

  return nextWord;
}

function getPlaceholderThinkingWord(words: readonly string[]): string {
  if (words.length === 0) {
    return "Thinking";
  }

  return words.reduce<string>((longestWord, word) => {
    return word.length > longestWord.length ? word : longestWord;
  }, words[0] ?? "Thinking");
}

const DEFAULT_THINKING_WORDS = getThinkingEasterEggWords();

/**
 * Displays a looping typewriter ticker for the chat thinking state.
 *
 * Why: the ticker keeps long-running recursion steps feeling alive without
 * leaking placeholder implementation details like iteration numbers.
 */
export interface ThinkingWordTickerProps {
  /**
   * Optional utility classes for the ticker wrapper.
   */
  className?: string;
  /**
   * Optional override used by tests or future experiments.
   */
  words?: readonly string[];
  /**
   * Delay between typed characters.
   */
  typingDelayMs?: number;
  /**
   * Delay between deleted characters.
   */
  deletingDelayMs?: number;
  /**
   * How long a completed word stays visible before deletion starts.
   */
  holdDelayMs?: number;
  /**
   * Short gap between fully deleting one word and typing the next one.
   */
  switchDelayMs?: number;
}

/**
 * Renders a typewriter-style rotating thinking label backed by easter egg
 * phrases so active chat iterations feel playful instead of repetitive.
 */
export function ThinkingWordTicker({
  className,
  words,
  typingDelayMs = DEFAULT_TYPING_DELAY_MS,
  deletingDelayMs = DEFAULT_DELETING_DELAY_MS,
  holdDelayMs = DEFAULT_HOLD_DELAY_MS,
  switchDelayMs = DEFAULT_SWITCH_DELAY_MS,
}: ThinkingWordTickerProps) {
  const normalizedWords =
    words?.map((word) => word.trim()).filter((word) => word.length > 0) ??
    DEFAULT_THINKING_WORDS;
  const normalizedWordKey = normalizedWords.join("\u0000");
  const [activeWord, setActiveWord] = useState(() =>
    pickNextThinkingWord(readThinkingWordsFromKey(normalizedWordKey), null),
  );
  const [visibleLength, setVisibleLength] = useState(0);
  const [phase, setPhase] = useState<ThinkingTickerPhase>("typing");

  useEffect(() => {
    setActiveWord(
      pickNextThinkingWord(readThinkingWordsFromKey(normalizedWordKey), null),
    );
    setVisibleLength(0);
    setPhase("typing");
  }, [normalizedWordKey]);

  useEffect(() => {
    const timeoutDelayMs =
      phase === "typing"
        ? typingDelayMs
        : phase === "holding"
          ? holdDelayMs
          : phase === "deleting"
            ? deletingDelayMs
            : switchDelayMs;

    const timeoutId = window.setTimeout(() => {
      if (phase === "typing") {
        if (visibleLength < activeWord.length) {
          const nextVisibleLength = visibleLength + 1;

          setVisibleLength(nextVisibleLength);
          if (nextVisibleLength >= activeWord.length) {
            setPhase("holding");
          }
          return;
        }

        setPhase("holding");
        return;
      }

      if (phase === "holding") {
        setPhase("deleting");
        return;
      }

      if (phase === "deleting") {
        if (visibleLength > 0) {
          const nextVisibleLength = visibleLength - 1;

          setVisibleLength(nextVisibleLength);
          if (nextVisibleLength <= 0) {
            setPhase("switching");
          }
          return;
        }

        setPhase("switching");
        return;
      }

      setActiveWord((currentWord) =>
        pickNextThinkingWord(
          readThinkingWordsFromKey(normalizedWordKey),
          currentWord,
        ),
      );
      setPhase("typing");
    }, timeoutDelayMs);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [
    activeWord,
    deletingDelayMs,
    holdDelayMs,
    normalizedWordKey,
    phase,
    switchDelayMs,
    typingDelayMs,
    visibleLength,
  ]);

  const visibleWord = activeWord.slice(0, visibleLength);
  const placeholderWord = getPlaceholderThinkingWord(normalizedWords);

  return (
    <span
      className={className}
      data-testid="thinking-word-ticker"
      title={activeWord}
    >
      <span className="sr-only">Thinking</span>
      <span
        aria-hidden="true"
        className="inline-grid items-center justify-items-start"
      >
        <span
          className="invisible col-start-1 row-start-1 inline-flex items-center gap-0.5 whitespace-nowrap"
          data-testid="thinking-word-ticker-placeholder"
        >
          <span>{placeholderWord}</span>
          <span className="inline-block h-3.5 w-px rounded-full" />
        </span>
        <span className="col-start-1 row-start-1 inline-flex items-center gap-0.5 whitespace-nowrap">
          <span data-testid="thinking-word-ticker-text">{visibleWord}</span>
          <motion.span
            animate={{ opacity: [0.25, 1, 0.25] }}
            aria-hidden="true"
            className="inline-block h-3.5 w-px rounded-full bg-current"
            data-testid="thinking-word-ticker-cursor"
            transition={{
              duration: 0.9,
              ease: "easeInOut",
              repeat: Number.POSITIVE_INFINITY,
            }}
          />
        </span>
      </span>
    </span>
  );
}
