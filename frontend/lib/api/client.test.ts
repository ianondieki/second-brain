import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CSRF_COOKIE, CSRF_HEADER, createApiClient, ensureCsrf, isCsrfFailure, readCookie } from "./client";

const BASE = "http://api.test";
const CSRF_URL = `${BASE}/api/auth/csrf`;

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

// A __Host- cookie must be Secure, which jsdom's http test page would refuse to store, so these tests stand in for
// document.cookie with exactly what a browser page would read.
let jar = "";
function setCsrfCookie(value: string) {
  jar = `${CSRF_COOKIE}=${value}`;
}

function clearCsrfCookie() {
  jar = "";
}

beforeEach(() => {
  Object.defineProperty(document, "cookie", { configurable: true, get: () => jar, set: () => {} });
});

interface Seen {
  method: string;
  url: string;
  csrf: string | null;
  body: string;
}

/** A fake API: records every request and answers from a queue per "METHOD url". */
function fakeApi(answers: Record<string, Array<() => Response>>) {
  const seen: Seen[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(String(input), init);
    seen.push({
      method: request.method,
      url: request.url,
      csrf: request.headers.get(CSRF_HEADER),
      body: await request.text(),
    });
    const queue = answers[`${request.method} ${request.url}`];
    const next = queue?.shift();
    if (!next) throw new Error(`unexpected ${request.method} ${request.url}`);
    return next();
  });
  return { fetchMock, seen };
}

beforeEach(() => clearCsrfCookie());
afterEach(() => clearCsrfCookie());

describe("readCookie", () => {
  it("finds a cookie among others and decodes it", () => {
    expect(readCookie("__Host-bridge_csrf", "a=1; __Host-bridge_csrf=abc%3D.def; b=2")).toBe("abc=.def");
  });

  it("treats a cookie that cannot be decoded as absent instead of throwing", () => {
    expect(readCookie("bridge_csrf", "bridge_csrf=%E0%A4%A")).toBeUndefined();
    expect(readCookie("__Host-bridge_csrf", "__Host-bridge_csrf=%zz; other=1")).toBeUndefined();
  });

  it("returns undefined when the cookie is absent", () => {
    expect(readCookie("__Host-bridge_csrf", "a=1")).toBeUndefined();
  });

  it("uses the __Host- prefixed name the API sets", () => {
    expect(CSRF_COOKIE).toBe("__Host-bridge_csrf");
  });
});

describe("ensureCsrf", () => {
  it("fetches a fresh token when the cookie is malformed (self-heals instead of failing the login)", async () => {
    jar = "__Host-bridge_csrf=%E0%A4%A";
    const { fetchMock, seen } = fakeApi({ [`GET ${CSRF_URL}`]: [() => json(200, { csrf_token: "fresh" })] });
    await expect(ensureCsrf({ fetch: fetchMock, url: CSRF_URL })).resolves.toBe("fresh");
    expect(seen.map((r) => r.method)).toEqual(["GET"]);
  });

  it("uses the plain-http dev cookie name too, without a request", async () => {
    jar = "bridge_csrf=from-dev-cookie";
    const { fetchMock } = fakeApi({});
    await expect(ensureCsrf({ fetch: fetchMock, url: CSRF_URL })).resolves.toBe("from-dev-cookie");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses the cookie when it is present, without a request", async () => {
    setCsrfCookie("from-cookie");
    const { fetchMock } = fakeApi({});
    await expect(ensureCsrf({ fetch: fetchMock, url: CSRF_URL })).resolves.toBe("from-cookie");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("asks GET /api/auth/csrf once when the cookie is missing, even for concurrent callers", async () => {
    const { fetchMock, seen } = fakeApi({ [`GET ${CSRF_URL}`]: [() => json(200, { csrf_token: "fresh" })] });
    const [a, b] = await Promise.all([
      ensureCsrf({ fetch: fetchMock, url: CSRF_URL }),
      ensureCsrf({ fetch: fetchMock, url: CSRF_URL }),
    ]);
    expect([a, b]).toEqual(["fresh", "fresh"]);
    expect(seen.map((r) => `${r.method} ${r.url}`)).toEqual([`GET ${CSRF_URL}`]);
  });

  it("asks again when forced, even with a cookie", async () => {
    setCsrfCookie("stale");
    const { fetchMock } = fakeApi({ [`GET ${CSRF_URL}`]: [() => json(200, { csrf_token: "fresh" })] });
    await expect(ensureCsrf({ fetch: fetchMock, url: CSRF_URL, force: true })).resolves.toBe("fresh");
  });
});

describe("isCsrfFailure", () => {
  it("is true only for 403 with code csrf_failed", async () => {
    expect(await isCsrfFailure(json(403, { detail: { code: "csrf_failed", message: "x" } }))).toBe(true);
    expect(await isCsrfFailure(json(403, { detail: { code: "forbidden", message: "x" } }))).toBe(false);
    expect(await isCsrfFailure(json(401, { detail: { code: "csrf_failed" } }))).toBe(false);
    expect(await isCsrfFailure(new Response("not json", { status: 403 }))).toBe(false);
  });
});

describe("api client CSRF handling", () => {
  const LOGIN = `${BASE}/api/auth/login`;
  const body = { email: "wanjiru@example.test", password: "a long enough password" };

  it("sends the cookie's token on state-changing requests", async () => {
    setCsrfCookie("tok-1");
    const { fetchMock, seen } = fakeApi({
      [`POST ${LOGIN}`]: [() => json(200, { mfa_required: false, user: {} })],
    });
    const { response } = await createApiClient({ baseUrl: BASE, fetch: fetchMock }).POST("/api/auth/login", { body });
    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0].csrf).toBe("tok-1");
  });

  it("reads the cookie on every request, so rotated cookies (after mfa/verify) are used at once", async () => {
    setCsrfCookie("before-rotation");
    const verify = `${BASE}/api/auth/mfa/verify`;
    const { fetchMock, seen } = fakeApi({
      [`POST ${verify}`]: [() => json(200, { mfa_required: false, user: {} })],
      [`POST ${BASE}/api/auth/logout`]: [() => new Response(null, { status: 204 })],
    });
    const client = createApiClient({ baseUrl: BASE, fetch: fetchMock });
    await client.POST("/api/auth/mfa/verify", { body: { code: "123456" } });
    setCsrfCookie("after-rotation"); // what the verify response's Set-Cookie does in a browser
    await client.POST("/api/auth/logout");
    expect(seen.map((r) => r.csrf)).toEqual(["before-rotation", "after-rotation"]);
  });

  it("fetches a token first when the cookie is missing", async () => {
    const { fetchMock, seen } = fakeApi({
      [`GET ${CSRF_URL}`]: [() => json(200, { csrf_token: "tok-new" })],
      [`POST ${LOGIN}`]: [() => json(200, { mfa_required: false, user: {} })],
    });
    await createApiClient({ baseUrl: BASE, fetch: fetchMock }).POST("/api/auth/login", { body });
    expect(seen.map((r) => r.method)).toEqual(["GET", "POST"]);
    expect(seen[1].csrf).toBe("tok-new");
  });

  it("leaves safe requests alone", async () => {
    const { fetchMock, seen } = fakeApi({ [`GET ${BASE}/api/auth/me`]: [() => json(401, { detail: {} })] });
    await createApiClient({ baseUrl: BASE, fetch: fetchMock }).GET("/api/auth/me");
    expect(seen).toHaveLength(1);
    expect(seen[0].csrf).toBeNull();
  });

  it("retries once with a fresh token and the same body after 403 csrf_failed", async () => {
    setCsrfCookie("stale");
    const { fetchMock, seen } = fakeApi({
      [`POST ${LOGIN}`]: [
        () => json(403, { detail: { code: "csrf_failed", message: "Refresh the page and try again." } }),
        () => json(200, { mfa_required: true, user: {} }),
      ],
      [`GET ${CSRF_URL}`]: [() => json(200, { csrf_token: "fresh" })],
    });
    const { data, response } = await createApiClient({ baseUrl: BASE, fetch: fetchMock }).POST("/api/auth/login", {
      body,
    });
    expect(response.status).toBe(200);
    expect(data?.mfa_required).toBe(true);
    expect(seen.map((r) => `${r.method} ${r.csrf ?? "-"}`)).toEqual(["POST stale", "GET -", "POST fresh"]);
    expect(JSON.parse(seen[2].body)).toEqual(body);
    expect(seen[2].body).toBe(seen[0].body);
  });

  it("does not retry a second time", async () => {
    setCsrfCookie("stale");
    const refused = () => json(403, { detail: { code: "csrf_failed", message: "x" } });
    const { fetchMock, seen } = fakeApi({
      [`POST ${LOGIN}`]: [refused, refused],
      [`GET ${CSRF_URL}`]: [() => json(200, { csrf_token: "fresh" })],
    });
    const { error, response } = await createApiClient({ baseUrl: BASE, fetch: fetchMock }).POST("/api/auth/login", {
      body,
    });
    expect(response.status).toBe(403);
    expect(error).toEqual({ detail: { code: "csrf_failed", message: "x" } });
    expect(seen).toHaveLength(3);
  });

  it("does not retry other 403 answers", async () => {
    setCsrfCookie("tok");
    const { fetchMock, seen } = fakeApi({
      [`POST ${LOGIN}`]: [() => json(403, { detail: { code: "email_unverified", message: "x" } })],
    });
    await createApiClient({ baseUrl: BASE, fetch: fetchMock }).POST("/api/auth/login", { body });
    expect(seen).toHaveLength(1);
  });
});
