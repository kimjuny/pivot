import { ArrowRight, CircleCheck, Loader2, RefreshCw } from "lucide-react";
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
 * Dialog shown for stale or migrated consumer sessions.
 *
 * - Stale: the agent was republished; user can migrate to a new session.
 * - Migrated: this session was already migrated; user can navigate to the
 *   replacement session or dismiss to browse history.
 */
interface StaleSessionDialogProps {
    isOpen: boolean;
    onMigrate: () => void;
    onClose: () => void;
    isMigrating?: boolean;
    migratedSessionId?: string | null;
    onGoToMigrated?: (sessionId: string) => void;
}

function StaleSessionDialog({
    isOpen,
    onMigrate,
    onClose,
    isMigrating = false,
    migratedSessionId,
    onGoToMigrated,
}: StaleSessionDialogProps) {
    const isMigrated = !!migratedSessionId;

    return (
        <AlertDialog open={isOpen}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <div className="flex items-center space-x-3">
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${isMigrated ? 'bg-muted' : 'bg-warning/10'}`}>
                            {isMigrated ? (
                                <CircleCheck className="w-5 h-5 text-muted-foreground" aria-hidden="true" />
                            ) : (
                                <RefreshCw className="w-5 h-5 text-warning" aria-hidden="true" />
                            )}
                        </div>
                        <AlertDialogTitle>
                            {isMigrated ? 'Session migrated' : 'Agent has been republished'}
                        </AlertDialogTitle>
                    </div>
                    <AlertDialogDescription className="pt-2">
                        {isMigrated
                            ? 'This conversation has been migrated to a new session. You are viewing the history — sending messages is disabled.'
                            : 'This conversation was started on an earlier release of the agent. A new session is required to continue safely. You can dismiss this dialog to browse the history, but sending new messages will be disabled until you migrate.'}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel onClick={onClose} disabled={isMigrating}>
                        Close
                    </AlertDialogCancel>
                    {isMigrated ? (
                        <AlertDialogAction
                            onClick={(event) => {
                                event.preventDefault();
                                if (migratedSessionId && onGoToMigrated) {
                                    onGoToMigrated(migratedSessionId);
                                }
                            }}
                        >
                            <ArrowRight className="h-4 w-4" />
                            Go to migrated session
                        </AlertDialogAction>
                    ) : (
                        <AlertDialogAction
                            onClick={(event) => {
                                event.preventDefault();
                                if (!isMigrating) {
                                    onMigrate();
                                }
                            }}
                            disabled={isMigrating}
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
                    )}
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}

export default StaleSessionDialog;
