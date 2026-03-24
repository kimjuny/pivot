import {
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Expand, Minimize2, X } from "@/lib/lucide";
import { cn } from "@/lib/utils";

/**
 * Dialog size preset.
 */
type DialogSize = "default" | "large";

interface DialogPosition {
  x: number;
  y: number;
}

interface DialogDimensions {
  width: number;
  height: number;
  minWidth: number;
  minHeight: number;
}

/**
 * Dialogs are rendered without a modal backdrop, so we need explicit stacking
 * management to mimic desktop-window behavior.
 */
const BASE_DIALOG_Z_INDEX = 50;
const DIALOG_HEADER_HEIGHT = 40;
const FULLSCREEN_TRANSITION_MS = 200;
let topDialogZIndex = BASE_DIALOG_Z_INDEX;

/** Allocates the next top-most z-index for a dialog instance. */
function getNextDialogZIndex(): number {
  topDialogZIndex += 1;
  return topDialogZIndex;
}

/**
 * Returns the default windowed size for a dialog preset.
 */
function getDialogDimensions(size: DialogSize): DialogDimensions {
  if (size === "large") {
    return {
      width: window.innerWidth * 0.75,
      height: window.innerHeight * 0.75,
      minWidth: 600,
      minHeight: 400,
    };
  }

  return {
    width: 480,
    height: Math.min(window.innerHeight * 0.8, 600),
    minWidth: 480,
    minHeight: 300,
  };
}

/**
 * Keeps dialogs fully reachable after drag or fullscreen restore.
 */
function clampDialogPosition(
  position: DialogPosition,
  dimensions: DialogDimensions,
): DialogPosition {
  return {
    x: Math.max(0, Math.min(position.x, window.innerWidth - dimensions.width)),
    y: Math.max(
      0,
      Math.min(
        position.y,
        window.innerHeight - Math.max(dimensions.height, DIALOG_HEADER_HEIGHT),
      ),
    ),
  };
}

/**
 * Props for DraggableDialog component.
 */
interface DraggableDialogProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Callback when dialog should close */
  onOpenChange: (open: boolean) => void;
  /** Dialog title to display in header */
  title: string;
  /** Optional action button to display in header */
  headerAction?: ReactNode;
  /** Dialog content to render inside the draggable container */
  children: ReactNode;
  /** Size preset: 'default' (480x600) or 'large' (75% of screen) */
  size?: DialogSize;
  /** Enables a fullscreen toggle for dialogs that benefit from more workspace. */
  fullscreenable?: boolean;
}

/**
 * Draggable dialog component with optional fullscreen support.
 *
 * Features:
 * - Drag anywhere on the screen by dragging the header
 * - Optional fullscreen mode for workspace-heavy flows
 * - No backdrop/overlay so the underlying canvas stays visible
 * - Theme-aware styling
 * - High-performance dragging using transform
 */
function DraggableDialog({
  open,
  onOpenChange,
  title,
  headerAction,
  children,
  size = "default",
  fullscreenable = false,
}: DraggableDialogProps) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isFullscreenTransitionActive, setIsFullscreenTransitionActive] =
    useState(false);
  const [zIndex, setZIndex] = useState(BASE_DIALOG_Z_INDEX);
  const dialogRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);
  const dragStartRef = useRef({ x: 0, y: 0, elemX: 0, elemY: 0 });
  const currentPosRef = useRef<DialogPosition>({ x: 0, y: 0 });
  const restorePositionRef = useRef<DialogPosition>({ x: 0, y: 0 });
  const fullscreenTransitionTimerRef = useRef<number | null>(null);

  const getWindowedDimensions = useCallback(
    () => getDialogDimensions(size),
    [size],
  );

  /** Brings this dialog above other dialogs on open, click, or drag. */
  const bringToFront = useCallback(() => {
    setZIndex(getNextDialogZIndex());
  }, []);

  /**
   * Applies a windowed transform after clamping it to the visible viewport.
   */
  const applyWindowedPosition = useCallback(
    (position: DialogPosition) => {
      const dialogElement = dialogRef.current;
      if (!dialogElement) {
        return;
      }

      const boundedPosition = clampDialogPosition(
        position,
        getWindowedDimensions(),
      );
      currentPosRef.current = boundedPosition;
      dialogElement.style.transform = `translate(${boundedPosition.x}px, ${boundedPosition.y}px)`;
    },
    [getWindowedDimensions],
  );

  /**
   * Centers a dialog when it opens so each session starts from a predictable
   * windowed position instead of reusing a stale drag offset.
   */
  const centerDialog = useCallback(() => {
    const dimensions = getWindowedDimensions();
    applyWindowedPosition({
      x: (window.innerWidth - dimensions.width) / 2,
      y: (window.innerHeight - dimensions.height) / 2,
    });
  }, [applyWindowedPosition, getWindowedDimensions]);

  useEffect(() => {
    if (!open) {
      if (fullscreenTransitionTimerRef.current !== null) {
        window.clearTimeout(fullscreenTransitionTimerRef.current);
        fullscreenTransitionTimerRef.current = null;
      }
      setIsFullscreen(false);
      setIsFullscreenTransitionActive(false);
      return;
    }

    bringToFront();
    centerDialog();
  }, [bringToFront, centerDialog, open]);

  useEffect(() => {
    return () => {
      if (fullscreenTransitionTimerRef.current !== null) {
        window.clearTimeout(fullscreenTransitionTimerRef.current);
      }
    };
  }, []);

  /**
   * Start dragging when mouse down on header.
   * Records initial offset for smooth drag behavior.
   */
  const handleMouseDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (isFullscreen) {
      return;
    }

    if ((event.target as HTMLElement).closest("button")) {
      return;
    }

    isDraggingRef.current = true;
    dragStartRef.current = {
      x: event.clientX,
      y: event.clientY,
      elemX: currentPosRef.current.x,
      elemY: currentPosRef.current.y,
    };

    event.preventDefault();
    document.body.style.userSelect = "none";

    if (dialogRef.current) {
      dialogRef.current.style.cursor = "grabbing";
    }
  };

  /**
   * Update position while dragging.
   * Uses direct DOM manipulation for zero-lag dragging.
   */
  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      if (!isDraggingRef.current || !dialogRef.current) {
        return;
      }

      applyWindowedPosition({
        x: dragStartRef.current.elemX + (event.clientX - dragStartRef.current.x),
        y: dragStartRef.current.elemY + (event.clientY - dragStartRef.current.y),
      });
    };

    const handleMouseUp = () => {
      if (!isDraggingRef.current) {
        return;
      }

      isDraggingRef.current = false;
      document.body.style.userSelect = "";

      if (dialogRef.current) {
        dialogRef.current.style.cursor = "";
      }
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [applyWindowedPosition]);

  /**
   * Fullscreen is opt-in because only a few dialog flows benefit from turning a
   * floating utility window into a primary workspace.
   */
  const toggleFullscreen = () => {
    if (!fullscreenable) {
      return;
    }

    if (fullscreenTransitionTimerRef.current !== null) {
      window.clearTimeout(fullscreenTransitionTimerRef.current);
    }

    setIsFullscreenTransitionActive(true);
    fullscreenTransitionTimerRef.current = window.setTimeout(() => {
      setIsFullscreenTransitionActive(false);
      fullscreenTransitionTimerRef.current = null;
    }, FULLSCREEN_TRANSITION_MS);

    if (!isFullscreen) {
      restorePositionRef.current = currentPosRef.current;
      currentPosRef.current = { x: 0, y: 0 };
      if (dialogRef.current) {
        dialogRef.current.style.transform = "translate(0px, 0px)";
      }
      setIsFullscreen(true);
      return;
    }

    setIsFullscreen(false);
    applyWindowedPosition(restorePositionRef.current);
  };

  /**
   * Close dialog completely and reset fullscreen state for the next open.
   */
  const handleClose = () => {
    if (fullscreenTransitionTimerRef.current !== null) {
      window.clearTimeout(fullscreenTransitionTimerRef.current);
      fullscreenTransitionTimerRef.current = null;
    }
    setIsFullscreen(false);
    setIsFullscreenTransitionActive(false);
    onOpenChange(false);
  };

  if (!open) {
    return null;
  }

  const dimensions = getWindowedDimensions();

  return (
    <div
      ref={dialogRef}
      className={cn(
        "fixed left-0 top-0",
        isFullscreenTransitionActive &&
          "transition-[width,height,transform] ease-in-out",
      )}
      onMouseDownCapture={bringToFront}
      style={{
        zIndex,
        width: isFullscreen ? "100vw" : `${dimensions.width}px`,
        height: isFullscreen ? "100vh" : `${dimensions.height}px`,
        minWidth: isFullscreen ? undefined : `${dimensions.minWidth}px`,
        minHeight: isFullscreen ? undefined : `${dimensions.minHeight}px`,
        transitionDuration: isFullscreenTransitionActive
          ? `${FULLSCREEN_TRANSITION_MS}ms`
          : undefined,
        willChange: isFullscreen ? undefined : "transform",
      }}
    >
      <div
        className={cn(
          "bg-background flex h-full flex-col overflow-hidden shadow-2xl",
          isFullscreenTransitionActive &&
            "transition-[border-radius] ease-in-out",
          isFullscreen ? "border-0 rounded-none" : "rounded-lg border border-border",
        )}
        style={{
          transitionDuration: isFullscreenTransitionActive
            ? `${FULLSCREEN_TRANSITION_MS}ms`
            : undefined,
        }}
      >
        <div
          className={cn(
            "h-10 border-b border-border bg-background px-3",
            "flex items-center justify-between select-none",
            isFullscreen
              ? "cursor-default"
              : "cursor-grab active:cursor-grabbing",
          )}
          onMouseDown={handleMouseDown}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
            <h2 className="truncate text-sm font-semibold text-foreground">
              {title}
            </h2>
          </div>

          <div className="flex items-center gap-1">
            {headerAction && <div className="mr-2">{headerAction}</div>}
            {fullscreenable && (
              <button
                type="button"
                onClick={toggleFullscreen}
                className="rounded p-1 transition-colors hover:bg-accent"
                aria-label={
                  isFullscreen ? "Exit fullscreen" : "Enter fullscreen"
                }
                title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
              >
                {isFullscreen ? (
                  <Minimize2 className="h-3.5 w-3.5 text-foreground" />
                ) : (
                  <Expand className="h-3.5 w-3.5 text-foreground" />
                )}
              </button>
            )}
            <button
              type="button"
              onClick={handleClose}
              className="rounded p-1 transition-colors hover:bg-accent"
              aria-label="Close"
            >
              <X className="h-3.5 w-3.5 text-foreground" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-hidden">{children}</div>
      </div>
    </div>
  );
}

export default DraggableDialog;
