import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// appNow (lib/api/server.ts; P23-3, REQ-TRACK-03): the page's countdowns count from the app clock the API stamps on
// every response (X-App-Now), read once per request; an API that does not send it leaves the server's own clock,
// never the browser's. React's client build (this jsdom run) does not memoise `cache`, so the test stands in for one
// server request with a memoising `cache`, as React's server build gives each request (as server-cache.test.ts does).

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
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }), headers: async () => new Headers() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

const answer = (stamp?: string) =>
  new Response("{}", { status: 200, headers: { "content-type": "application/json", ...(stamp ? { "x-app-now": stamp } : {}) } });

beforeEach(() => vi.resetModules()); // each test is a fresh request
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("appNow, the app clock for one request", () => {
  it("is the X-App-Now instant of the request's API calls, the first one kept", async () => {
    const stamps = ["2026-10-20T07:00:00Z", "2026-10-20T07:00:01Z"];
    vi.stubGlobal("fetch", vi.fn(async () => answer(stamps.shift())));
    const { appNow, serverApi } = await import("./server");
    await serverApi().GET("/api/consents");
    await serverApi().GET("/api/consents");
    expect(appNow()).toBe("2026-10-20T07:00:00.000Z");
  });

  it("ignores a stamp that is not an instant", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => answer("soon")));
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-07T09:00:00Z"));
    const { appNow, serverApi } = await import("./server");
    await serverApi().GET("/api/consents");
    expect(appNow()).toBe("2026-10-07T09:00:00.000Z");
  });

  it("falls back to this server's clock when the API sends none, fixed for the rest of the request", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => answer()));
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-07T09:00:00Z"));
    const { appNow, serverApi } = await import("./server");
    await serverApi().GET("/api/consents");
    expect(appNow()).toBe("2026-10-07T09:00:00.000Z");
    vi.setSystemTime(new Date("2026-10-07T09:05:00Z"));
    expect(appNow()).toBe("2026-10-07T09:00:00.000Z");
  });
});
