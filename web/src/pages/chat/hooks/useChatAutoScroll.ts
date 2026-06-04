import { useCallback, useEffect, useLayoutEffect, useRef } from "react";

import type { ChatMessage } from "../types";

const AUTO_SCROLL_BOTTOM_THRESHOLD_PX = 96;

/**
 * Keeps the timeline pinned to the newest activity until the user intentionally scrolls up.
 * When the user sends a new message, it scrolls that message to the viewport top so
 * previous conversation stays above. The pin is held until the user manually scrolls
 * back to the bottom.
 */
export function useChatAutoScroll(messages: ChatMessage[]) {
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const previousMessageCountRef = useRef<number>(0);
  const autoScrollEnabledRef = useRef<boolean>(true);
  const lastScrollTopRef = useRef<number>(0);
  const forceAutoScrollNextRef = useRef<boolean>(false);
  const programmaticScrollUntilRef = useRef<number>(0);

  /**
   * While set, auto-scroll-to-bottom is suppressed so the user message stays pinned
   * at the viewport top. Cleared when the user manually scrolls near the bottom.
   */
  const scrolledToUserMessageRef = useRef<string | null>(null);

  /** Tracks the count of user messages to detect when a new one is sent. */
  const lastUserMessageCountRef = useRef<number>(0);

  /** Removes the extra bottom padding added by scrollToMessageTop. */
  const clearUserMessagePadding = useCallback(() => {
    const contentEl = scrollContainerRef.current?.firstElementChild
      ?.firstElementChild as HTMLElement | null;
    if (contentEl) {
      contentEl.style.paddingBottom = "";
    }
  }, []);

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
    programmaticScrollUntilRef.current = Date.now() + 450;
    scrollContainer.scrollTo({ top: targetTop, behavior });
  }, []);

  /** Scrolls so the given message element sits at the top of the viewport. */
  const scrollToMessageTop = useCallback(
    (messageId: string, behavior: ScrollBehavior) => {
      const scrollContainer = scrollContainerRef.current;
      if (!scrollContainer) {
        return;
      }

      const element = scrollContainer.querySelector(
        `[data-message-id="${messageId}"]`,
      );
      if (!element) {
        scrollToBottom(behavior);
        return;
      }

      const topGap = 16;
      const containerRect = scrollContainer.getBoundingClientRect();
      const elementRect = element.getBoundingClientRect();
      const targetTop = Math.max(
        scrollContainer.scrollTop +
          (elementRect.top - containerRect.top) -
          topGap,
        0,
      );

      // Ensure enough scroll room by adding bottom padding when the message
      // is near the end of the content and there's nothing below it yet.
      // Radix ScrollArea wraps content in a display:table div, so we target
      // firstElementChild.firstElementChild (the actual content wrapper).
      const contentEl = scrollContainer.firstElementChild
        ?.firstElementChild as HTMLElement | null;
      const maxScroll = scrollContainer.scrollHeight - scrollContainer.clientHeight;
      if (targetTop > maxScroll && contentEl) {
        contentEl.style.paddingBottom = `${targetTop - maxScroll + topGap}px`;
      }

      lastScrollTopRef.current = targetTop;
      programmaticScrollUntilRef.current = Date.now() + 450;
      scrollContainer.scrollTo({ top: targetTop, behavior });
    },
    [scrollToBottom],
  );

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

  const handleScroll = useCallback(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer) {
      return;
    }

    const currentTop = scrollContainer.scrollTop;
    if (Date.now() < programmaticScrollUntilRef.current) {
      lastScrollTopRef.current = currentTop;
      return;
    }

    const userScrolledUp = currentTop + 2 < lastScrollTopRef.current;
    const nearBottom = isNearBottom();

    if (userScrolledUp) {
      autoScrollEnabledRef.current = false;
      forceAutoScrollNextRef.current = false;
    } else if (nearBottom) {
      autoScrollEnabledRef.current = true;
      // Resume normal auto-scroll and clean up the extra padding
      if (scrolledToUserMessageRef.current) {
        scrolledToUserMessageRef.current = null;
        clearUserMessagePadding();
      }
    }

    lastScrollTopRef.current = currentTop;
  }, [isNearBottom, clearUserMessagePadding]);

  const prepareForProgrammaticScroll = useCallback(() => {
    autoScrollEnabledRef.current = true;
    forceAutoScrollNextRef.current = true;
    // Clean up any previous pin state
    scrolledToUserMessageRef.current = null;
    clearUserMessagePadding();
  }, [clearUserMessagePadding]);

  useLayoutEffect(() => {
    const forceAutoScroll = forceAutoScrollNextRef.current;
    const scrollContainer = scrollContainerRef.current;

    const currentUserMsgCount = messages.filter((m) => m.role === "user").length;
    const isNewUserMessage =
      currentUserMsgCount === lastUserMessageCountRef.current + 1;
    lastUserMessageCountRef.current = currentUserMsgCount;

    // When user sends a new message, pin it to the viewport top.
    // requestAnimationFrame ensures the DOM element is fully committed and
    // queryable — useLayoutEffect fires synchronously but Radix ScrollArea's
    // internal wrappers may not have settled yet.
    if (forceAutoScroll && isNewUserMessage) {
      const lastUserMsg = [...messages].reverse().find((m) => m.role === "user");
      if (lastUserMsg) {
        scrolledToUserMessageRef.current = lastUserMsg.id;
        forceAutoScrollNextRef.current = false;
        previousMessageCountRef.current = messages.length;

        requestAnimationFrame(() => {
          scrollToMessageTop(lastUserMsg.id, "smooth");
        });
        return;
      }
    }

    // Suppress auto-scroll while a user message is pinned to top
    if (scrolledToUserMessageRef.current) {
      previousMessageCountRef.current = messages.length;
      return;
    }

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
  }, [messages, scrollToBottom, scrollToMessageTop]);

  useEffect(() => {
    const scrollContainer = scrollContainerRef.current;
    if (!scrollContainer || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observedElement = scrollContainer.firstElementChild ?? scrollContainer;

    const observer = new ResizeObserver(() => {
      if (scrolledToUserMessageRef.current) {
        return;
      }
      if (autoScrollEnabledRef.current || forceAutoScrollNextRef.current) {
        scrollToBottom("auto");
      }
    });
    observer.observe(observedElement);
    return () => {
      observer.disconnect();
    };
  }, [scrollToBottom]);

  /** Scrolls to an arbitrary message and disables auto-scroll-to-bottom. */
  const scrollToMessage = useCallback(
    (messageId: string) => {
      autoScrollEnabledRef.current = false;
      scrolledToUserMessageRef.current = null;
      clearUserMessagePadding();
      scrollToMessageTop(messageId, "smooth");
    },
    [scrollToMessageTop, clearUserMessagePadding],
  );

  const pauseAutoScroll = useCallback(() => {
    autoScrollEnabledRef.current = false;
    forceAutoScrollNextRef.current = false;
  }, []);

  return {
    scrollContainerRef,
    handleScroll,
    prepareForProgrammaticScroll,
    scrollToMessage,
    pauseAutoScroll,
  };
}
