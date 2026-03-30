import { invoke, isTauri as detectTauriRuntime } from "@tauri-apps/api/core";

/** localStorage key for the desktop backend server URL. */
const STORAGE_KEY = "pivot_desktop_backend_url";

/** Whether the app is running inside the Tauri desktop shell. */
export const isDesktop: boolean =
  typeof window !== "undefined" &&
  (detectTauriRuntime() ||
    "__TAURI_INTERNALS__" in window ||
    "__TAURI__" in window);

interface NativeSaveBlobOptions {
  /** Binary payload to save to disk. */
  blob: Blob;
  /** Suggested filename shown in the native Save As dialog. */
  suggestedName: string;
  /** Optional file extension without the leading dot. */
  extension?: string | null;
  /** Optional human-readable file format label used by dialog filters. */
  formatLabel?: string | null;
}

/**
 * Read the previously stored backend URL.
 *
 * @returns The stored URL string, or null if not yet configured.
 */
export function getStoredBackendUrl(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

/**
 * Persist the backend URL after the user completes the setup screen.
 *
 * @param url - Full origin URL of the backend (e.g. "https://pivot.example.com").
 *   The "/api" path segment is appended by the API module, not stored here.
 */
export function setStoredBackendUrl(url: string): void {
  localStorage.setItem(STORAGE_KEY, url);
}

/**
 * Build the full API base URL from the stored backend URL.
 *
 * Appends "/api" to the stored origin if present, otherwise returns null.
 *
 * @returns The complete API base URL, or null if no backend URL is stored.
 */
export function resolveApiBaseUrl(): string | null {
  const stored = getStoredBackendUrl();
  if (!stored) return null;
  const trimmed = stored.replace(/\/+$/, "");
  return `${trimmed}/api`;
}

/**
 * Save a blob through the desktop shell's native Save As dialog.
 *
 * Tauri's dialog plugin adds the user-selected path to the filesystem scope
 * for the current session, which lets the fs plugin persist the blob without
 * predeclaring every possible destination directory.
 *
 * @param options - Save dialog metadata and blob payload.
 * @returns The chosen absolute path, or null when the user cancels.
 */
export async function saveBlobWithNativeDialog(
  options: NativeSaveBlobOptions,
): Promise<string | null> {
  if (!isDesktop) {
    return null;
  }

  const normalizedExtension = options.extension
    ?.trim()
    .replace(/^\./, "")
    .toLowerCase();
  const selectedPath = await invoke<string | null>("plugin:dialog|save", {
    options: {
    defaultPath: options.suggestedName,
    canCreateDirectories: true,
    filters: normalizedExtension
      ? [
          {
            name: options.formatLabel ?? normalizedExtension.toUpperCase(),
            extensions: [normalizedExtension],
          },
        ]
      : undefined,
    },
  });

  if (!selectedPath) {
    return null;
  }

  const bytes = new Uint8Array(await options.blob.arrayBuffer());
  await invoke("plugin:fs|write_file", bytes, {
    headers: {
      path: encodeURIComponent(selectedPath),
      options: JSON.stringify(undefined),
    },
  });
  return selectedPath;
}
