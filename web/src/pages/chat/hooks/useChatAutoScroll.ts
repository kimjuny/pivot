import { useCallback, useEffect, useRef } from "react";

import type { ChatMessage } from "../types";

const AUTO_SCROLL_BOTTOM_THRESHOLD_PX = 96;

/**
 * Keeps the timeline pinned to the newest activity until the user intentionally scrolls up.
 */
export function useChatAutoScroll(messages: ChatMessage[]) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const previousMessageCountRef = useRef<number>(0);
  const autoScrollEnabledRef = useRef<boolean>(true);
  const lastScrollTopRef = useRef<number>(0);
  const forceAutoScrollNextRef = useRef<boolean>(false);

  /**
   * Scrolls the message viewport to the latest content while preserving a small bottom gap.
   */
  const scrollToBottom = useCallback((behavior: ScrollBehavior) => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) {
      return;
    }

    const bottomGap = 20;
    const targetTop = Math.max(
      scrollContainer.scrollHeight - scrollContainer.clientHeight - bottomGap,
      0,
    );
    lastScrollTopRef.current = targetTop;
    scrollContainer.scrollTo({ top: targetTop, behavior });
  }, []);

  /**
   * Detects whether the user is already close enough to the latest content.
   */
  const isNearBottom = useCallback((): boolean => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) {
      return true;
    }

    const distanceToBottom =
      scrollContainer.scrollHeight -
      scrollContainer.scrollTop -
      scrollContainer.clientHeight;
    return distanceToBottom <= AUTO_SCROLL_BOTTOM_THRESHOLD_PX;
  }, []);

  /**
   * Records manual upward scrolling so streaming updates do not yank the viewport.
   */
  const handleScroll = useCallback(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) {
      return;
    }

    const currentTop = scrollContainer.scrollTop;
    const userScrolledUp = currentTop + 2 < lastScrollTopRef.current;
    const nearBottom = isNearBottom();

    if (userScrolledUp) {
      autoScrollEnabledRef.current = false;
      forceAutoScrollNextRef.current = false;
    } else if (nearBottom) {
      autoScrollEnabledRef.current = true;
    }

    lastScrollTopRef.current = currentTop;
  }, [isNearBottom]);

  /**
   * Re-enables follow mode before programmatic timeline changes like session switches or sends.
   */
  const prepareForProgrammaticScroll = useCallback(() => {
    autoScrollEnabledRef.current = true;
    forceAutoScrollNextRef.current = true;
  }, []);

  useEffect(() => {
    const forceAutoScroll = forceAutoScrollNextRef.current;
    const scrollContainer = scrollContainerRef.current;

    if (scrollContainer && !forceAutoScroll) {
      const distanceToBottom =
        scrollContainer.scrollHeight -
        scrollContainer.scrollTop -
        scrollContainer.clientHeight;

      if (distanceToBottom > AUTO_SCROLL_BOTTOM_THRESHOLD_PX) {
        autoScrollEnabledRef.current = false;
      }
    }

    if (!autoScrollEnabledRef.current && !forceAutoScroll) {
      previousMessageCountRef.current = messages.length;
      return;
    }

    const behavior: ScrollBehavior =
      messages.length > previousMessageCountRef.current ? "smooth" : "auto";
    scrollToBottom(behavior);
    forceAutoScrollNextRef.current = false;
    previousMessageCountRef.current = messages.length;
  }, [messages, scrollToBottom]);

  return {
    scrollContainerRef,
    handleScroll,
    prepareForProgrammaticScroll,
  };
}
