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
