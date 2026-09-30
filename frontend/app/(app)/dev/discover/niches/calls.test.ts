import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";

import { saveNiches, setProfiling } from "./calls";

// REQ-PERS-01, REQ-PERS-03 (P12-F): the browser's calls on the liked-niches page, against a fake client: what each
// sends, and how each answer settles.

type Put = (path: string, options: { body: unknown }) => Promise<{ data?: unknown; error?: unknown; response: Response }>;

function client(put: Put): ApiClient {
  return { PUT: vi.fn(put) } as unknown as ApiClient;
}
const ok = (data: unknown) => async () => ({ data, response: new Response(null, { status: 200 }) });
const refused = (status: number, error: unknown) => async () => ({ error, response: new Response(null, { status }) });

const CONSENTS = [
  { purpose: "marketing", granted: false, text: "Send me news.", version: "v3" },
  { purpose: "profiling", granted: true, text: "Use my niches and activity to recommend problems.", version: "v3" },
];

describe("setProfiling", () => {
  it("sends only the profiling decision on the version shown, and reads it back from the 200 list", async () => {
    const fake = client(ok(CONSENTS));
    await expect(setProfiling(true, "v3", fake)).resolves.toEqual({ ok: true, value: CONSENTS[1] });
    expect(fake.PUT).toHaveBeenCalledWith("/api/me/consents", { body: { profiling: { granted: true, version: "v3" } } });
  });

  it("asks for a reload on 409 consent_text_changed, and fails on a 200 without the profiling item", async () => {
    const changed = client(refused(409, { detail: { code: "consent_text_changed", message: "The wording changed." } }));
    await expect(setProfiling(false, "v2", changed)).resolves.toEqual({ ok: false, problem: "changed" });
    await expect(setProfiling(true, "v3", client(ok([CONSENTS[0]])))).resolves.toEqual({ ok: false, problem: "failed" });
  });

  it("is network when the fetch throws", async () => {
    const offline = client(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(setProfiling(true, "v3", offline)).resolves.toEqual({ ok: false, problem: "network" });
  });
});

describe("saveNiches", () => {
  it("sends the whole list and gives back what the API kept", async () => {
    const kept = { liked: [{ id: "a", slug: "a", label: "A" }], min: 3, max: 5 };
    const fake = client(ok(kept));
    await expect(saveNiches(["a", "b", "c"], fake)).resolves.toEqual({ ok: true, value: kept });
    expect(fake.PUT).toHaveBeenCalledWith("/api/me/niches", { body: { liked: ["a", "b", "c"] } });
  });

  it("settles the API's refusals into their fixed sentences' keys", async () => {
    const count = client(refused(422, { detail: { code: "liked_niches_count", message: "Choose 3 to 5 niches you like." } }));
    await expect(saveNiches(["a"], count)).resolves.toEqual({ ok: false, problem: "count" });
    const unknown = client(refused(422, { detail: { code: "unknown_niche", message: "x", niches: ["z"] } }));
    await expect(saveNiches(["a", "b", "z"], unknown)).resolves.toEqual({ ok: false, problem: "unknown" });
  });
});
