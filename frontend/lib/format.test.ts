import { describe, expect, it } from "vitest";

import { formatCalendarDate, formatDay, formatMoment, formatMomentSeconds, formatTime, nairobiParts } from "./format";

// REQ-UX-07 (docs/spec/07 item 7): one date format on every screen, "30 Sep 2026", shown in Nairobi time.

describe("the shared date format", () => {
  it("writes a day with a three-letter month, never 'Sept'", () => {
    expect(formatDay("en", "2026-09-30T08:00:00Z")).toBe("30 Sep 2026");
    expect(formatCalendarDate("en", "2026-09-28")).toBe("28 Sep 2026");
    expect(formatMoment("en", "2026-09-30T11:06:00Z")).toBe("30 Sep 2026, 14:06");
    for (const text of [
      formatDay("en", "2026-09-01T08:00:00Z"),
      formatCalendarDate("en", "2026-09-15"),
      formatMoment("en", "2026-09-15T08:00:00Z"),
    ]) {
      expect(text).not.toMatch(/Sept/);
    }
  });

  it("writes every month in three letters", () => {
    const months = Array.from({ length: 12 }, (_, i) => formatCalendarDate("en", `2026-${String(i + 1).padStart(2, "0")}-10`));
    expect(months).toEqual([
      "10 Jan 2026",
      "10 Feb 2026",
      "10 Mar 2026",
      "10 Apr 2026",
      "10 May 2026",
      "10 Jun 2026",
      "10 Jul 2026",
      "10 Aug 2026",
      "10 Sep 2026",
      "10 Oct 2026",
      "10 Nov 2026",
      "10 Dec 2026",
    ]);
  });

  it("shows a moment in Nairobi time, so late UTC evenings are the next day", () => {
    expect(formatDay("en", "2026-09-29T22:30:00Z")).toBe("30 Sep 2026");
    expect(formatMoment("en", "2026-09-30T21:30:00Z")).toBe("1 Oct 2026, 00:30");
    expect(formatTime("en", "2026-09-30T21:30:00Z")).toBe("00:30");
    expect(nairobiParts("en", "2026-09-23T11:05:00Z")).toEqual({ date: "23 Sep 2026", time: "14:05" });
  });

  it("never shifts a calendar date and leaves anything else as it is", () => {
    expect(formatCalendarDate("en", "2026-01-01")).toBe("1 Jan 2026");
    expect(formatCalendarDate("en", "2026-12-31")).toBe("31 Dec 2026");
    expect(formatCalendarDate("en", "not a date")).toBe("not a date");
  });

  it("writes a moment to the second in the same format, in Nairobi or UTC", () => {
    expect(formatMomentSeconds("en", "2026-09-30T07:49:20Z")).toBe("30 Sep 2026, 10:49:20");
    expect(formatMomentSeconds("en", "2026-09-30T07:49:20Z", "UTC")).toBe("30 Sep 2026, 07:49:20");
    expect(formatMomentSeconds("en", "2026-09-30T21:30:05Z")).toBe("1 Oct 2026, 00:30:05"); // the next day in Nairobi
    expect(formatMomentSeconds("sw", "2026-10-10T11:06:25Z")).toBe("10 Okt 2026, 14:06:25");
  });

  it("uses the same shape in Swahili", () => {
    expect(formatDay("sw", "2026-09-30T08:00:00Z")).toBe("30 Sep 2026");
    expect(formatDay("sw", "2026-10-10T08:00:00Z")).toBe("10 Okt 2026");
    expect(formatMoment("sw", "2026-10-10T11:06:00Z")).toBe("10 Okt 2026, 14:06");
  });
});
