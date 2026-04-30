import { afterEach, describe, expect, it, vi } from "vitest";

import { formatTimestamp } from "./timestamp";

describe("timestamp formatting", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("treats ISO datetimes without an explicit timezone as UTC", () => {
    const RealDate = Date;
    const constructedValues: unknown[] = [];

    class RecordingDate extends RealDate {
      constructor(value?: string | number | Date) {
        constructedValues.push(value);
        if (value === undefined) {
          super();
        } else {
          super(value);
        }
      }
    }

    vi.stubGlobal("Date", RecordingDate);

    formatTimestamp("2026-04-30T02:07:00");

    expect(constructedValues[0]).toBe("2026-04-30T02:07:00Z");
  });

  it("keeps timestamps with explicit timezone offsets unchanged", () => {
    const RealDate = Date;
    const constructedValues: unknown[] = [];

    class RecordingDate extends RealDate {
      constructor(value?: string | number | Date) {
        constructedValues.push(value);
        if (value === undefined) {
          super();
        } else {
          super(value);
        }
      }
    }

    vi.stubGlobal("Date", RecordingDate);

    formatTimestamp("2026-04-30T02:07:00+08:00");

    expect(constructedValues[0]).toBe("2026-04-30T02:07:00+08:00");
  });
});
