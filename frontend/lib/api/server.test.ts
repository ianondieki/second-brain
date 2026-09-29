import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// forwardHeaders (lib/api/server.ts): what a server-side API call forwards for the current request.

const mocks = vi.hoisted(() => ({ cookies: new Map<string, string>(), headers: new Headers() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (mocks.cookies.has(name) ? { value: mocks.cookies.get(name) } : undefined),
  }),
  headers: async () => mocks.headers,
}));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

const { forwardHeaders } = await import("./server");

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
