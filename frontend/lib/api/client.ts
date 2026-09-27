import type { Client } from "openapi-fetch";

import { CSRF_COOKIES, pickCookie } from "./cookies";
import type { components, paths } from "./schema";

/** The CSRF cookie's name with Secure cookies; `bridge_csrf` on a plain-http dev stack (see ./cookies). */
export const CSRF_COOKIE = CSRF_COOKIES[0];
export const CSRF_HEADER = "X-CSRF-Token";
export const CSRF_PATH = "/api/auth/csrf";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type CsrfResponse = components["schemas"]["CsrfResponse"];

const defaultFetch: Fetch = (input, init) => globalThis.fetch(input, init);

/** Read a cookie in the browser (the CSRF cookie is deliberately not httpOnly: double-submit, docs/spec/08). */
export function readCookie(name: string, source: string = typeof document === "undefined" ? "" : document.cookie) {
  for (const part of source.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key !== name) continue;
    try {
      return decodeURIComponent(rest.join("="));
    } catch {
      // A malformed cookie (for example "%E0%A4%A") counts as absent, so ensureCsrf fetches a fresh token.
      return undefined;
    }
  }
  return undefined;
}

/** The CSRF token from whichever cookie name the API uses (the __Host- prefixed one first). */
export function readCsrfCookie(source?: string): string | undefined {
  return pickCookie(CSRF_COOKIES, (name) => readCookie(name, source))?.value;
}

let inFlight: Promise<string | undefined> | null = null;

async function fetchCsrf(fetchImpl: Fetch, url: string): Promise<string | undefined> {
  const response = await fetchImpl(url, {
    method: "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) return readCsrfCookie();
  const body = (await response.json()) as Partial<CsrfResponse>;
  // The response also sets the cookie; the body carries the same value, so it works before the cookie is readable.
  return body.csrf_token ?? readCsrfCookie();
}

export interface EnsureCsrfOptions {
  fetch?: Fetch;
  url?: string;
  /** Ask the server for a new token even when a cookie exists (after a 403 `csrf_failed`). */
  force?: boolean;
}

/**
 * Returns the CSRF token for the next state-changing request: the CSRF cookie when present (either name), else one
 * GET /api/auth/csrf. Concurrent callers share a single request.
 */
export function ensureCsrf({ fetch: fetchImpl = defaultFetch, url = CSRF_PATH, force = false }: EnsureCsrfOptions = {}) {
  if (!force) {
    const existing = readCsrfCookie();
    if (existing) return Promise.resolve<string | undefined>(existing);
  }
  inFlight ??= fetchCsrf(fetchImpl, url).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

/** True when the API refused a request because its CSRF token was missing, stale or bound to another session. */
export async function isCsrfFailure(response: Response): Promise<boolean> {
  if (response.status !== 403) return false;
  try {
    const body = (await response.clone().json()) as { detail?: { code?: unknown } } | null;
    return body?.detail?.code === "csrf_failed";
  } catch {
    return false;
  }
}

/**
 * Wraps fetch so every state-changing request carries the double-submit header, and retries exactly once with a
 * fresh token when the server answers 403 `csrf_failed` (for example after the session changed in another tab).
 */
export function withCsrf(baseFetch: Fetch = defaultFetch, csrfUrl: string = CSRF_PATH): Fetch {
  return async (input, init) => {
    const request = new Request(input, init);
    if (!UNSAFE.has(request.method.toUpperCase())) return baseFetch(request);

    const spare = request.clone();
    const token = await ensureCsrf({ fetch: baseFetch, url: csrfUrl });
    if (token) request.headers.set(CSRF_HEADER, token);
    const response = await baseFetch(request);
    if (!(await isCsrfFailure(response))) return response;

    const fresh = await ensureCsrf({ fetch: baseFetch, url: csrfUrl, force: true });
    if (fresh) spare.headers.set(CSRF_HEADER, fresh);
    return baseFetch(spare);
  };
}

export interface ApiClientOptions {
  baseUrl?: string;
  fetch?: Fetch;
}

/** The browser's API client: openapi-fetch's types over the generated `paths`, for the methods the app calls. */
export type ApiClient = Pick<Client<paths>, "GET" | "POST">;

interface CallInit {
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

/**
 * Typed client for the same-origin API (types generated from backend/openapi.json). The types are openapi-fetch's
 * (a type-only import); the runtime is this small function instead of openapi-fetch's (about 2 KB of gzipped JS on
 * every route, docs/spec/07 item 5), since the app only sends GET and JSON POST requests without path or query
 * parameters. It answers like openapi-fetch: `{ data, response }` when ok, `{ error, response }` otherwise, with
 * error parsed as JSON when it is JSON and left as text when it is not; an empty body gives neither.
 */
export function createApiClient({ baseUrl = "", fetch: fetchImpl = defaultFetch }: ApiClientOptions = {}): ApiClient {
  const root = baseUrl.replace(/\/$/, "");
  const send = withCsrf(fetchImpl, `${root}${CSRF_PATH}`);

  async function call(method: "GET" | "POST", path: string, { body, headers, signal }: CallInit = {}) {
    const init: RequestInit = { method, credentials: "same-origin", headers: new Headers(headers), signal };
    if (body !== undefined) {
      (init.headers as Headers).set("Content-Type", "application/json");
      init.body = JSON.stringify(body);
    }
    const response = await send(`${root}${path}`, init);
    const text = await response.text(); // "" for 204 and every other empty body
    if (!text) return response.ok ? { data: undefined, response } : { error: undefined, response };
    if (response.ok) return { data: JSON.parse(text), response };
    try {
      return { error: JSON.parse(text), response };
    } catch {
      return { error: text, response };
    }
  }

  return {
    GET: (path: string, init?: CallInit) => call("GET", path, init),
    POST: (path: string, init?: CallInit) => call("POST", path, init),
  } as unknown as ApiClient;
}

export const api = createApiClient();
