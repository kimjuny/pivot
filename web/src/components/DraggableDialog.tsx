import { useState, useRef, useEffect, ReactNode } from 'react';
import { X, Minus, Maximize2 } from 'lucide-react';

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
function DraggableDialog({ open, onOpenChange, title, headerAction, children }: DraggableDialogProps) {
    const [isMinimized, setIsMinimized] = useState(false);
    const dialogRef = useRef<HTMLDivElement>(null);
    const isDraggingRef = useRef(false);
    const dragStartRef = useRef({ x: 0, y: 0, elemX: 0, elemY: 0 });
    const currentPosRef = useRef({ x: 0, y: 0 });

    // Initialize position to center-ish on first render
    useEffect(() => {
        if (open && dialogRef.current) {
            const initialX = window.innerWidth / 2 - 240; // 480px / 2
            const initialY = 80;
            currentPosRef.current = { x: initialX, y: initialY };
            dialogRef.current.style.transform = `translate(${initialX}px, ${initialY}px)`;
        }
    }, [open]);

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

            // Simple boundary check
            const dialogWidth = 480;
            const dialogHeight = isMinimized ? 40 : Math.min(window.innerHeight * 0.8, 600);

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
    }, [isMinimized]);

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

    return (
        <div
            ref={dialogRef}
            className="fixed z-50 left-0 top-0"
            style={{
                width: '480px',
                height: isMinimized ? '40px' : '80vh',
                maxHeight: isMinimized ? '40px' : '600px',
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

                {/* Content Area - Hidden when minimized */}
                {!isMinimized && (
                    <div className="flex-1 overflow-hidden">
                        {children}
                    </div>
                )}
            </div>
        </div>
    );
}

export default DraggableDialog;
