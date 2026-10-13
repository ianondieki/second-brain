import { beforeEach, describe, expect, it, vi } from "vitest";

import { withCsrf } from "./csrf";
import { DEMO_SIGN_IN_PATH, demoSignIn } from "./demo-sign-in";

// REQ-FND-04: POST /api/auth/demo/sign-in is not in the API's schema (it exists only in the public demo), so a small
// helper sends it, with the double-submit CSRF header exactly as the typed client sends every POST.

const ORIGIN = "http://web.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const SESSION = { user: { id: "u1", email: "owner@telco-a.example" }, mfa_required: false };

const network = vi.fn<(request: Request) => Promise<Response>>();
/** withCsrf over the fake network, at an absolute origin (Node's Request takes no relative URL). */
const csrfSend = withCsrf((input, init) => network(new Request(input, init)), `${ORIGIN}/api/auth/csrf`);
const send = (input: RequestInfo | URL, init?: RequestInit) => csrfSend(new URL(String(input), ORIGIN), init);

beforeEach(() => {
  network.mockReset();
  document.cookie = "bridge_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("demoSignIn", () => {
  it("POSTs {persona} as JSON to the demo route with the CSRF token, and answers the session", async () => {
    network.mockImplementation(async (request) =>
      new URL(request.url).pathname === "/api/auth/csrf" ? json({ csrf_token: "tok-9" }) : json(SESSION),
    );
    expect(await demoSignIn("grace", send)).toEqual({ ok: true, data: SESSION });
    const post = network.mock.calls.map(([request]) => request).find((request) => request.method === "POST")!;
    expect(new URL(post.url).pathname).toBe(DEMO_SIGN_IN_PATH);
    expect(post.headers.get("X-CSRF-Token")).toBe("tok-9");
    expect(post.headers.get("Content-Type")).toBe("application/json");
    expect(post.credentials).toBe("same-origin");
    expect(await post.json()).toEqual({ persona: "grace" });
  });

  it("retries once with a fresh token after 403 csrf_failed, as the typed client does", async () => {
    document.cookie = "bridge_csrf=stale";
    let posts = 0;
    network.mockImplementation(async (request) => {
      if (new URL(request.url).pathname === "/api/auth/csrf") return json({ csrf_token: "fresh" });
      posts += 1;
      return posts === 1 ? json({ detail: { code: "csrf_failed", message: "x" } }, 403) : json(SESSION);
    });
    expect(await demoSignIn("amina", send)).toEqual({ ok: true, data: SESSION });
    const tokens = network.mock.calls.map(([r]) => r).filter((r) => r.method === "POST").map((r) => r.headers.get("X-CSRF-Token"));
    expect(tokens).toEqual(["stale", "fresh"]);
  });

  it("answers the status of a refusal, and 0 when the request did not complete", async () => {
    network.mockImplementation(async (request) =>
      new URL(request.url).pathname === "/api/auth/csrf" ? json({ csrf_token: "t" }) : json({ detail: { code: "too_many_attempts" } }, 429),
    );
    expect(await demoSignIn("rita", send)).toEqual({ ok: false, status: 429 });
    expect(await demoSignIn("rita", async () => Promise.reject(new TypeError("offline")))).toEqual({ ok: false, status: 0 });
    expect(await demoSignIn("rita", async () => new Response("not json", { status: 200 }))).toEqual({ ok: false, status: 200 });
  });
});
