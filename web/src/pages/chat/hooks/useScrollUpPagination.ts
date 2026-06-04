import { useCallback, useEffect, useRef, useState } from "react";

interface UseScrollUpPaginationOptions {
  scrollContainerRef: React.RefObject<HTMLElement | null>;
  messages: unknown[];
  canLoadOlder: () => boolean;
  isOlderLoading: () => boolean;
  loadOlderTasks: (
    limit: number,
    options?: { preserveScroll?: boolean },
  ) => Promise<string[]>;
  isTaskLoaded: (taskId: string) => boolean;
  batchSize?: number;
}

/**
 * Preloads older tasks when the top of the rendered timeline approaches the
 * viewport. The hook only decides when to ask for more data; the parent owns
 * the scroll-position preservation.
 */
export function useScrollUpPagination({
  scrollContainerRef,
  messages,
  canLoadOlder,
  isOlderLoading,
  loadOlderTasks,
  isTaskLoaded,
  batchSize = 10,
}: UseScrollUpPaginationOptions) {
  const [isLoadingOlder, setIsLoadingOlder] = useState(false);
  const observerRef = useRef<IntersectionObserver | null>(null);
  const triggeredRef = useRef(false);

  // Re-observe the first rendered message whenever the loaded window changes.
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || typeof IntersectionObserver === "undefined") return;

    observerRef.current?.disconnect();

    if (!canLoadOlder()) return;

    const sentinel = container.querySelector("[data-message-id]");
    if (!sentinel) return;

    triggeredRef.current = false;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (
          entry.isIntersecting &&
          !triggeredRef.current &&
          !isOlderLoading() &&
          canLoadOlder()
        ) {
          triggeredRef.current = true;
          setIsLoadingOlder(true);
          void loadOlderTasks(batchSize).finally(() => {
            setIsLoadingOlder(false);
            triggeredRef.current = false;
          });
        }
      },
      { root: container, rootMargin: "480px 0px 0px 0px", threshold: 0 },
    );

    observer.observe(sentinel);
    observerRef.current = observer;

    return () => observer.disconnect();
  }, [
    scrollContainerRef,
    messages,
    canLoadOlder,
    isOlderLoading,
    loadOlderTasks,
    batchSize,
  ]);

  /** Loads batches until the target task ID is found or no more history. */
  const loadUntilTask = useCallback(
    async (targetTaskId: string): Promise<boolean> => {
      const maxBatches = 20; // Safety limit

      if (isTaskLoaded(targetTaskId)) {
        return true;
      }

      for (let i = 0; i < maxBatches; i++) {
        if (isOlderLoading() || !canLoadOlder()) break;

        setIsLoadingOlder(true);
        const loadedTaskIds = await loadOlderTasks(batchSize, {
          preserveScroll: false,
        });
        setIsLoadingOlder(false);

        if (loadedTaskIds.includes(targetTaskId) || isTaskLoaded(targetTaskId)) {
          return true;
        }
      }

      return false;
    },
    [isTaskLoaded, isOlderLoading, canLoadOlder, loadOlderTasks, batchSize],
  );

  return { isLoadingOlder, loadUntilTask };
}
