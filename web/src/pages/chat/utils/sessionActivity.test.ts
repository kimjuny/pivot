import { describe, expect, it } from "vitest";

import {
  SESSION_IDLE_TIMEOUT_MS,
  hasSessionExceededIdleTimeout,
} from "./sessionActivity";

describe("hasSessionExceededIdleTimeout", () => {
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

  it("treats invalid timestamps as expired", () => {
    expect(
      hasSessionExceededIdleTimeout({ updated_at: "not-a-timestamp" }),
    ).toBe(true);
  });
});
