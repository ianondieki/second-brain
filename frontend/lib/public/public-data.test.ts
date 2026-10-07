// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { nicheLabel, publicActivity, publicExplore, publicProblem } from "./public-data";

// P24: the public reads. A failed summary is null (the landing then leaves its ticker out and Explore shows its empty
// state); an activity kind this page does not know is skipped; a problem read says found, not found or unavailable.
// The visitor's address is forwarded and no session cookie is sent.

const forward = vi.hoisted(() => vi.fn(async () => ({ "x-forwarded-for": "198.51.100.7" })));
vi.mock("@/lib/api/server", async () => {
  const { default: createClient } = await import("openapi-fetch");
  return { forwardHeaders: forward, serverApi: () => createClient({ baseUrl: "http://api.test", fetch: (r: Request) => globalThis.fetch(r) }) };
});

afterEach(() => vi.unstubAllGlobals());

const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
const item = (id: string, kind: string) => ({ id, kind, at: "2026-10-07T07:00:00Z", county: null, niche: null, title: null, stage: null, seeded: true });
const UUID = "0199b000-0000-7000-8000-0000000000aa";

describe("the public reads", () => {
  it("read the routes without a session, and skip an activity kind the page does not know", async () => {
    const fetch = vi.fn(async (request: Request) =>
      ok(new URL(request.url).pathname.endsWith("activity")
        ? { generated_at: "x", seeded: true, items: [item("a", "problem_posted"), item("b", "stage_reached"), item("c", "brief_opened")] }
        : { seeded: false, totals: {}, counties: [], niches: [] }),
    );
    vi.stubGlobal("fetch", fetch);
    expect((await publicActivity())?.items.map((i) => i.id)).toEqual(["a", "c"]);
    expect((await publicExplore())?.counties).toEqual([]);
    const requests = fetch.mock.calls.map(([request]) => request as Request);
    expect(requests.map((r) => new URL(r.url).pathname)).toEqual(["/api/public/activity", "/api/public/explore"]);
    expect(requests.every((r) => r.headers.get("cookie") === null)).toBe(true);
    expect(forward).toHaveBeenCalledWith({ session: false });
  });

  it.each([
    ["an error status", async () => new Response("{}", { status: 503 })],
    ["a network failure", async () => Promise.reject(new TypeError("fetch failed"))],
    ["a body of the wrong shape", async () => ok({ detail: "no" })],
  ])("are null on %s", async (_, answer) => {
    vi.stubGlobal("fetch", vi.fn(answer));
    expect(await publicActivity()).toBeNull();
    expect(await publicExplore()).toBeNull();
  });

  it("leave a feed with nothing the page can say out", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ generated_at: "x", seeded: true, items: [item("b", "stage_reached")] })));
    expect(await publicActivity()).toBeNull();
  });

  it("read one problem: found, not found (404, or no request for an id that cannot be one), unavailable", async () => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async () => ok({ id: UUID, title: "T" }));
    vi.stubGlobal("fetch", fetch);
    expect(await publicProblem(UUID)).toEqual({ kind: "found", problem: { id: UUID, title: "T" } });
    expect(new URL(fetch.mock.calls[0][0].url).pathname).toBe(`/api/public/problems/${UUID}`);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
    expect(await publicProblem(UUID)).toEqual({ kind: "notFound" });
    const none = vi.fn();
    vi.stubGlobal("fetch", none);
    expect(await publicProblem("../me")).toEqual({ kind: "notFound" });
    expect(none).not.toHaveBeenCalled();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 503 })));
    expect(await publicProblem(UUID)).toEqual({ kind: "unavailable" });
  });

  it("label a niche with its parent", () => {
    expect(nicheLabel({ id: "n", name: "Networks", parent: { id: "p", name: "ICT" } })).toBe("ICT › Networks");
    expect(nicheLabel({ id: "n", name: "Health", parent: null })).toBe("Health");
    expect(nicheLabel(null)).toBeNull();
  });
});
