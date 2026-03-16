import { describe, expect, it } from "vitest";

import {
  SESSION_IDLE_TIMEOUT_MS,
  hasSessionExceededIdleTimeout,
  resolveSessionIdleTimeoutMs,
} from "./sessionActivity";

describe("hasSessionExceededIdleTimeout", () => {
  it("falls back to the default timeout when the agent config is missing", () => {
    expect(resolveSessionIdleTimeoutMs(undefined)).toBe(SESSION_IDLE_TIMEOUT_MS);
    expect(resolveSessionIdleTimeoutMs(0)).toBe(SESSION_IDLE_TIMEOUT_MS);
  });

  it("returns false for a recently updated session", () => {
    const nowMs = Date.parse("2026-03-12T12:00:00.000Z");

    expect(
      hasSessionExceededIdleTimeout(
        {
          updated_at: new Date(nowMs - (SESSION_IDLE_TIMEOUT_MS - 1_000)).toISOString(),
        },
        nowMs,
      ),
    ).toBe(false);
  });

  it("returns true once the session exceeds the inactivity threshold", () => {
    const nowMs = Date.parse("2026-03-12T12:00:00.000Z");

    expect(
      hasSessionExceededIdleTimeout(
        {
          updated_at: new Date(nowMs - (SESSION_IDLE_TIMEOUT_MS + 1_000)).toISOString(),
        },
        nowMs,
      ),
    ).toBe(true);
  });

  it("uses the agent-specific timeout when one is configured", () => {
    const nowMs = Date.parse("2026-03-12T12:00:00.000Z");
    const customTimeoutMs = resolveSessionIdleTimeoutMs(45);

    expect(
      hasSessionExceededIdleTimeout(
        {
          updated_at: new Date(nowMs - (30 * 60 * 1000)).toISOString(),
        },
        nowMs,
        customTimeoutMs,
      ),
    ).toBe(false);
  });

  it("treats invalid timestamps as expired", () => {
    expect(
      hasSessionExceededIdleTimeout({ updated_at: "not-a-timestamp" }),
    ).toBe(true);
  });
});
