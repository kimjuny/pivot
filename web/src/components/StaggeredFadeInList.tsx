import { useMemo, type CSSProperties, type ReactNode } from "react";

import { cn } from "@/lib/utils";

type StaggeredItemKey = string | number;

type StaggeredItemStyle = CSSProperties & {
  "--stagger-index": number;
};

interface StaggeredFadeInListProps<T> {
  items: T[];
  getItemKey: (item: T) => StaggeredItemKey;
  className: string;
  itemClassName?: string;
  renderItem: (item: T, index: number) => ReactNode;
}

/**
 * Shared card-list wrapper for staggered fade-in entry.
 * Remounts the visible page slice when the item set changes so all list pages
 * stay aligned on the same animation behavior and timing.
 */
function StaggeredFadeInList<T>({
  items,
  getItemKey,
  className,
  itemClassName,
  renderItem,
}: StaggeredFadeInListProps<T>) {
  const listAnimationKey = useMemo(
    () => items.map((item) => String(getItemKey(item))).join("|"),
    [getItemKey, items],
  );

  return (
    <div className={className}>
      {items.map((item, index) => {
        const itemKey = String(getItemKey(item));
        const itemStyle: StaggeredItemStyle = {
          "--stagger-index": index,
        };

        return (
          <div
            key={`${listAnimationKey}-${itemKey}`}
            className={cn("staggered-fade-in-card", itemClassName)}
            style={itemStyle}
          >
            {renderItem(item, index)}
          </div>
        );
      })}
    </div>
  );
}

export default StaggeredFadeInList;
