// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { publicActivity, publicExplore } from "./public-data";

// P24: the public summaries are null when the API cannot answer (the landing then leaves its ticker out and Explore
// shows its empty state); the visitor's address is forwarded and no session cookie is sent.

const forward = vi.hoisted(() => vi.fn(async () => ({ "x-forwarded-for": "198.51.100.7" })));
vi.mock("@/lib/api/server", () => ({ forwardHeaders: forward }));

afterEach(() => vi.unstubAllGlobals());

const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

describe("the public summaries", () => {
  it("read the two routes without a session", async () => {
    const fetch = vi.fn(async (url: string) => ok(url.endsWith("activity") ? { generated_at: "x", seeded: true, items: [{ id: "a" }] } : { totals: {}, counties: [], niches: [] }));
    vi.stubGlobal("fetch", fetch);
    expect((await publicActivity())?.items).toHaveLength(1);
    expect((await publicExplore())?.counties).toEqual([]);
    expect(fetch.mock.calls.map(([url]) => new URL(url).pathname)).toEqual(["/api/public/activity", "/api/public/explore"]);
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

  it("leave an empty feed out", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ generated_at: "x", seeded: true, items: [] })));
    expect(await publicActivity()).toBeNull();
  });
});
