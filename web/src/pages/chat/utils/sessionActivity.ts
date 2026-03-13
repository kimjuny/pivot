/**
 * Session inactivity timeout used to automatically start a fresh conversation.
 */
export const SESSION_IDLE_TIMEOUT_MS = 15 * 60 * 1000;

/**
 * Minimal session timestamp shape used by the inactivity helpers.
 */
export interface SessionActivityInfo {
  updated_at: string;
}

/**
 * Decide whether a session has been idle long enough to require a new session.
 * Why: once a conversation sits idle for too long, continuing in the same thread
 * makes the UX feel sticky across unrelated asks.
 */
export function hasSessionExceededIdleTimeout(
  session: SessionActivityInfo | null | undefined,
  nowMs: number = Date.now(),
): boolean {
  if (!session) {
    return false;
  }

  const updatedAtMs = Date.parse(session.updated_at);
  if (Number.isNaN(updatedAtMs)) {
    return true;
  }

  return nowMs - updatedAtMs > SESSION_IDLE_TIMEOUT_MS;
}
