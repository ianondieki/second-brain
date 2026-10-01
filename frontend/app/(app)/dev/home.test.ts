import { describe, expect, it } from "vitest";

import { summary } from "@/test/engagement";

import { homeGroups } from "./home";

// Developer Home (REQ-ENG-03, docs/spec/07 item 1): "Needs you" lists what waits on the developer, nothing else.
describe("the Home's engagement groups", () => {
  it("puts the developer's turn under Needs you and the organisation's turn with the others", () => {
    const mine = summary({ id: "a", whose_turn: ["developer"] });
    const both = summary({ id: "b", whose_turn: ["developer", "org"] });
    const theirs = summary({ id: "c", whose_turn: ["org"] });
    const closed = summary({ id: "d", state: "CLOSED", whose_turn: [] });
    const ended = summary({ id: "e", state: "DECLINED", whose_turn: ["developer"] });
    const { waiting, others } = homeGroups([mine, theirs, both, closed, ended]);
    expect(waiting.map((e) => e.id)).toEqual(["a", "b"]);
    expect(others.map((e) => e.id)).toEqual(["c", "d", "e"]);
  });
});

describe("homeStats", () => {
  it("counts live ideas and drafts, active engagements, and finds the soonest deadline", async () => {
    const { homeStats } = await import("./home");
    const { summary } = await import("@/test/engagement");
    const engagements = [
      summary({ id: "a", due: { due_on: "2026-10-09", business_days_left: 6, overdue: false } }),
      summary({ id: "b", state: "UNDER_REVIEW", due: { due_on: "2026-10-03", business_days_left: 2, overdue: false } }),
      summary({ id: "c", state: "DECLINED", due: { due_on: "2026-10-01", business_days_left: 0, overdue: false } }),
    ];
    const idea = (over: Record<string, unknown>) => ({ id: "x", title: "t", status: "published", moderation_state: "clear", niche: null, cert_id: null, current_version_no: 1, has_draft: false, published_at: null, updated_at: "2026-10-01T00:00:00Z", ...over }) as never;
    const stats = homeStats(engagements, [idea({}), idea({ status: "draft" }), idea({ has_draft: true }), idea({ status: "hidden" })]);
    expect(stats).toEqual({ ideas: 3, published: 2, drafts: 1, changes: 1, engagements: 3, active: 2, nextDue: engagements[1].due, nextDueId: "b" });
  });

  it("has no deadline when no active engagement carries one", async () => {
    const { homeStats } = await import("./home");
    const { summary } = await import("@/test/engagement");
    expect(homeStats([summary({ due: null })], []).nextDue).toBeNull();
  });
});
