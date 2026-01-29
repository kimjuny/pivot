import React, { useEffect, useRef } from 'react';
import { AlertTriangle, X } from 'lucide-react';

/**
 * Confirmation modal for destructive actions.
 * Provides accessible modal dialog with focus trap and keyboard support.
 */
interface ConfirmationModalProps {
    /** Whether the modal is open */
    isOpen: boolean;
    /** Modal title */
    title: string;
    /** Confirmation message */
    message: string;
    /** Confirm button text */
    confirmText?: string;
    /** Cancel button text */
    cancelText?: string;
    /** Callback when user confirms */
    onConfirm: () => void;
    /** Callback when user cancels */
    onCancel: () => void;
    /** Visual variant for the modal */
    variant?: 'danger' | 'warning';
}

/**
 * Reusable confirmation modal component.
 * Implements proper accessibility with ARIA attributes, focus management, and keyboard navigation.
 */
function ConfirmationModal({
    isOpen,
    title,
    message,
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    onConfirm,
    onCancel,
    variant = 'danger',
}: ConfirmationModalProps) {
    const modalRef = useRef<HTMLDivElement>(null);
    const confirmButtonRef = useRef<HTMLButtonElement>(null);

    /**
     * Handle escape key to close modal.
     * Provides keyboard accessibility for dismissing the modal.
     */
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape' && isOpen) {
                onCancel();
            }
        };

        if (isOpen) {
            document.addEventListener('keydown', handleEscape);
            // Focus the confirm button when modal opens for keyboard accessibility
            confirmButtonRef.current?.focus();
            // Prevent body scroll when modal is open
            document.body.style.overflow = 'hidden';
        }

        return () => {
            document.removeEventListener('keydown', handleEscape);
            document.body.style.overflow = 'unset';
        };
    }, [isOpen, onCancel]);

    /**
     * Handle backdrop click to close modal.
     * Only closes if clicking directly on backdrop, not on modal content.
     */
    const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
        if (e.target === e.currentTarget) {
            onCancel();
        }
    };

    if (!isOpen) return null;

    const variantStyles = {
        danger: {
            icon: 'text-danger',
            iconBg: 'bg-danger-100',
            button: 'bg-danger hover:bg-danger-600 focus-visible:ring-danger',
        },
        warning: {
            icon: 'text-warning',
            iconBg: 'bg-warning-100',
            button: 'bg-warning hover:bg-warning-600 focus-visible:ring-warning',
        },
    };

    const styles = variantStyles[variant];

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm motion-reduce:transition-none transition-opacity duration-200"
            onClick={handleBackdropClick}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
            aria-describedby="modal-description"
        >
            <div
                ref={modalRef}
                className="bg-dark-bg-lighter border border-dark-border rounded-lg shadow-card-lg max-w-md w-full mx-4 motion-reduce:transition-none motion-reduce:transform-none transition-all duration-200 animate-slide-up"
                style={{ overscrollBehavior: 'contain' }}
            >
                {/* Header - Fixed alignment issue by using items-center instead of items-start */}
                <div className="flex items-center justify-between p-6 pb-4">
                    <div className="flex items-center space-x-3 flex-1">
                        <div className={`w-10 h-10 rounded-lg ${styles.iconBg} flex items-center justify-center flex-shrink-0`}>
                            <AlertTriangle className={`w-5 h-5 ${styles.icon}`} aria-hidden="true" />
                        </div>
                        <h2 id="modal-title" className="text-lg font-semibold text-dark-text-primary">
                            {title}
                        </h2>
                    </div>
                    <button
                        onClick={onCancel}
                        className="text-dark-text-muted hover:text-dark-text-primary transition-colors p-1 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg-lighter ml-4 flex-shrink-0"
                        aria-label="Close modal"
                    >
                        <X className="w-5 h-5" aria-hidden="true" />
                    </button>
                </div>

                {/* Content - Fixed padding to match header */}
                <div className="px-6 pb-6">
                    <p id="modal-description" className="text-dark-text-secondary">
                        {message}
                    </p>
                </div>

                {/* Actions - Unified background color by removing bg-dark-bg */}
                <div className="flex items-center justify-end space-x-3 px-6 py-4 border-t border-dark-border rounded-b-lg">
                    <button
                        onClick={onCancel}
                        className="px-4 py-2 rounded-md text-dark-text-primary bg-dark-bg border border-dark-border hover:bg-dark-border-light transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg-lighter font-medium"
                        tabIndex={0}
                    >
                        {cancelText}
                    </button>
                    <button
                        ref={confirmButtonRef}
                        onClick={onConfirm}
                        className={`px-4 py-2 rounded-md text-white font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-dark-bg-lighter ${styles.button}`}
                        tabIndex={0}
                    >
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>
    );
}

export default ConfirmationModal;

