import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type ApiClient,
  CSRF_COOKIE,
  CSRF_HEADER,
  createApiClient,
  ensureCsrf,
  fillPath,
  isCsrfFailure,
  queryString,
  readCookie,
} from "./client";
import type { paths } from "./schema";

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

// createApiClient answers like openapi-fetch (whose types it uses), so settle() and every screen read it unchanged.
describe("api client requests and answers", () => {
  const ME = `${BASE}/api/auth/me`;

  function recording(answer: () => Response) {
    const requests: Request[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(String(input), init);
      requests.push(request);
      return answer();
    });
    return { client: createApiClient({ baseUrl: `${BASE}/`, fetch: fetchMock }), requests };
  }

  it("sends a JSON body with its content type, and a GET with neither", async () => {
    setCsrfCookie("tok");
    const post = recording(() => json(200, { mfa_required: false, user: {} }));
    await post.client.POST("/api/auth/login", { body: { email: "a@example.test", password: "a long password" } });
    expect(post.requests[0].url).toBe(`${BASE}/api/auth/login`);
    expect(post.requests[0].headers.get("Content-Type")).toBe("application/json");
    expect(await post.requests[0].json()).toEqual({ email: "a@example.test", password: "a long password" });
    expect(post.requests[0].credentials).toBe("same-origin");

    const get = recording(() => json(401, { detail: { code: "unauthenticated", message: "x" } }));
    await get.client.GET("/api/auth/me");
    expect(get.requests[0].url).toBe(ME);
    expect(get.requests[0].method).toBe("GET");
    expect(get.requests[0].headers.get("Content-Type")).toBeNull();
    expect(get.requests[0].body).toBeNull();
  });

  it("passes request headers and an abort signal through", async () => {
    const { client, requests } = recording(() => json(200, {}));
    const controller = new AbortController();
    await client.GET("/api/auth/me", { headers: { Accept: "application/json" }, signal: controller.signal });
    expect(requests[0].headers.get("Accept")).toBe("application/json");
    controller.abort();
    expect(requests[0].signal.aborted).toBe(true);
  });

  it("returns parsed data when ok", async () => {
    const { client } = recording(() => json(200, { csrf_token: "t" }));
    const { data, error, response } = await client.GET("/api/auth/me");
    expect(response.status).toBe(200);
    expect(data).toEqual({ csrf_token: "t" });
    expect(error).toBeUndefined();
  });

  it("returns neither data nor error for an empty answer (204, Content-Length 0, an empty body)", async () => {
    setCsrfCookie("tok");
    for (const answer of [
      () => new Response(null, { status: 204 }),
      () => new Response("", { status: 200, headers: { "Content-Length": "0" } }),
      () => new Response("", { status: 200 }),
    ]) {
      const { data, error, response } = await recording(answer).client.POST("/api/auth/logout");
      expect(response.ok).toBe(true);
      expect(data).toBeUndefined();
      expect(error).toBeUndefined();
    }
    const failed = await recording(() => new Response(null, { status: 503 })).client.GET("/api/auth/me");
    expect(failed.response.status).toBe(503);
    expect(failed.error).toBeUndefined();
    expect(failed.data).toBeUndefined();
  });

  it("returns the error body parsed as JSON, or as text when it is not JSON", async () => {
    const detail = { detail: { code: "rate_limited", message: "x" } };
    const asJson = await recording(() => json(429, detail)).client.GET("/api/auth/me");
    expect(asJson.error).toEqual(detail);
    expect(asJson.data).toBeUndefined();

    const asText = await recording(() => new Response("Bad gateway", { status: 502 })).client.GET("/api/auth/me");
    expect(asText.error).toBe("Bad gateway");
    expect(asText.response.status).toBe(502);
  });
});

describe("fillPath", () => {
  it("puts each value into its segment, percent-encoded", () => {
    expect(fillPath("/api/orgs/{org_id}", { org_id: "4f1c-9a" })).toBe("/api/orgs/4f1c-9a");
    expect(fillPath("/api/orgs/{org_id}", { org_id: "a/b c?d#e%f&g" })).toBe("/api/orgs/a%2Fb%20c%3Fd%23e%25f%26g");
    expect(fillPath("/api/orgs/{org_id}/members/{user_id}/roles", { user_id: "u 1", org_id: 7 })).toBe(
      "/api/orgs/7/members/u%201/roles",
    );
    expect(fillPath("/api/auth/me")).toBe("/api/auth/me");
  });

  it("refuses a missing or empty value, and . or .., instead of sending another path", () => {
    expect(() => fillPath("/api/orgs/{org_id}")).toThrow(/org_id/);
    for (const org_id of [undefined, null, "", ".", ".."]) {
      expect(() => fillPath("/api/orgs/{org_id}", { org_id }), String(org_id)).toThrow(TypeError);
    }
    expect(fillPath("/api/orgs/{org_id}", { org_id: "..." })).toBe("/api/orgs/...");
  });
});

describe("queryString", () => {
  it("repeats the key for each array item, encodes, and leaves out undefined and null", () => {
    expect(
      queryString({ niche: ["agri", "health tech"], cursor: undefined, after: null, q: "maji&safi=1", limit: 20 }),
    ).toBe("?niche=agri&niche=health%20tech&q=maji%26safi%3D1&limit=20");
    expect(queryString({ verified: false, page: 0 })).toBe("?verified=false&page=0");
  });

  it("is empty when nothing is left to send", () => {
    expect(queryString()).toBe("");
    expect(queryString({ cursor: undefined, niche: [] })).toBe("");
  });
});

/**
 * Two endpoints Phase 2 screens will call that the frozen schema does not have yet, written in openapi-typescript's
 * output shape so the client's types and runtime can be tested with query parameters and DELETE today.
 */
interface Phase2Paths {
  "/api/directory/orgs": {
    get: {
      parameters: {
        query?: { niche?: string[]; cursor?: string | null; q?: string };
        header?: never;
        path?: never;
        cookie?: never;
      };
      requestBody?: never;
      responses: { 200: { headers: { [name: string]: unknown }; content: { "application/json": { items: string[] } } } };
    };
  };
  "/api/auth/identities/{identity_id}": {
    delete: {
      parameters: { query?: never; header?: never; path: { identity_id: string }; cookie?: never };
      requestBody?: never;
      responses: { 204: { headers: { [name: string]: unknown }; content?: never } };
    };
  };
}

describe("api client parameters and methods", () => {
  function recording<Paths = paths>(answer: () => Response = () => json(200, {})) {
    const requests: Request[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(String(input), init);
      requests.push(request);
      return answer();
    });
    return { client: createApiClient<Paths>({ baseUrl: BASE, fetch: fetchMock }), requests };
  }

  it("fills path parameters, one encoded segment each", async () => {
    const { client, requests } = recording();
    await client.GET("/api/orgs/{org_id}", { params: { path: { org_id: "a/b c" } } });
    expect(requests[0].url).toBe(`${BASE}/api/orgs/a%2Fb%20c`);
  });

  it("sends nothing when a path parameter would leave the path (missing, empty, . or ..)", async () => {
    const { client, requests } = recording();
    await expect(client.GET("/api/orgs/{org_id}", { params: { path: { org_id: ".." } } })).rejects.toThrow(TypeError);
    await expect(client.GET("/api/orgs/{org_id}", { params: { path: { org_id: "" } } })).rejects.toThrow(TypeError);
    expect(requests).toHaveLength(0);
  });

  it("sends the query string, arrays as repeated keys, without undefined values", async () => {
    const { client, requests } = recording<Phase2Paths>(() => json(200, { items: ["x"] }));
    const { data } = await client.GET("/api/directory/orgs", {
      params: { query: { niche: ["agri", "fintech"], cursor: undefined, q: "maji safi" } },
    });
    expect(requests[0].url).toBe(`${BASE}/api/directory/orgs?niche=agri&niche=fintech&q=maji%20safi`);
    expect(data?.items).toEqual(["x"]);
  });

  it("sends PUT, PATCH and DELETE with the CSRF header, credentials and a JSON body where given", async () => {
    setCsrfCookie("tok-unsafe");
    const orgs = recording(() => json(200, {}));
    await orgs.client.PUT("/api/orgs/{org_id}/members/{user_id}/roles", {
      params: { path: { org_id: "o-1", user_id: "u-2" } },
      body: { roles: ["reviewer"] },
    });
    await orgs.client.PATCH("/api/me/profile", { body: { headline: "Water systems for Kisumu" } });
    const identities = recording<Phase2Paths>(() => new Response(null, { status: 204 }));
    const { response } = await identities.client.DELETE("/api/auth/identities/{identity_id}", {
      params: { path: { identity_id: "id-3" } },
    });
    expect(response.status).toBe(204);

    const sent = [...orgs.requests, ...identities.requests];
    expect(sent.map((r) => `${r.method} ${r.url}`)).toEqual([
      `PUT ${BASE}/api/orgs/o-1/members/u-2/roles`,
      `PATCH ${BASE}/api/me/profile`,
      `DELETE ${BASE}/api/auth/identities/id-3`,
    ]);
    for (const request of sent) {
      expect(request.headers.get(CSRF_HEADER), request.method).toBe("tok-unsafe");
      expect(request.credentials, request.method).toBe("same-origin");
    }
    expect(await sent[0].json()).toEqual({ roles: ["reviewer"] });
    expect(sent[1].headers.get("Content-Type")).toBe("application/json");
    expect(sent[2].body).toBeNull();
  });

  // `npm run typecheck` (tsc) fails when any of these calls compiles, because its @ts-expect-error is then unused.
  // They are built, never run: the point is that the options the runtime would drop cannot be written at all.
  it("refuses, at compile time, the options it would not send", () => {
    const api: ApiClient = createApiClient();
    const phase2: ApiClient<Phase2Paths> = createApiClient<Phase2Paths>();
    const refused = [
      // @ts-expect-error: the org_id path parameter is required
      () => api.GET("/api/orgs/{org_id}"),
      // @ts-expect-error: both path parameters are required
      () => api.PUT("/api/orgs/{org_id}/members/{user_id}/roles", { params: { path: { org_id: "o" } }, body: { roles: [] } }),
      // @ts-expect-error: header parameters are not sent
      () => api.GET("/api/orgs/{org_id}", { params: { path: { org_id: "o" }, header: { "X-Org": "o" } } }),
      // @ts-expect-error: cookie parameters are not sent
      () => api.GET("/api/auth/me", { params: { cookie: { session: "s" } } }),
      // @ts-expect-error: this endpoint takes no query
      () => api.GET("/api/auth/me", { params: { query: { expand: "orgs" } } }),
      // @ts-expect-error: fetch options other than headers and signal are not sent
      () => api.GET("/api/auth/me", { cache: "no-store" }),
      // @ts-expect-error: openapi-fetch's own options do not exist here
      () => api.GET("/api/auth/me", { parseAs: "text" }),
      // @ts-expect-error: a GET has no body
      () => api.GET("/api/auth/me", { body: { a: 1 } }),
      // @ts-expect-error: no DELETE operation at this path
      () => api.DELETE("/api/auth/me"),
      // @ts-expect-error: the body must match the operation's schema
      () => api.POST("/api/auth/totp/confirm", { body: { code: 123456 } }),
      // @ts-expect-error: an unknown query parameter
      () => phase2.GET("/api/directory/orgs", { params: { query: { sort: "name" } } }),
      // @ts-expect-error: a query value of the wrong type
      () => phase2.GET("/api/directory/orgs", { params: { query: { niche: "agri" } } }),
    ];
    expect(refused).toHaveLength(12);
  });
});
