import { describe, expect, it } from "vitest";

import { deadline } from "@/test/deadlines";

import {
  addDays,
  byDay,
  googleCalendarHref,
  gridSpan,
  keyParts,
  monthWeeks,
  nairobiDay,
  pickMonth,
  shiftMonth,
  upcoming,
} from "./month";

// P27 track A (REQ-ENG-13): the Calendar tab's arithmetic. Nairobi days (the API's due_on), weeks Monday first, the
// month from ?month= or today's, the list's overdue and next-30-days split, the Google Calendar entry.

describe("the Nairobi day", () => {
  it("turns at midnight in Nairobi (UTC+3), not at midnight UTC or the browser's", () => {
    expect(nairobiDay("2026-10-12T20:59:59.999Z")).toBe("2026-10-12");
    expect(nairobiDay("2026-10-12T21:00:00.000Z")).toBe("2026-10-13");
    expect(nairobiDay("2026-12-31T21:30:00Z")).toBe("2027-01-01");
  });

  it("adds days across months and years", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });
});

describe("the month shown", () => {
  it("is ?month= when it is a real month, else today's", () => {
    expect(pickMonth("2026-11", "2026-10-12")).toBe("2026-11");
    expect(pickMonth(["2027-01", "2026-02"], "2026-10-12")).toBe("2027-01");
    for (const bad of [undefined, "", "2026-13", "2026-1", "26-10", "2026-10-01", "x"]) {
      expect(pickMonth(bad, "2026-10-12")).toBe("2026-10");
    }
  });

  it(
    "takes no month far from today's year, or of any other shape: the current month, at once (no request can hang)",
    { timeout: 1_000 },
    () => {
      for (const bad of [
        "0000-01",
        "9999-12",
        "0050-06",
        "2026-13",
        "2026-00",
        "abcd-ef",
        "2026-10-01",
        "2026-1",
        "20261",
        "2026-100",
        "12345-01",
        "+2026-10",
        " 2026-10",
        "2026-10 ",
      ]) {
        expect(pickMonth(bad, "2026-10-12"), bad).toBe("2026-10");
      }
      expect(pickMonth("x".repeat(10_000), "2026-10-12")).toBe("2026-10");
      // Ten years either side are months to show.
      expect(pickMonth("2016-10", "2026-10-12")).toBe("2016-10");
      expect(pickMonth("2036-12", "2026-10-12")).toBe("2036-12");
      expect(pickMonth("2015-12", "2026-10-12")).toBe("2026-10");
      expect(pickMonth("2037-01", "2026-10-12")).toBe("2026-10");
    },
  );

  it("draws a bounded grid for any month written, even one pickMonth would refuse", { timeout: 1_000 }, () => {
    for (const month of ["0000-01", "0050-06", "1999-12", "9999-12", "2026-02"]) {
      const weeks = monthWeeks(month);
      expect(weeks.length, month).toBeGreaterThanOrEqual(4);
      expect(weeks.length, month).toBeLessThanOrEqual(6);
      for (const week of weeks) expect(week).toHaveLength(7);
    }
    // The year is the one written (never 1950 for 0050).
    expect(
      monthWeeks("0050-06")
        .flat()
        .filter((d) => d.inMonth)[0].day,
    ).toBe("0050-06-01");
    // A link a month past the range is just a month pickMonth turns back to today's.
    expect(pickMonth(shiftMonth("2016-01", -1), "2026-10-12")).toBe("2026-10");
  });

  it("moves a month at a time, across the year", () => {
    expect(shiftMonth("2026-10", -1)).toBe("2026-09");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  });

  it("is weeks of seven days, Monday first, the neighbours' days marked outside", () => {
    // October 2026 starts on a Thursday and ends on a Saturday: five weeks.
    const october = monthWeeks("2026-10");
    expect(october).toHaveLength(5);
    expect(october[0].map((d) => d.day)).toEqual([
      "2026-09-28",
      "2026-09-29",
      "2026-09-30",
      "2026-10-01",
      "2026-10-02",
      "2026-10-03",
      "2026-10-04",
    ]);
    expect(october[0].map((d) => d.inMonth)).toEqual([false, false, false, true, true, true, true]);
    expect(october.at(-1)!.at(-1)).toEqual({ day: "2026-11-01", inMonth: false });
    for (const week of october) {
      expect(week).toHaveLength(7);
      expect(new Date(`${week[0].day}T00:00:00Z`).getUTCDay()).toBe(1);
    }
    // August 2026 starts on a Saturday and has 31 days: six weeks. February 2027 starts on a Monday: four.
    expect(monthWeeks("2026-08")).toHaveLength(6);
    expect(monthWeeks("2027-02")).toHaveLength(4);
    expect(gridSpan("2026-10")).toEqual({ from: "2026-09-28", to: "2026-11-01" });
  });
});

describe("the deadlines by day and the list", () => {
  it("groups by the Nairobi day, keeping the API's order", () => {
    const a = deadline({ key: "stage:a", due_on: "2026-10-16" });
    const b = deadline({ key: "answer:b", kind: "answer", due_on: "2026-10-16" });
    const c = deadline({ key: "brief:c", kind: "brief", due_on: "2026-10-20" });
    const days = byDay([a, b, c]);
    expect(days.get("2026-10-16")).toEqual([a, b]);
    expect(days.get("2026-10-20")).toEqual([c]);
  });

  it("reads the kind and the id from the key, for the .ics route", () => {
    expect(keyParts({ key: "milestone:0193f0c8-6a8f-7b4c-9d2e-3f4a5b6c7d8e", kind: "milestone" })).toEqual({
      kind: "milestone",
      id: "0193f0c8-6a8f-7b4c-9d2e-3f4a5b6c7d8e",
    });
  });

  it("splits the overdue from what falls due in the next 30 days, today and the 30th day included", () => {
    const late = deadline({ key: "stage:late", due_on: "2026-10-09", overdue: true, business_days_left: -1 });
    const today = deadline({ key: "stage:today", due_on: "2026-10-12", business_days_left: 0 });
    const last = deadline({ key: "stage:last", due_on: "2026-11-11" });
    const beyond = deadline({ key: "stage:beyond", due_on: "2026-11-12" });
    expect(upcoming([late, today, last, beyond], "2026-10-12")).toEqual({ overdue: [late], next: [today, last] });
  });

  it("puts a deadline in Google Calendar as a 15-minute entry at its instant, in Nairobi time", () => {
    const href = new URL(googleCalendarHref(deadline(), "Due: Maziwa baridi", "Telco A"));
    expect(href.origin + href.pathname).toBe("https://calendar.google.com/calendar/render");
    expect(href.searchParams.get("action")).toBe("TEMPLATE");
    expect(href.searchParams.get("text")).toBe("Due: Maziwa baridi");
    expect(href.searchParams.get("dates")).toBe("20261016T205959Z/20261016T211459Z");
    expect(href.searchParams.get("ctz")).toBe("Africa/Nairobi");
  });
});
