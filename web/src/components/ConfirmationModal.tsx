import { AlertTriangle } from 'lucide-react';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';

/**
 * Confirmation modal for destructive actions.
 * Provides accessible modal dialog using shadcn AlertDialog.
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
 * Reusable confirmation modal component using shadcn AlertDialog.
 * Implements proper accessibility with ARIA attributes and keyboard navigation.
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
    const variantStyles = {
        danger: {
            icon: 'text-destructive',
            iconBg: 'bg-destructive/10',
            button: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        },
        warning: {
            icon: 'text-warning',
            iconBg: 'bg-warning/10',
            button: 'bg-warning text-warning-foreground hover:bg-warning/90',
        },
    };

    const styles = variantStyles[variant];

    return (
        <AlertDialog open={isOpen} onOpenChange={(open) => !open && onCancel()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <div className="flex items-center space-x-3">
                        <div className={`w-10 h-10 rounded-lg ${styles.iconBg} flex items-center justify-center flex-shrink-0`}>
                            <AlertTriangle className={`w-5 h-5 ${styles.icon}`} aria-hidden="true" />
                        </div>
                        <AlertDialogTitle>{title}</AlertDialogTitle>
                    </div>
                    <AlertDialogDescription className="pt-2">
                        {message}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel onClick={onCancel}>
                        {cancelText}
                    </AlertDialogCancel>
                    <AlertDialogAction
                        onClick={onConfirm}
                        className={styles.button}
                    >
                        {confirmText}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}

export default ConfirmationModal;
