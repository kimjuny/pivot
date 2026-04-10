import { useEffect, useState } from "react";

import { AlertTriangle } from "@/lib/lucide";
import { getStorageStatus, type StorageStatus } from "@/utils/api";

/**
 * Shows one prominent warning when storage falls back from an external profile.
 */
export function StorageStatusBanner() {
  const [status, setStatus] = useState<StorageStatus | null>(null);

  useEffect(() => {
    let ignore = false;

    async function loadStorageStatus(): Promise<void> {
      try {
        const nextStatus = await getStorageStatus();
        if (!ignore) {
          setStatus(nextStatus);
        }
      } catch {
        // Why: the banner is purely diagnostic and should never block Studio
        // navigation if the status probe itself is temporarily unavailable.
      }
    }

    void loadStorageStatus();
    return () => {
      ignore = true;
    };
  }, []);

  if (
    status === null ||
    status.fallback_reason === null ||
    status.requested_profile === status.active_profile
  ) {
    return null;
  }

  const rootGuidance = status.external_posix_root
    ? !status.external_filer_reachable
      ? "SeaweedFS is configured, but the filer endpoint is not reachable from backend yet."
      : !status.external_posix_root_exists
        ? "Prepare the external POSIX entrypoint before startup. A plain missing directory will keep Pivot on local_fs."
        : status.external_namespace_shared
          ? null
          : "The configured POSIX root is visible to backend, but it is still a plain local directory or other non-shared path. It must expose the same namespace as the SeaweedFS filer."
      : null;

  return (
    <div className="border-b border-warning/25 bg-warning/10">
      <div className="mx-auto flex w-full max-w-7xl items-start gap-3 px-4 py-3 text-sm text-warning-foreground">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <div className="min-w-0">
          <p className="font-medium text-foreground">
            External storage is unavailable. Pivot is using local fallback storage.
          </p>
          <p className="mt-1 text-muted-foreground">
            Requested profile: <span className="font-medium text-foreground">{status.requested_profile}</span>
            {" · "}
            Active profile: <span className="font-medium text-foreground">{status.active_profile}</span>
            {" · "}
            Reason: <span className="font-medium text-foreground">{status.fallback_reason}</span>
          </p>
          {status.external_posix_root ? (
            <p className="mt-1 text-muted-foreground">
              External POSIX root:{" "}
              <span className="font-medium text-foreground">{status.external_posix_root}</span>
              {" · "}
              Visible to backend:{" "}
              <span className="font-medium text-foreground">
                {status.external_posix_root_exists ? "yes" : "no"}
              </span>
            </p>
          ) : null}
          {status.external_host_posix_root ? (
            <p className="mt-1 text-muted-foreground">
              Host POSIX root:{" "}
              <span className="font-medium text-foreground">
                {status.external_host_posix_root}
              </span>
            </p>
          ) : null}
          {rootGuidance ? (
            <p className="mt-1 text-muted-foreground">{rootGuidance}</p>
          ) : null}
          {status.external_readiness_reason ? (
            <p className="mt-1 text-muted-foreground">
              External readiness:{" "}
              <span className="font-medium text-foreground">
                {status.external_readiness_reason}
              </span>
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
