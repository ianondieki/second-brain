// @vitest-environment node
import { NextRequest } from "next/server";
import { getRedirectUrl, getRewrittenUrl, unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import nextConfig from "./next.config";
import { admitsStaff, config, isAdminPath, isSignedInPath, proxy, SIGNED_IN_PREFIXES, UNMATCHED_PATH } from "./proxy";

const answer = (status: number, body: unknown = {}) =>
  vi.fn<typeof fetch>(async () => new Response(JSON.stringify(body), { status }));

// REQ-ADM-01: only sessions the API admits to the staff console reach /admin; the rest get the unknown-address 404.
describe("admitsStaff", () => {
  it("admits staff, and staff whose second factor must be refreshed", async () => {
    expect(await admitsStaff("__Host-bridge_session=t", answer(200, { role: "admin" }))).toBe(true);
    expect(
      await admitsStaff("__Host-bridge_session=t", answer(403, { detail: { code: "step_up_required", message: "x" } })),
    ).toBe(true);
  });

  it("turns away everyone else, and fails closed", async () => {
    const none = answer(200);
    expect(await admitsStaff(undefined, none)).toBe(false);
    expect(none).not.toHaveBeenCalled();
    expect(await admitsStaff("c", answer(404, { detail: { code: "not_found" } }))).toBe(false);
    expect(await admitsStaff("c", answer(401))).toBe(false);
    expect(await admitsStaff("c", answer(403, { detail: { code: "forbidden" } }))).toBe(false);
    expect(await admitsStaff("c", answer(500))).toBe(false);
    expect(
      await admitsStaff(
        "c",
        vi.fn<typeof fetch>(async () => {
          throw new Error("offline");
        }),
      ),
    ).toBe(false);
  });

  it("forwards only the session cookie it was given", async () => {
    const fetchImpl = answer(200);
    await admitsStaff("__Host-bridge_session=tok", fetchImpl);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/admin\/me$/);
    expect(init?.headers).toEqual({ cookie: "__Host-bridge_session=tok" });
  });
});

// COOKIE_SECURE is unset in tests, so the session cookie is the __Host- one (lib/api/cookies.ts cookieSecure).
const TOKEN = "__Host-bridge_session=abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG";
const request = (path: string, cookie?: string) =>
  new NextRequest(`http://localhost:3000${path}`, cookie ? { headers: { cookie } } : undefined);
const passesOn = (response: Response) => response.headers.get("x-middleware-next") === "1";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

// P16-B: loading states make the signed-in portals stream, so a signed-out visit is redirected here, before rendering,
// with a real 307 (a presence check only; the page's requireMe still decides for a cookie it cannot use).
describe("signed-out visits to the signed-in portals", () => {
  const paths = [...SIGNED_IN_PREFIXES, "/dev/ideas/0199a000-0000-7000-8000-0000000000aa/edit", "/org/inbox"];

  it.each(paths)("send %s to /login with a 307 when there is no session cookie", async (path) => {
    const fetchImpl = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchImpl);
    const response = await proxy(request(path));
    expect(response.status).toBe(307);
    const location = new URL(getRedirectUrl(response)!);
    expect(`${location.origin}${location.pathname}`).toBe("http://localhost:3000/login");
    expect(location.searchParams.get("next")).toBe(path); // P16-C1: back to the page after signing in
    expect(fetchImpl).not.toHaveBeenCalled(); // no API call
  });

  it("carries the page and its query as the return path, and nothing unsafe", async () => {
    const response = await proxy(request("/dev/discover?view=projects&niche=dairy"));
    expect(getRedirectUrl(response)).toBe("http://localhost:3000/login?next=%2Fdev%2Fdiscover%3Fview%3Dprojects%26niche%3Ddairy");
    // A path the return-path rule refuses (an encoded character, a double slash) goes to /login without one.
    for (const path of ["/dev//evil.example", "/dev/%41", "/settings/notifications?x=//evil.example"]) {
      expect(getRedirectUrl(await proxy(request(path))), path).toBe("http://localhost:3000/login");
    }
  });

  it("lets a request with a session cookie through, without asking the API (the page decides)", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchImpl);
    for (const path of paths) expect(passesOn(await proxy(request(path, TOKEN))), path).toBe(true);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("treats a cookie that is not a session token like no cookie", async () => {
    expect((await proxy(request("/dev", "__Host-bridge_session=x"))).status).toBe(307);
  });

  it("covers the portals and below them only", () => {
    expect(isSignedInPath("/dev")).toBe(true);
    expect(isSignedInPath("/settings/security")).toBe(true);
    expect(isSignedInPath("/notifications")).toBe(true);
    expect(isSignedInPath("/developer")).toBe(false);
    expect(isSignedInPath("/Dev")).toBe(false);
    expect(isSignedInPath("/admin")).toBe(false);
  });
});

describe("the staff console, unchanged", () => {
  it("rewrites a signed-out visit to the unmatched address, without asking the API", async () => {
    const fetchImpl = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchImpl);
    const response = await proxy(request("/admin/moderation"));
    expect(getRewrittenUrl(response)).toBe(`http://localhost:3000${UNMATCHED_PATH}`);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("asks the API for a session, then lets staff through and rewrites everyone else", async () => {
    vi.stubGlobal("fetch", answer(200, { role: "admin" }));
    expect(passesOn(await proxy(request("/admin", TOKEN)))).toBe(true);
    vi.stubGlobal("fetch", answer(404, { detail: { code: "not_found" } }));
    expect(getRewrittenUrl(await proxy(request("/admin/claims", TOKEN)))).toBe(`http://localhost:3000${UNMATCHED_PATH}`);
  });
});

describe("where the proxy runs", () => {
  it("runs on the console and the signed-in portals, nested paths included", () => {
    for (const url of ["/admin", "/admin/claims/1", "/dev", "/dev/ideas/1/edit", "/org/inbox", "/billing/upgrade",
      "/settings/notifications", "/problems/1", "/notifications"]) {
      expect(unstable_doesMiddlewareMatch({ config, nextConfig, url }), url).toBe(true);
    }
  });

  // P28 (REQ-FND-04): the public demo's header goes on every page, so the proxy runs on the public pages too (and on
  // /robots.txt); the build assets, the image optimiser, the fonts and the API never reach it.
  it("runs on the public pages and /robots.txt, never on build assets, fonts or the API", () => {
    for (const url of ["/", "/login", "/signup", "/help", "/verify", "/verify/x", "/legal/terms", "/auth/mfa", "/robots.txt"]) {
      expect(unstable_doesMiddlewareMatch({ config, nextConfig, url }), url).toBe(true);
    }
    for (const url of ["/_next/static/chunks/a.js", "/_next/image?url=x", "/fonts/hanken-grotesk-v1.woff2", "/api/auth/me",
      "/api/public/demo"]) {
      expect(unstable_doesMiddlewareMatch({ config, nextConfig, url }), url).toBe(false);
    }
  });

  // What "never runs on public pages" guaranteed before P28, kept: with the mode off a public page is passed on
  // untouched (no redirect, no rewrite, no API call, no added header).
  it.each(["/", "/login", "/signup", "/help", "/verify", "/legal/terms", "/auth/mfa", "/developer", "/Admin", "/admin-x"])(
    "passes %s through untouched with the mode off, signed in or not",
    async (path) => {
      const fetchImpl = vi.fn<typeof fetch>();
      vi.stubGlobal("fetch", fetchImpl);
      for (const cookie of [undefined, TOKEN]) {
        const response = await proxy(request(path, cookie));
        expect(passesOn(response), path).toBe(true);
        expect(getRewrittenUrl(response)).toBeNull();
        expect(response.headers.get("x-robots-tag")).toBeNull();
      }
      expect(fetchImpl).not.toHaveBeenCalled();
    },
  );

  it("knows the console's paths exactly", () => {
    expect(isAdminPath("/admin")).toBe(true);
    expect(isAdminPath("/admin/moderation")).toBe(true);
    expect(isAdminPath("/admin-x")).toBe(false);
    expect(isAdminPath("/Admin")).toBe(false);
  });
});

describe("the public demo (REQ-FND-04, AT-PD-6)", () => {
  it("adds X-Robots-Tag: noindex, nofollow to every response while PUBLIC_DEMO is on", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    vi.stubGlobal("fetch", answer(404, { detail: { code: "not_found" } }));
    const pages = [
      await proxy(request("/")),
      await proxy(request("/login")),
      await proxy(request("/dev", TOKEN)),
      await proxy(request("/dev")), // the redirect to /login
      await proxy(request("/admin", TOKEN)), // the rewrite to the unmatched address
    ];
    for (const response of pages) expect(response.headers.get("x-robots-tag")).toBe("noindex, nofollow");
    expect(pages[3].status).toBe(307);
    expect(getRewrittenUrl(pages[4])).toBe(`http://localhost:3000${UNMATCHED_PATH}`);
  });

  it("reads the switch on each request, not once", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    expect((await proxy(request("/"))).headers.get("x-robots-tag")).toBe("noindex, nofollow");
    vi.stubEnv("PUBLIC_DEMO", "false");
    expect((await proxy(request("/"))).headers.get("x-robots-tag")).toBeNull();
  });

  it("serves a disallow-all /robots.txt while on", async () => {
    vi.stubEnv("PUBLIC_DEMO", "1");
    const response = await proxy(request("/robots.txt"));
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toMatch(/^text\/plain/);
    expect(await response.text()).toBe("User-agent: *\nDisallow: /\n");
    expect(passesOn(response)).toBe(false);
  });

  it("leaves /robots.txt to Next as before while off (today's 404)", async () => {
    const response = await proxy(request("/robots.txt"));
    expect(passesOn(response)).toBe(true);
    expect(response.headers.get("x-robots-tag")).toBeNull();
  });
});
