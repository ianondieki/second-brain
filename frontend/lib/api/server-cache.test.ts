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

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

/** The paths the server asked the API for, in order. */
function asked(fetch: { mock: { calls: unknown[][] } }): string[] {
  return fetch.mock.calls.map(([request]) => new URL((request as Request).url).pathname);
}

describe("getMe, one request", () => {
  // requireMe also starts the bell's unread count beside /api/auth/me (P19-C): that one is answered here too.
  const fetch = vi.fn(async (request: Request) =>
    new URL(request.url).pathname.endsWith("/unread-count") ? json({ count: 3 }) : json(ME),
  );

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
    expect(asked(fetch).filter((path) => path === "/api/auth/me")).toHaveLength(1);
  });

  it("reads the bell's unread count once per request, started with /api/auth/me (P19-C)", async () => {
    vi.resetModules(); // a fresh request: nothing memoised yet
    const { getUnreadCount, requireMe } = await import("./server");
    await requireMe();
    expect(await getUnreadCount()).toBe(3);
    expect(await getUnreadCount()).toBe(3);
    expect(asked(fetch).filter((path) => path === "/api/me/notifications/unread-count")).toHaveLength(1);
  });
});

describe("getUnreadCount, never in the way", () => {
  beforeEach(() => vi.stubEnv("COOKIE_SECURE", "true"));

  it("answers null when the API fails or does not answer, so the bell shows no count", async () => {
    vi.resetModules();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    expect(await (await import("./server")).getUnreadCount()).toBeNull();
    vi.resetModules();
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fetch failed"))));
    expect(await (await import("./server")).getUnreadCount()).toBeNull();
  });
});
