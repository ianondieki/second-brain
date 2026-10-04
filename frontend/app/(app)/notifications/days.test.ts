import { describe, expect, it } from "vitest";

import { groupByDay, nairobiDay } from "./days";

// P19-C: the Notifications page groups by the Nairobi day (docs/spec/07 item 7: store UTC, display Africa/Nairobi).

const NOW = new Date("2026-10-02T09:00:00Z"); // 12:00 EAT on 2 Oct

describe("nairobiDay", () => {
  it("is the calendar day in Nairobi, three hours ahead of UTC", () => {
    expect(nairobiDay("2026-10-01T20:59:00Z")).toBe("2026-10-01");
    expect(nairobiDay("2026-10-01T21:00:00Z")).toBe("2026-10-02"); // midnight EAT
  });
});

describe("groupByDay", () => {
  it("keeps the API's newest-first order in groups: Today, Yesterday, then dates", () => {
    const items = [
      { id: "a", created_at: "2026-10-02T08:00:00Z" },
      { id: "b", created_at: "2026-10-01T22:30:00Z" }, // 01:30 EAT on 2 Oct: today
      { id: "c", created_at: "2026-10-01T20:00:00Z" }, // 23:00 EAT on 1 Oct: yesterday
      { id: "d", created_at: "2026-09-28T10:00:00Z" },
      { id: "e", created_at: "2026-09-28T06:00:00Z" },
    ];
    const groups = groupByDay(items, NOW);
    expect(groups.map((g) => [g.day, g.name, g.items.map((i) => i.id).join("")])).toEqual([
      ["2026-10-02", "today", "ab"],
      ["2026-10-01", "yesterday", "c"],
      ["2026-09-28", "date", "de"],
    ]);
    expect(groups[2].at).toBe("2026-09-28T10:00:00Z");
  });

  it("names yesterday across a month's end", () => {
    const groups = groupByDay([{ created_at: "2026-09-30T12:00:00Z" }], new Date("2026-10-01T05:00:00Z"));
    expect(groups[0].name).toBe("yesterday");
  });

  it("answers no groups for no items", () => {
    expect(groupByDay([], NOW)).toEqual([]);
  });
});
