/** localStorage key for the desktop backend server URL. */
const STORAGE_KEY = "pivot_desktop_backend_url";

/** Whether the app is running inside the Tauri desktop shell. */
export const isDesktop: boolean = "__TAURI__" in window;

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
