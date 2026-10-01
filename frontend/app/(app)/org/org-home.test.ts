import { describe, expect, it } from "vitest";

import type { Summary } from "@/components/tracker/model";

import type { InboxItem } from "./data";
import { orgHomeStats, weeklySeries } from "./home";
import type { Match } from "./scout";

// D-52: the organisation Home's stat tiles and their sparklines come from the lists the page already reads.

const NOW = new Date("2026-10-01T09:00:00Z");

describe("weeklySeries", () => {
  it("counts dates per week over the last eight weeks, oldest first", () => {
    const dates = ["2026-10-01T08:00:00Z", "2026-09-30T08:00:00Z", "2026-09-20T08:00:00Z", "2026-07-01T08:00:00Z", "bad"];
    expect(weeklySeries(dates, NOW)).toEqual([0, 0, 0, 0, 0, 0, 1, 2]);
  });

  it("counts a date in the future in this week", () => {
    expect(weeklySeries(["2026-10-02T08:00:00Z"], NOW, 3)).toEqual([0, 0, 1]);
  });
});

function item(state: "SUBMITTED" | "UNDER_REVIEW" | null): InboxItem {
  return {
    tag_id: "t",
    pitched_at: "2026-09-29T08:00:00Z",
    proposal: { id: "p", teaser: { title: "x" } },
    engagement: state ? { id: "e", state, stage_deadline_at: null } : null,
  } as unknown as InboxItem;
}

function summary(state: Summary["state"], whose: Summary["whose_turn"]): Summary {
  return { id: state + whose.join(), state, whose_turn: whose } as unknown as Summary;
}

describe("orgHomeStats", () => {
  it("counts the inbox, the fresh proposals, the matches and the engagements that wait on the organisation", () => {
    const stats = orgHomeStats(
      { items: [item(null), item("SUBMITTED"), item("UNDER_REVIEW")], next_cursor: "abc" },
      [{ created_at: "2026-09-01T00:00:00Z" }, { created_at: "2026-09-28T00:00:00Z" }] as Match[],
      [summary("UNDER_REVIEW", ["org"]), summary("INFO_REQUESTED", ["developer"]), summary("CLOSED", [])],
    );
    expect(stats).toMatchObject({ inbox: 3, more: true, fresh: 2, matches: 2, newestMatch: "2026-09-28T00:00:00Z", engagements: 3, active: 2 });
    expect(stats.waiting.map((s) => s.state)).toEqual(["UNDER_REVIEW"]);
    expect(stats.others).toHaveLength(2);
  });

  it("reads a failed read as unknown, never as zero (reviewer MAJOR, round 2)", () => {
    expect(orgHomeStats(null, null, null)).toMatchObject({ inbox: null, more: false, fresh: 0, matches: null, newestMatch: null, engagements: null, active: 0, waiting: [], others: [] });
    // One failed read leaves the others' figures intact.
    const stats = orgHomeStats({ items: [item(null)] }, null, [summary("UNDER_REVIEW", ["org"])]);
    expect(stats).toMatchObject({ inbox: 1, matches: null, engagements: 1 });
    expect(stats.waiting).toHaveLength(1);
  });
});
