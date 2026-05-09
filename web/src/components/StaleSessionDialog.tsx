import { Loader2, RefreshCw } from "@/lib/lucide";
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
 * Blocking dialog shown when a consumer session is pinned to an outdated
 * Agent release. Offers Migrate (create a fresh session, carry private
 * workspace files) or Close (mark old session closed, keep history).
 */
interface StaleSessionDialogProps {
    isOpen: boolean;
    onMigrate: () => void;
    onClose: () => void;
    isMigrating?: boolean;
    isClosing?: boolean;
}

function StaleSessionDialog({
    isOpen,
    onMigrate,
    onClose,
    isMigrating = false,
    isClosing = false,
}: StaleSessionDialogProps) {
    const isBusy = isMigrating || isClosing;
    return (
        <AlertDialog open={isOpen}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <div className="flex items-center space-x-3">
                        <div className="w-10 h-10 rounded-lg bg-warning/10 flex items-center justify-center flex-shrink-0">
                            <RefreshCw className="w-5 h-5 text-warning" aria-hidden="true" />
                        </div>
                        <AlertDialogTitle>Agent has been republished</AlertDialogTitle>
                    </div>
                    <AlertDialogDescription className="pt-2">
                        This conversation was started on an earlier release of the agent.
                        A new session is required to continue safely. Choose Migrate to
                        carry over your workspace files, or Close to keep this conversation
                        as read-only history.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel
                        onClick={(event) => {
                            event.preventDefault();
                            if (!isBusy) {
                                onClose();
                            }
                        }}
                        disabled={isBusy}
                    >
                        {isClosing ? (
                            <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Close
                            </>
                        ) : (
                            'Close'
                        )}
                    </AlertDialogCancel>
                    <AlertDialogAction
                        onClick={(event) => {
                            event.preventDefault();
                            if (!isBusy) {
                                onMigrate();
                            }
                        }}
                        disabled={isBusy}
                    >
                        {isMigrating ? (
                            <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Migrate
                            </>
                        ) : (
                            'Migrate'
                        )}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}

export default StaleSessionDialog;
