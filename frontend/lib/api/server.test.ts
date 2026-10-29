import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// forwardHeaders (lib/api/server.ts): what a server-side API call forwards for the current request.

const mocks = vi.hoisted(() => ({ cookies: new Map<string, string>(), headers: new Headers() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (mocks.cookies.has(name) ? { value: mocks.cookies.get(name) } : undefined),
  }),
  headers: async () => mocks.headers,
}));
const redirect = vi.hoisted(() =>
  vi.fn((to: string) => {
    throw new Error(`redirect:${to}`);
  }),
);
vi.mock("next/navigation", () => ({ redirect }));

const { forwardHeaders, requirePendingMfa } = await import("./server");

const TOKEN = "a".repeat(43); // secrets.token_urlsafe(32)

beforeEach(() => {
  vi.stubEnv("COOKIE_SECURE", "true");
  mocks.cookies.clear();
  mocks.headers = new Headers();
});
afterEach(() => vi.unstubAllEnvs());

describe("forwardHeaders", () => {
  it("forwards the session cookie and the visitor's address", async () => {
    mocks.cookies.set("__Host-bridge_session", TOKEN);
    mocks.headers.set("x-forwarded-for", "203.0.113.7, 10.0.0.2");
    expect(await forwardHeaders()).toEqual({
      cookie: `__Host-bridge_session=${TOKEN}`,
      "x-forwarded-for": "203.0.113.7, 10.0.0.2",
    });
  });

  it("leaves the cookie out of public calls (session: false)", async () => {
    mocks.cookies.set("__Host-bridge_session", TOKEN);
    mocks.headers.set("x-forwarded-for", "2001:db8::1");
    expect(await forwardHeaders({ session: false })).toEqual({ "x-forwarded-for": "2001:db8::1" });
  });

  it("sends nothing when signed out and no address came in", async () => {
    expect(await forwardHeaders()).toEqual({});
  });

  it.each([
    ["a hostname", "evil.example"],
    ["a second header smuggled in", "1.2.3.4\r\nX-Admin: 1"],
    ["a cookie", "1.2.3.4; bridge_session=x"],
    ["an overlong list", "1.2.3.4, ".repeat(60)],
  ])("drops an X-Forwarded-For with %s", async (_, value) => {
    // Headers refuses CR/LF itself; stub the getter so the pattern is what is tested.
    mocks.headers = { get: () => value } as unknown as Headers;
    expect(await forwardHeaders({ session: false })).toEqual({});
  });
});

// Reviewer MINOR 6 (P16-C1 fix round 1): /auth/mfa for someone already fully signed in.
describe("requirePendingMfa", () => {
  const me = (pending: boolean) => ({
    side: pending ? "pending" : "developer",
    mfa: { enrolled: true, verified: !pending, required: false },
    user: { staff_role: null },
  });
  function answer(body: unknown) {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } })));
  }
  afterEach(() => vi.unstubAllGlobals());

  it("sends a fully signed-in person to a safe return path, else home", async () => {
    mocks.cookies.set("__Host-bridge_session", TOKEN);
    answer(me(false));
    await expect(requirePendingMfa("/settings/notifications")).rejects.toThrow("redirect:/settings/notifications");
    await expect(requirePendingMfa("//evil.example")).rejects.toThrow("redirect:/dev");
    await expect(requirePendingMfa()).rejects.toThrow("redirect:/dev");
  });

  it("keeps a session that still owes its second factor on the page", async () => {
    mocks.cookies.set("__Host-bridge_session", TOKEN);
    answer(me(true));
    await expect(requirePendingMfa("/dev")).resolves.toMatchObject({ side: "pending" });
  });
});
