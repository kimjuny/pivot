import { useCallback, useEffect, useRef, useState } from "react";

interface UseScrollUpPaginationOptions {
  scrollContainerRef: React.RefObject<HTMLElement | null>;
  messages: unknown[];
  hasMoreOlderRef: React.RefObject<boolean>;
  isLoadingOlderRef: React.RefObject<boolean>;
  loadOlderTasks: (limit: number) => Promise<void>;
  batchSize?: number;
}

/**
 * Triggers pre-loading of older tasks when the user scrolls up and the
 * 5th user message from the top enters the viewport.
 *
 * Uses IntersectionObserver on the 5th user message element (located via
 * `data-role="user"`). When it intersects the scroll container, calls
 * `loadOlderTasks(batchSize)` while respecting the `isLoadingOlder` lock.
 *
 * After a successful load, the observer is disconnected and reconnected on
 * the new 5th element so it tracks the updated DOM.
 */
export function useScrollUpPagination({
  scrollContainerRef,
  messages,
  hasMoreOlderRef,
  isLoadingOlderRef,
  loadOlderTasks,
  batchSize = 10,
}: UseScrollUpPaginationOptions) {
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const triggeredRef = useRef(false);

  // Re-observe the 5th user message whenever messages change.
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    // Disconnect previous observer.
    observerRef.current?.disconnect();

    // Only observe if there could be more data above.
    if (!hasMoreOlderRef.current) return;

    const userMessages = container.querySelectorAll('[data-role="user"]');
    if (userMessages.length < 5) return;

    const sentinel = userMessages[4]; // 5th user message (0-indexed)

    triggeredRef.current = false;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (
          entry.isIntersecting &&
          !triggeredRef.current &&
          !isLoadingOlderRef.current &&
          hasMoreOlderRef.current
        ) {
          triggeredRef.current = true;
          setIsLoadingOlder(true);
          void loadOlderTasks(batchSize).finally(() => {
            setIsLoadingOlder(false);
            triggeredRef.current = false;
          });
        }
      },
      { root: container, threshold: 0 },
    );

    observer.observe(sentinel);
    observerRef.current = observer;

    return () => observer.disconnect();
  }, [
    scrollContainerRef,
    messages,
    hasMoreOlderRef,
    isLoadingOlderRef,
    loadOlderTasks,
    batchSize,
  ]);

  /** Loads batches until the target task ID is found or no more history. */
  const loadUntilTask = useCallback(
    async (targetTaskId: string): Promise<boolean> => {
      let found = false;
      const maxBatches = 20; // Safety limit

      for (let i = 0; i < maxBatches; i++) {
        if (isLoadingOlderRef.current || !hasMoreOlderRef.current) break;

        setIsLoadingOlder(true);
        await loadOlderTasks(batchSize);
        setIsLoadingOlder(false);

        // loadOlderTasks updates loadedTaskIds in the parent.
        // We check via the DOM — if the target user message element exists,
        // the task is loaded.
        const container = scrollContainerRef.current;
        if (container) {
          const el = container.querySelector(
            `[data-message-id="user-${targetTaskId}"]`,
          );
          if (el) {
            found = true;
            break;
          }
        }
      }

      return found;
    },
    [scrollContainerRef, isLoadingOlderRef, hasMoreOlderRef, loadOlderTasks, batchSize],
  );

  return { isLoadingOlder, loadUntilTask };
}
