import { useState, useRef, useEffect, ReactNode } from 'react';
import { X, Minus, Maximize2 } from 'lucide-react';

/**
 * Dialog size preset.
 */
type DialogSize = 'default' | 'large';

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
}

/**
 * Draggable and minimizable dialog component.
 *
 * Features:
 * - Drag anywhere on the screen by dragging the header
 * - Minimize to a compact bar (like macOS notes)
 * - No backdrop/overlay - user can see the canvas while building
 * - Maintains position even when minimized
 * - Theme-aware styling
 * - High-performance dragging using transform
 */
function DraggableDialog({ open, onOpenChange, title, headerAction, children, size = 'default' }: DraggableDialogProps) {
    const [isMinimized, setIsMinimized] = useState(false);
    const dialogRef = useRef<HTMLDivElement>(null);
    const isDraggingRef = useRef(false);
    const dragStartRef = useRef({ x: 0, y: 0, elemX: 0, elemY: 0 });
    const currentPosRef = useRef({ x: 0, y: 0 });

    // Calculate dimensions based on size
    const getDimensions = () => {
        if (size === 'large') {
            return {
                width: window.innerWidth * 0.75,
                height: window.innerHeight * 0.75,
                minWidth: 600,
                minHeight: 400
            };
        }
        return {
            width: 480,
            height: Math.min(window.innerHeight * 0.8, 600),
            minWidth: 480,
            minHeight: 300
        };
    };

    const dimensions = getDimensions();

    // Initialize position to center on first render
    useEffect(() => {
        if (open && dialogRef.current) {
            const dims = getDimensions();
            const initialX = (window.innerWidth - dims.width) / 2;
            const initialY = (window.innerHeight - dims.height) / 2;
            currentPosRef.current = { x: initialX, y: initialY };
            dialogRef.current.style.transform = `translate(${initialX}px, ${initialY}px)`;
        }
    }, [open, size]);

    /**
     * Start dragging when mouse down on header.
     * Records initial offset for smooth drag behavior.
     */
    const handleMouseDown = (e: React.MouseEvent) => {
        // Only start drag if clicking on header (not buttons)
        if ((e.target as HTMLElement).closest('button')) {
            return;
        }

        isDraggingRef.current = true;
        dragStartRef.current = {
            x: e.clientX,
            y: e.clientY,
            elemX: currentPosRef.current.x,
            elemY: currentPosRef.current.y
        };

        // Prevent text selection during drag
        e.preventDefault();
        document.body.style.userSelect = 'none';

        if (dialogRef.current) {
            dialogRef.current.style.cursor = 'grabbing';
        }
    };

    /**
     * Update position while dragging.
     * Uses direct DOM manipulation for zero-lag dragging.
     */
    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (!isDraggingRef.current || !dialogRef.current) return;

            const deltaX = e.clientX - dragStartRef.current.x;
            const deltaY = e.clientY - dragStartRef.current.y;

            const newX = dragStartRef.current.elemX + deltaX;
            const newY = dragStartRef.current.elemY + deltaY;

            // Get current dimensions
            const dims = getDimensions();
            const dialogWidth = dims.width;
            const dialogHeight = isMinimized ? 40 : dims.height;

            const boundedX = Math.max(0, Math.min(newX, window.innerWidth - dialogWidth));
            const boundedY = Math.max(0, Math.min(newY, window.innerHeight - dialogHeight));

            currentPosRef.current = { x: boundedX, y: boundedY };

            // Update position using transform for GPU acceleration
            dialogRef.current.style.transform = `translate(${boundedX}px, ${boundedY}px)`;
        };

        const handleMouseUp = () => {
            if (isDraggingRef.current) {
                isDraggingRef.current = false;
                document.body.style.userSelect = '';

                if (dialogRef.current) {
                    dialogRef.current.style.cursor = '';
                }
            }
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);

        return () => {
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
        };
    }, [isMinimized, size]);

    /**
     * Toggle between minimized and expanded states.
     */
    const toggleMinimize = () => {
        setIsMinimized(!isMinimized);
    };

    /**
     * Close dialog completely.
     * Resets minimized state for next open.
     */
    const handleClose = () => {
        onOpenChange(false);
        setIsMinimized(false);
    };

    if (!open) return null;

    const dims = getDimensions();

    return (
        <div
            ref={dialogRef}
            className="fixed z-50 left-0 top-0"
            style={{
                width: `${dims.width}px`,
                height: isMinimized ? '40px' : `${dims.height}px`,
                willChange: 'transform'
            }}
        >
            <div className="bg-background border border-border rounded-lg shadow-2xl flex flex-col h-full overflow-hidden">
                {/* Draggable Header */}
                <div
                    className="px-3 py-2 border-b border-border bg-background flex items-center justify-between cursor-grab active:cursor-grabbing select-none"
                    onMouseDown={handleMouseDown}
                >
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                        <span className="w-2 h-2 bg-primary rounded-full animate-pulse" />
                        <h2 className="text-sm font-semibold text-foreground truncate">
                            {title}
                        </h2>
                    </div>

                    <div className="flex items-center gap-1">
                        {headerAction && !isMinimized && (
                            <div className="mr-2">
                                {headerAction}
                            </div>
                        )}
                        <button
                            onClick={toggleMinimize}
                            className="p-1 hover:bg-accent rounded transition-colors relative overflow-hidden"
                            aria-label={isMinimized ? "Restore" : "Minimize"}
                        >
                            <div className="relative w-3.5 h-3.5">
                                <Minus
                                    className={`absolute inset-0 w-3.5 h-3.5 text-foreground transition-all duration-150 ${isMinimized
                                        ? 'opacity-0 scale-0 rotate-90'
                                        : 'opacity-100 scale-100 rotate-0'
                                        }`}
                                />
                                <Maximize2
                                    className={`absolute inset-0 w-3.5 h-3.5 text-foreground transition-all duration-150 ${isMinimized
                                        ? 'opacity-100 scale-100 rotate-0'
                                        : 'opacity-0 scale-0 -rotate-90'
                                        }`}
                                />
                            </div>
                        </button>
                        <button
                            onClick={handleClose}
                            className="p-1 hover:bg-accent rounded transition-colors"
                            aria-label="Close"
                        >
                            <X className="w-3.5 h-3.5 text-foreground" />
                        </button>
                    </div>
                </div>

                {/* Content Area - Hidden with CSS when minimized to preserve state */}
                <div 
                    className="flex-1 overflow-hidden"
                    style={{ display: isMinimized ? 'none' : 'block' }}
                >
                    {children}
                </div>
            </div>
        </div>
    );
}

export default DraggableDialog;
