import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCase } from "./data";
import type { Case } from "./moderation";

// REQ-MOD-01: the case page reads its case by id (open or decided, wherever it falls in the queue, which stops at 200)
// and "Review the next case" goes only to an open case this moderator can decide.

const api = vi.hoisted(() => ({
  open: [] as unknown[],
  cases: new Map<string, unknown>(),
  queueStatus: 200,
  caseStatus: 0, // 0: 200 with the case when it exists, else 404
  paths: [] as string[],
}));
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
    GET: async (
      path: string,
      options: { params: { query?: { decided: boolean }; path?: { case_id: string } } },
    ) => {
      api.paths.push(options.params.query?.decided ? `${path}?decided` : path);
      if (path === "/api/admin/moderation/cases/{case_id}") {
        const found = api.cases.get(options.params.path?.case_id ?? "");
        const status = api.caseStatus || (found ? 200 : 404);
        if (status === 200) return { data: found, response: new Response(null, { status }) };
        return { error: { detail: { code: "not_found", message: "x" } }, response: new Response(null, { status }) };
      }
      if (api.queueStatus !== 200) {
        return {
          error: { detail: { code: "step_up_required", message: "x" } },
          response: new Response(null, { status: api.queueStatus }),
        };
      }
      return { data: { items: api.open }, response: new Response(null, { status: 200 }) };
    },
  }),
}));

const THIS = "01a0f016-0000-7000-8000-000000000001";
const OTHER = "01a0f016-0000-7000-8000-000000000002";
const THIRD = "01a0f016-0000-7000-8000-000000000003";

function item(id: string, actions: Case["actions"]): Case {
  return { id, actions } as Case;
}

function known(...cases: Case[]) {
  for (const one of cases) api.cases.set(one.id, one);
}

beforeEach(() => {
  api.open = [];
  api.cases.clear();
  api.queueStatus = 200;
  api.caseStatus = 0;
  api.paths = [];
});

describe("getCase", () => {
  it("offers no next case when the only other open case is not this moderator's to decide", async () => {
    api.open = [item(THIS, ["approve", "reject"]), item(OTHER, [])];
    known(item(THIS, ["approve", "reject"]));
    expect(await getCase(THIS)).toEqual({ kind: "ok", data: { item: api.open[0], nextId: null } });
  });

  it("offers the oldest other case this moderator can decide", async () => {
    api.open = [item(OTHER, []), item(THIS, ["reject"]), item(THIRD, ["approve", "reject"])];
    known(item(THIS, ["reject"]));
    expect(await getCase(THIS)).toEqual({ kind: "ok", data: { item: api.open[1], nextId: THIRD } });
  });

  it("opens a case beyond the queue's first 200 by its id", async () => {
    api.open = Array.from({ length: 200 }, (_, n) =>
      item(`01a0f016-0000-7000-8000-${String(n + 10).padStart(12, "0")}`, n === 0 ? [] : ["approve", "reject"]),
    );
    known(item(THIS, ["approve", "reject"]));
    const loaded = await getCase(THIS);
    expect(loaded).toEqual({
      kind: "ok",
      data: { item: item(THIS, ["approve", "reject"]), nextId: (api.open[1] as Case).id },
    });
  });

  it("reads a decided case by its id, never the decided list, and nothing for an unknown one", async () => {
    api.open = [item(OTHER, ["approve", "reject"])];
    known(item(THIS, []));
    expect(await getCase(THIS)).toEqual({ kind: "ok", data: { item: item(THIS, []), nextId: OTHER } });
    expect(await getCase(THIRD)).toEqual({ kind: "ok", data: { item: null, nextId: OTHER } });
    expect(api.paths).not.toContain("/api/admin/moderation/cases?decided");
    expect(api.paths.filter((path) => path.endsWith("{case_id}"))).toHaveLength(2);
  });

  it("lets the queue's answer settle access", async () => {
    known(item(THIS, []));
    api.queueStatus = 403;
    expect(await getCase(THIS)).toEqual({ kind: "stepUp" });
    api.queueStatus = 404;
    await expect(getCase(THIS)).rejects.toThrow("notFound");
  });

  it("fails loudly when the case read fails", async () => {
    api.open = [item(OTHER, ["approve", "reject"])];
    api.caseStatus = 500;
    await expect(getCase(THIS)).rejects.toThrow("GET /api/admin/moderation/cases/{case_id} answered 500");
  });
});
