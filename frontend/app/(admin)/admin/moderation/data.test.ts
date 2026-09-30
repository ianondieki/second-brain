import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCase } from "./data";
import type { Case } from "./moderation";

// REQ-MOD-01: the case page finds its case in the open list, then in the decided one, and "Review the next case"
// goes only to a case this moderator can decide.

const lists = vi.hoisted(() => ({ open: [] as unknown[], decided: [] as unknown[] }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("notFound");
  },
  redirect: () => {
    throw new Error("redirect");
  },
}));
vi.mock("@/lib/api/server", () => ({
  forwardHeaders: async () => ({}),
  serverApi: () => ({
    GET: async (_path: string, options: { params: { query: { decided: boolean } } }) => ({
      data: { items: options.params.query.decided ? lists.decided : lists.open },
      response: new Response(null, { status: 200 }),
    }),
  }),
}));

const THIS = "01a0f016-0000-7000-8000-000000000001";
const OTHER = "01a0f016-0000-7000-8000-000000000002";
const THIRD = "01a0f016-0000-7000-8000-000000000003";

function item(id: string, actions: Case["actions"]): Case {
  return { id, actions } as Case;
}

beforeEach(() => {
  lists.open = [];
  lists.decided = [];
});

describe("getCase", () => {
  it("offers no next case when the only other open case is not this moderator's to decide", async () => {
    lists.open = [item(THIS, ["approve", "reject"]), item(OTHER, [])];
    expect(await getCase(THIS)).toEqual({ kind: "ok", data: { item: lists.open[0], nextId: null } });
  });

  it("offers the oldest other case this moderator can decide", async () => {
    lists.open = [item(OTHER, []), item(THIS, ["reject"]), item(THIRD, ["approve", "reject"])];
    expect(await getCase(THIS)).toEqual({ kind: "ok", data: { item: lists.open[1], nextId: THIRD } });
  });

  it("finds a decided case in the decided list, and nothing for an unknown one", async () => {
    lists.open = [item(OTHER, ["approve", "reject"])];
    lists.decided = [item(THIS, [])];
    expect(await getCase(THIS)).toEqual({ kind: "ok", data: { item: lists.decided[0], nextId: OTHER } });
    expect(await getCase(THIRD)).toEqual({ kind: "ok", data: { item: null, nextId: OTHER } });
  });
});
