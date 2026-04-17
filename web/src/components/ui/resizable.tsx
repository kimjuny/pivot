import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type HTMLAttributes,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import { GripVertical } from "lucide-react";

import { cn } from "@/lib/utils";

type ResizableDirection = "horizontal" | "vertical";

interface ResizablePanelGroupProps {
  children: ReactNode;
  className?: string;
  direction: ResizableDirection;
  onLayout?: (sizes: number[]) => void;
}

interface ResizablePanelProps {
  children: ReactNode;
  className?: string;
  defaultSize?: number;
  minSize?: number;
  minSizePx?: number;
  maxSize?: number;
  size?: number;
}

interface ResizableHandleProps extends HTMLAttributes<HTMLDivElement> {
  withHandle?: boolean;
}

interface PanelConfig {
  controlledSize?: number;
  defaultSize: number;
  minSize: number;
  minSizePx?: number;
  maxSize: number;
}

interface DragState {
  containerSize: number;
  handleIndex: number;
  handleElement: HTMLDivElement;
  pointerId: number;
  startPosition: number;
  startSizes: number[];
}

interface InternalPanelProps {
  panelSize?: number;
}

interface InternalHandleProps {
  direction?: ResizableDirection;
  onResizeStart?: (event: ReactPointerEvent<HTMLDivElement>) => void;
}

const INTERNAL_PANEL_KEY = Symbol("pivot-resizable-panel");
const INTERNAL_HANDLE_KEY = Symbol("pivot-resizable-handle");

const ResizablePanelGroup = ({
  children,
  className,
  direction,
  onLayout,
}: ResizablePanelGroupProps) => {
  const groupRef = useRef<HTMLDivElement | null>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const panelConfigsRef = useRef<PanelConfig[]>([]);
  const resolvedPanelSizesRef = useRef<number[]>([]);
  const onLayoutRef = useRef<((sizes: number[]) => void) | undefined>(undefined);
  const childArray = useMemo(() => Children.toArray(children), [children]);
  const [isResizing, setIsResizing] = useState(false);

  const panelConfigs = useMemo(() => {
    const panelElements = childArray.filter(isResizablePanelElement);
    if (panelElements.length === 0) {
      return [];
    }

    const explicitTotal = panelElements.reduce((total, element) => {
      const nextSize = element.props.defaultSize;
      return typeof nextSize === "number" && Number.isFinite(nextSize)
        ? total + nextSize
        : total;
    }, 0);
    const panelsWithoutDefault = panelElements.filter(
      (element) =>
        typeof element.props.defaultSize !== "number" ||
        !Number.isFinite(element.props.defaultSize),
    ).length;
    const fallbackDefault =
      panelsWithoutDefault > 0
        ? Math.max((100 - explicitTotal) / panelsWithoutDefault, 0)
        : 100 / panelElements.length;

    return panelElements.map((element) => ({
      controlledSize:
        typeof element.props.size === "number" &&
        Number.isFinite(element.props.size)
          ? element.props.size
          : undefined,
      defaultSize:
        typeof element.props.size === "number" &&
        Number.isFinite(element.props.size)
          ? element.props.size
          : typeof element.props.defaultSize === "number" &&
              Number.isFinite(element.props.defaultSize)
            ? element.props.defaultSize
            : fallbackDefault,
      minSize:
        typeof element.props.minSize === "number" &&
        Number.isFinite(element.props.minSize)
          ? element.props.minSize
          : 16,
      minSizePx:
        typeof element.props.minSizePx === "number" &&
        Number.isFinite(element.props.minSizePx) &&
        element.props.minSizePx > 0
          ? element.props.minSizePx
          : undefined,
      maxSize:
        typeof element.props.maxSize === "number" &&
        Number.isFinite(element.props.maxSize)
          ? element.props.maxSize
          : 84,
    }));
  }, [childArray]);

  const normalizedDefaults = useMemo(
    () => normalizePanelSizes(panelConfigs.map((panel) => panel.defaultSize)),
    [panelConfigs],
  );
  const [panelSizes, setPanelSizes] = useState<number[]>(normalizedDefaults);
  const resolvedPanelSizes = useMemo(() => {
    const controlledSizes = panelConfigs.map((panel) => panel.controlledSize);
    if (controlledSizes.every((size) => typeof size === "number")) {
      return normalizePanelSizes(controlledSizes);
    }
    return panelSizes;
  }, [panelConfigs, panelSizes]);

  useEffect(() => {
    panelConfigsRef.current = panelConfigs;
  }, [panelConfigs]);

  useEffect(() => {
    resolvedPanelSizesRef.current = resolvedPanelSizes;
  }, [resolvedPanelSizes]);

  useEffect(() => {
    onLayoutRef.current = onLayout;
  }, [onLayout]);

  useEffect(() => {
    setPanelSizes((previous) => {
      if (
        previous.length === normalizedDefaults.length &&
        previous.every((size, index) => size === normalizedDefaults[index])
      ) {
        return previous;
      }
      return normalizedDefaults;
    });
  }, [normalizedDefaults]);

  useEffect(() => {
    const stopDragging = () => {
      const dragState = dragStateRef.current;
      if (
        dragState &&
        dragState.handleElement.hasPointerCapture(dragState.pointerId)
      ) {
        dragState.handleElement.releasePointerCapture(dragState.pointerId);
      }

      dragStateRef.current = null;
      setIsResizing(false);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };

    const handlePointerMove = (event: PointerEvent) => {
      const dragState = dragStateRef.current;
      if (!dragState || event.pointerId !== dragState.pointerId) {
        return;
      }
      if (event.buttons === 0) {
        stopDragging();
        return;
      }

      const nextPosition =
        direction === "vertical" ? event.clientY : event.clientX;
      const deltaPercent =
        ((nextPosition - dragState.startPosition) / dragState.containerSize) *
        100;
      const leftConfig = panelConfigsRef.current[dragState.handleIndex];
      const rightConfig = panelConfigsRef.current[dragState.handleIndex + 1];
      if (!leftConfig || !rightConfig) {
        stopDragging();
        return;
      }

      const leftStart =
        dragState.startSizes[dragState.handleIndex] ?? leftConfig.defaultSize;
      const rightStart =
        dragState.startSizes[dragState.handleIndex + 1] ??
        rightConfig.defaultSize;
      const total = leftStart + rightStart;
      const leftMinSize = Math.max(
        leftConfig.minSize,
        toPercentSize(leftConfig.minSizePx, dragState.containerSize),
      );
      const rightMinSize = Math.max(
        rightConfig.minSize,
        toPercentSize(rightConfig.minSizePx, dragState.containerSize),
      );
      const nextLeft = clampNumber(
        leftStart + deltaPercent,
        Math.max(leftMinSize, total - rightConfig.maxSize),
        Math.min(leftConfig.maxSize, total - rightMinSize),
      );
      const nextRight = total - nextLeft;

      const nextSizes = resolvedPanelSizesRef.current.map((size, index) => {
          if (index === dragState.handleIndex) {
            return nextLeft;
          }
          if (index === dragState.handleIndex + 1) {
            return nextRight;
          }
          return size;
        });
      setPanelSizes(nextSizes);
      onLayoutRef.current?.(nextSizes);
    };

    const handlePointerStop = (event?: PointerEvent) => {
      if (
        event &&
        dragStateRef.current &&
        event.pointerId !== dragStateRef.current.pointerId
      ) {
        return;
      }
      stopDragging();
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerStop);
    window.addEventListener("pointercancel", handlePointerStop);
    window.addEventListener("blur", () => handlePointerStop());
    document.addEventListener("visibilitychange", () => handlePointerStop());

    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerStop);
      window.removeEventListener("pointercancel", handlePointerStop);
      stopDragging();
    };
  }, [direction]);

  let panelIndex = 0;
  let handleIndex = 0;

  return (
    <div
      ref={groupRef}
      data-panel-group-direction={direction}
      data-resizing={isResizing ? "true" : "false"}
      className={cn(
        "group/panel-group flex h-full w-full overflow-hidden data-[panel-group-direction=vertical]:flex-col",
        className,
      )}
    >
      {childArray.map((child, childIndex) => {
        if (!isValidElement(child)) {
          return child;
        }

        if (isResizablePanelElement(child)) {
          const nextChild = cloneElement(
            child as ReactElement<ResizablePanelProps & InternalPanelProps>,
            {
              panelSize:
                resolvedPanelSizes[panelIndex] ??
                normalizedDefaults[panelIndex] ??
                50,
            },
          );
          panelIndex += 1;
          return cloneElement(nextChild, { key: child.key ?? childIndex });
        }

        if (isResizableHandleElement(child)) {
          const nextHandleIndex = handleIndex;
          const nextChild = cloneElement(
            child as ReactElement<ResizableHandleProps & InternalHandleProps>,
            {
              direction,
              onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => {
                const container = groupRef.current;
                if (!container) {
                  return;
                }

                const containerRect = container.getBoundingClientRect();
                const containerSize =
                  direction === "vertical"
                    ? containerRect.height
                    : containerRect.width;
                if (containerSize <= 0) {
                  return;
                }

                dragStateRef.current = {
                  containerSize,
                  handleIndex: nextHandleIndex,
                  handleElement: event.currentTarget,
                  pointerId: event.pointerId,
                  startPosition:
                    direction === "vertical" ? event.clientY : event.clientX,
                  startSizes: [...resolvedPanelSizes],
                };
                setIsResizing(true);
                event.currentTarget.setPointerCapture(event.pointerId);
                document.body.style.cursor =
                  direction === "vertical" ? "row-resize" : "col-resize";
                document.body.style.userSelect = "none";
                event.preventDefault();
              },
            },
          );
          handleIndex += 1;
          return cloneElement(nextChild, { key: child.key ?? childIndex });
        }

        return child;
      })}
    </div>
  );
};

const ResizablePanel = ({
  children,
  className,
  minSizePx,
  panelSize,
}: ResizablePanelProps & InternalPanelProps) => (
  <div
    data-resizable-panel=""
    className={cn(
      "flex min-h-0 min-w-0 shrink-0 grow-0 overflow-hidden transition-[flex-basis] duration-200 ease-out group-data-[resizing=true]/panel-group:transition-none",
      className,
    )}
    style={{
      flexBasis: `${panelSize ?? 50}%`,
      minWidth: typeof minSizePx === "number" ? `${minSizePx}px` : undefined,
    }}
  >
    {children}
  </div>
);

ResizablePanel.displayName = "ResizablePanel";
(ResizablePanel as typeof ResizablePanel & { [INTERNAL_PANEL_KEY]: true })[
  INTERNAL_PANEL_KEY
] = true;

const ResizableHandle = ({
  withHandle,
  className,
  direction = "horizontal",
  onResizeStart,
  ...props
}: ResizableHandleProps & InternalHandleProps) => {
  const isVertical = direction === "vertical";

  return (
    <div
      role="separator"
      aria-orientation={direction}
      className={cn(
        "relative flex shrink-0 items-center justify-center bg-border/80 transition-colors",
        isVertical ? "h-px w-full" : "w-px",
        className,
      )}
      onPointerDown={onResizeStart}
      {...props}
    >
      <div
        className={cn(
          "absolute touch-none",
          isVertical
            ? "inset-x-0 top-1/2 h-4 -translate-y-1/2 cursor-row-resize"
            : "inset-y-0 left-1/2 w-4 -translate-x-1/2 cursor-col-resize",
        )}
      />
      {withHandle ? (
        <div
          className={cn(
            "z-10 flex items-center justify-center rounded-sm border bg-border",
            isVertical ? "h-3 w-4 [&>svg]:rotate-90" : "h-4 w-3",
          )}
        >
          <GripVertical className="h-2.5 w-2.5" />
        </div>
      ) : null}
    </div>
  );
};

ResizableHandle.displayName = "ResizableHandle";
(ResizableHandle as typeof ResizableHandle & { [INTERNAL_HANDLE_KEY]: true })[
  INTERNAL_HANDLE_KEY
] = true;

function isResizablePanelElement(
  child: ReactNode,
): child is ReactElement<ResizablePanelProps> {
  return (
    isValidElement(child) &&
    Boolean(
      (
        child.type as { [INTERNAL_PANEL_KEY]?: boolean } | undefined
      )?.[INTERNAL_PANEL_KEY],
    )
  );
}

function isResizableHandleElement(
  child: ReactNode,
): child is ReactElement<ResizableHandleProps> {
  return (
    isValidElement(child) &&
    Boolean(
      (
        child.type as { [INTERNAL_HANDLE_KEY]?: boolean } | undefined
      )?.[INTERNAL_HANDLE_KEY],
    )
  );
}

function normalizePanelSizes(sizes: number[]): number[] {
  if (sizes.length === 0) {
    return [];
  }

  const total = sizes.reduce((sum, size) => sum + size, 0);
  if (total <= 0) {
    return sizes.map(() => 100 / sizes.length);
  }

  return sizes.map((size) => (size / total) * 100);
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function toPercentSize(
  pixelSize: number | undefined,
  containerSize: number,
): number {
  if (
    typeof pixelSize !== "number" ||
    !Number.isFinite(pixelSize) ||
    pixelSize <= 0 ||
    containerSize <= 0
  ) {
    return 0;
  }
  return (pixelSize / containerSize) * 100;
}

export { ResizablePanelGroup, ResizablePanel, ResizableHandle };
