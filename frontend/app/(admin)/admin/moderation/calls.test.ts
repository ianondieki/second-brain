import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "@/lib/api/client";

import { decideCase } from "./calls";

// REQ-MOD-01: the decision goes to the case's decision route with the version the page shows, through the
// CSRF-aware typed client; whatever happens, the screen gets data or a refusal, never a thrown error.

const CASE_ID = "01a0f016-2e64-7294-9e44-77fa421dce09";
const VERSION = "01a0f014-b507-70d8-9f0e-4097336a5fb0";

function fakeApi(answer: () => Response) {
  const seen: Request[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(new URL(String(input instanceof Request ? input.url : input), "http://web.test"), init);
    seen.push(input instanceof Request ? input : request);
    if (request.url.endsWith("/api/auth/csrf")) return Response.json({ csrf_token: "tok" });
    return answer();
  });
  return { seen, client: createApiClient({ baseUrl: "http://web.test", fetch: fetchImpl }) };
}

describe("decideCase", () => {
  it("posts the decision and the version reviewed to the case's decision route", async () => {
    const { seen, client } = fakeApi(() => Response.json({ id: CASE_ID, status: "approved", subject_state: "clear" }));
    const outcome = await decideCase(CASE_ID, "approve", VERSION, client);
    expect(outcome).toEqual({ ok: true, data: { id: CASE_ID, status: "approved", subject_state: "clear" } });
    const post = seen.find((request) => request.method === "POST")!;
    expect(post.url).toBe(`http://web.test/api/admin/moderation/cases/${CASE_ID}/decision`);
    expect(post.headers.get("X-CSRF-Token")).toBe("tok");
    expect(await post.json()).toEqual({ decision: "approve", subject_version_id: VERSION });
  });

  it("sends a null version for a problem", async () => {
    const { seen, client } = fakeApi(() =>
      Response.json({ id: CASE_ID, status: "rejected", subject_state: "rejected" }),
    );
    await decideCase(CASE_ID, "reject", null, client);
    const post = seen.find((request) => request.method === "POST")!;
    expect(await post.json()).toEqual({ decision: "reject", subject_version_id: null });
  });

  it("settles a refusal from its code, never its message", async () => {
    const { client } = fakeApi(() =>
      Response.json(
        { detail: { code: "case_changed", message: "The author published a new version." } },
        { status: 409 },
      ),
    );
    expect(await decideCase(CASE_ID, "approve", VERSION, client)).toEqual({ ok: false, refusal: { kind: "changed" } });
  });

  it("settles a thrown fetch as the generic refusal", async () => {
    const client = createApiClient({ fetch: async () => Promise.reject(new TypeError("offline")) });
    expect(await decideCase(CASE_ID, "approve", VERSION, client)).toEqual({
      ok: false,
      refusal: { kind: "refusal", code: "generic" },
    });
  });
});
