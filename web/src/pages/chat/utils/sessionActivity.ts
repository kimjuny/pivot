/**
 * Session inactivity timeout used to automatically start a fresh conversation.
 */
export const SESSION_IDLE_TIMEOUT_MS = 15 * 60 * 1000;

/**
 * Convert an agent-level idle timeout setting into milliseconds.
 *
 * Why: older agents do not have this persisted setting yet, so the chat UI
 * must fall back to the historical 15-minute threshold until configuration is
 * explicitly saved.
 */
export function resolveSessionIdleTimeoutMs(
  sessionIdleTimeoutMinutes: number | null | undefined,
): number {
  if (
    sessionIdleTimeoutMinutes === undefined ||
    sessionIdleTimeoutMinutes === null ||
    !Number.isFinite(sessionIdleTimeoutMinutes) ||
    sessionIdleTimeoutMinutes < 1
  ) {
    return SESSION_IDLE_TIMEOUT_MS;
  }

  return sessionIdleTimeoutMinutes * 60 * 1000;
}

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
  idleTimeoutMs: number = SESSION_IDLE_TIMEOUT_MS,
): boolean {
  if (!session) {
    return false;
  }

  const updatedAtMs = Date.parse(session.updated_at);
  if (Number.isNaN(updatedAtMs)) {
    return true;
  }

  return nowMs - updatedAtMs > idleTimeoutMs;
}
