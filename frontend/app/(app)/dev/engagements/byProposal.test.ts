import { describe, expect, it } from "vitest";

import type { Summary } from "@/components/tracker/model";

import { byProposal } from "./byProposal";

// docs/spec/07 item 1 (P16-B ux-review, for C1): the developer's engagements grouped by proposal, one row per
// organisation, what waits on the developer first.
function row(id: string, proposal: string, turn: Summary["whose_turn"], state: Summary["state"] = "SUBMITTED"): Summary {
  return {
    id,
    proposal_id: proposal,
    proposal_title: `Idea ${proposal}`,
    org_name: `Org ${id}`,
    whose_turn: turn,
    state,
  } as Summary;
}

describe("byProposal", () => {
  it("groups by proposal in the API's order, one row per organisation", () => {
    const groups = byProposal([row("a", "p1", ["org"]), row("b", "p2", ["org"]), row("c", "p1", ["org"])]);
    expect(groups.map((g) => [g.proposalId, g.title, g.items.map((i) => i.id)])).toEqual([
      ["p1", "Idea p1", ["a", "c"]],
      ["p2", "Idea p2", ["b"]],
    ]);
    expect(groups.every((g) => !g.needsYou)).toBe(true);
  });

  it("puts proposals and rows that wait on the developer first", () => {
    const groups = byProposal([
      row("a", "p1", ["org"]),
      row("b", "p2", ["org"]),
      row("c", "p2", ["developer"]),
      row("d", "p1", ["developer"], "WITHDRAWN"),
    ]);
    expect(groups.map((g) => [g.proposalId, g.needsYou, g.items.map((i) => i.id)])).toEqual([
      ["p2", true, ["c", "b"]],
      ["p1", false, ["a", "d"]], // a finished engagement never waits on anyone
    ]);
  });

  it("is empty without engagements", () => {
    expect(byProposal([])).toEqual([]);
  });
});
