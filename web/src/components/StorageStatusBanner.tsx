import { useEffect, useState } from "react";

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { AlertTriangle } from "@/lib/lucide";
import { getStorageStatus, type StorageStatus } from "@/utils/api";

let cachedBannerStatus: StorageStatus | null | undefined;
let pendingBannerStatusRequest: Promise<StorageStatus | null> | null = null;

/**
 * Shows one prominent warning when storage falls back from an external profile.
 */
export function StorageStatusBanner() {
  const [status, setStatus] = useState<StorageStatus | null | undefined>(
    cachedBannerStatus,
  );

  useEffect(() => {
    let ignore = false;
    let timerId = 0;

    async function loadStorageStatus(): Promise<void> {
      const nextStatus = await getBannerStatus();
      if (!ignore) {
        setStatus(nextStatus);
      }
    }

    if (cachedBannerStatus !== undefined) {
      setStatus(cachedBannerStatus);
      return () => {
        ignore = true;
      };
    }

    timerId = window.setTimeout(() => {
      void loadStorageStatus();
    }, 0);

    return () => {
      ignore = true;
      window.clearTimeout(timerId);
    };
  }, []);

  if (status === null || status === undefined) {
    return null;
  }

  const message = getStorageWarningMessage(status);

  return (
    <div className="bg-background/95">
      <div className="mx-auto w-full max-w-5xl px-6 py-3">
        <Alert className="border-warning/30 bg-warning/10 text-warning-foreground">
          <AlertTriangle className="h-4 w-4 text-warning" />
          <AlertTitle className="text-foreground">
            External storage is not ready. Pivot is saving files locally for
            now.
          </AlertTitle>
          <AlertDescription className="text-muted-foreground">
            <p>{message}</p>
          </AlertDescription>
        </Alert>
      </div>
    </div>
  );
}

async function getBannerStatus(): Promise<StorageStatus | null> {
  if (cachedBannerStatus !== undefined) {
    return cachedBannerStatus;
  }

  if (pendingBannerStatusRequest !== null) {
    return pendingBannerStatusRequest;
  }

  pendingBannerStatusRequest = (async () => {
    try {
      const nextStatus = await getStorageStatus();
      cachedBannerStatus = shouldShowStorageWarning(nextStatus)
        ? nextStatus
        : null;
    } catch {
      // Why: the banner is purely diagnostic and should never block Studio
      // navigation if the status probe itself is temporarily unavailable.
      cachedBannerStatus = null;
    } finally {
      pendingBannerStatusRequest = null;
    }

    return cachedBannerStatus;
  })();

  return pendingBannerStatusRequest;
}

function shouldShowStorageWarning(status: StorageStatus): boolean {
  return !(
    status.fallback_reason === null ||
    status.requested_profile === status.active_profile
  );
}

function getStorageWarningMessage(status: StorageStatus): string {
  switch (status.fallback_reason) {
    case "seaweedfs_namespace_mismatch":
      return (
        "Pivot can see the SeaweedFS bridge folder, but it is not connected to " +
        "the same storage space yet. The bridge mount is likely missing or " +
        "pointing to the wrong folder."
      );
    case "seaweedfs_filer_unreachable":
      return (
        "Pivot cannot reach SeaweedFS right now. Please check whether the " +
        "SeaweedFS filer and bridge are running normally."
      );
    case "seaweedfs_posix_root_missing":
      return (
        "Pivot cannot find the SeaweedFS bridge folder from the backend. " +
        "Please check whether the mount directory exists and is shared " +
        "correctly."
      );
    case "seaweedfs_posix_io_failed":
      return (
        "Pivot found the SeaweedFS bridge, but it cannot write files through " +
        "it yet. Please check whether the bridge mount is healthy and " +
        "writable."
      );
    default:
      if (status.external_filer_reachable === false) {
        return (
          "Pivot cannot reach SeaweedFS right now. Please check whether the " +
          "SeaweedFS filer and bridge are running normally."
        );
      }
      if (
        status.external_posix_root_exists &&
        status.external_namespace_shared === false
      ) {
        return (
          "Pivot can see the SeaweedFS bridge folder, but it is not connected " +
          "to the same storage space yet."
        );
      }
      return (
        "External storage is temporarily unavailable. Please check the " +
        "SeaweedFS bridge status and try again."
      );
  }
}
