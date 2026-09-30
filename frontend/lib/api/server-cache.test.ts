import { beforeEach, describe, expect, it, vi } from "vitest";

// getMe (lib/api/server.ts) is cached per request with React.cache (P16-D, REQ-UX-03): a page, its layout and the parts
// they render share one GET /api/auth/me. React's client build (this jsdom run) does not memoise `cache`, so the test
// stands in for one server request with a memoising `cache`, as React's server build gives each request.

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  cache: <A extends unknown[], R>(fn: (...args: A) => R) => {
    const memo = new Map<string, R>();
    return (...args: A): R => {
      const key = JSON.stringify(args);
      if (!memo.has(key)) memo.set(key, fn(...args));
      return memo.get(key)!;
    };
  },
}));
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: (name: string) => (name === "__Host-bridge_session" ? { value: "a".repeat(43) } : undefined) }),
  headers: async () => new Headers(),
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));

const ME = {
  side: "developer",
  mfa: { enrolled: true, verified: true, required: false },
  user: { id: "u1", staff_role: null },
  memberships: [],
};

describe("getMe, one request", () => {
  const fetch = vi.fn(async () => new Response(JSON.stringify(ME), { status: 200, headers: { "content-type": "application/json" } }));

  beforeEach(() => {
    vi.stubEnv("COOKIE_SECURE", "true");
    fetch.mockClear();
    vi.stubGlobal("fetch", fetch);
  });

  it("reads /api/auth/me once however many parts ask (getMe, requireMe, getSignedIn)", async () => {
    const { getMe, getSignedIn, requireMe } = await import("./server");
    const [a, b, c] = await Promise.all([getMe(), requireMe(), getSignedIn()]);
    await requireMe();
    expect(a).toEqual(ME);
    expect(b).toEqual(ME);
    expect(c).toEqual(ME);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [request] = fetch.mock.calls[0] as unknown as [Request];
    expect(request.url).toContain("/api/auth/me");
  });
});
