import type { FetchResponse } from "openapi-fetch";

import { CSRF_PATH, withCsrf } from "./csrf";
import type { paths } from "./schema";

export {
  CSRF_COOKIE,
  CSRF_HEADER,
  CSRF_PATH,
  ensureCsrf,
  isCsrfFailure,
  readCookie,
  readCsrfCookie,
  withCsrf,
  type EnsureCsrfOptions,
} from "./csrf";

type Fetch = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
const defaultFetch: Fetch = (input, init) => globalThis.fetch(input, init);

export interface ApiClientOptions {
  baseUrl?: string;
  fetch?: Fetch;
}

// Types. The operations come from the generated `paths` (backend/openapi.json); the answer type is openapi-fetch's
// (a type-only import). The request options are this client's own: only what `call` below sends is accepted, so an
// option it would drop (a header parameter, `cache`, `parseAs`, …) fails to compile instead of vanishing at runtime.

type HttpMethod = "get" | "put" | "post" | "patch" | "delete";

/** The paths with an operation for the method (openapi-typescript writes `delete?: never` for the others). */
type PathsWith<Paths, M extends HttpMethod> = {
  [P in keyof Paths]: Paths[P] extends { [K in M]: object } ? P : never;
}[keyof Paths];

type OperationOf<Paths, P, M extends HttpMethod> = P extends keyof Paths
  ? M extends keyof Paths[P]
    ? Paths[P][M]
    : never
  : never;

/** Keys that must be given (openapi-typescript marks the others optional). */
type RequiredKeys<T> = { [K in keyof T]-?: T extends Record<K, T[K]> ? K : never }[keyof T];

/**
 * Path and query parameters only. Header and cookie parameters are refused: the API declares none, and the session
 * and CSRF cookies travel on their own.
 */
type ParamsOf<Op> = Op extends { parameters: infer P }
  ? Pick<P, Extract<keyof P, "path" | "query">> & { header?: never; cookie?: never }
  : never;

type ParamsOption<Op> = [RequiredKeys<ParamsOf<Op>>] extends [never]
  ? { params?: ParamsOf<Op> }
  : { params: ParamsOf<Op> };

type RequestBodyOf<Op> = Op extends { requestBody?: infer R } ? NonNullable<R> : never;
type JsonOf<R> = R extends { content: { "application/json": infer B } } ? B : never;

/** A JSON body where the operation takes one (required when the API requires it); no body anywhere else. */
type BodyOption<Op> = [JsonOf<RequestBodyOf<Op>>] extends [never]
  ? { body?: never }
  : Op extends { requestBody: object }
    ? { body: JsonOf<RequestBodyOf<Op>> }
    : { body?: JsonOf<RequestBodyOf<Op>> };

/** What one call can carry: parameters, a JSON body, request headers and an abort signal. Nothing else. */
export type RequestOptions<Op> = ParamsOption<Op> & BodyOption<Op> & { headers?: HeadersInit; signal?: AbortSignal };

type OptionsArg<Op> = [RequiredKeys<RequestOptions<Op>>] extends [never]
  ? [options?: RequestOptions<Op>]
  : [options: RequestOptions<Op>];

type Answer<Op> = Op extends Record<string | number, unknown> ? FetchResponse<Op, unknown, `${string}/${string}`> : never;

type ClientMethod<Paths, M extends HttpMethod> = <P extends PathsWith<Paths, M>>(
  path: P,
  ...options: OptionsArg<OperationOf<Paths, P, M>>
) => Promise<Answer<OperationOf<Paths, P, M>>>;

/** The browser's API client over the generated `paths`. */
export interface ApiClient<Paths = paths> {
  GET: ClientMethod<Paths, "get">;
  POST: ClientMethod<Paths, "post">;
  PUT: ClientMethod<Paths, "put">;
  PATCH: ClientMethod<Paths, "patch">;
  DELETE: ClientMethod<Paths, "delete">;
}

type Method = Uppercase<HttpMethod>;

interface CallOptions {
  params?: { path?: Record<string, unknown>; query?: Record<string, unknown> };
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
}

/**
 * "/api/orgs/{org_id}" with { org_id: "a/b c" } gives "/api/orgs/a%2Fb%20c": each value is one encoded segment. A
 * missing or empty value, "." or ".." throws instead of sending "{org_id}" or a URL that resolves to another path.
 */
export function fillPath(template: string, values: Record<string, unknown> = {}): string {
  return template.replace(/\{([^}]+)\}/g, (_, name: string) => {
    const value = values[name] === undefined || values[name] === null ? "" : String(values[name]);
    if (value === "" || value === "." || value === "..") {
      throw new TypeError(`Path parameter "${name}" must be a non-empty segment`);
    }
    return encodeURIComponent(value);
  });
}

/**
 * { niche: ["agri", "health"], cursor: undefined, q: "maji safi" } gives "?niche=agri&niche=health&q=maji%20safi":
 * arrays repeat the key (as FastAPI reads a list), undefined and null are left out, and "" when nothing is left.
 */
export function queryString(query: Record<string, unknown> = {}): string {
  const pairs: string[] = [];
  for (const [key, value] of Object.entries(query)) {
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item === undefined || item === null) continue;
      pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(item))}`);
    }
  }
  return pairs.length ? `?${pairs.join("&")}` : "";
}

/**
 * Typed client for the same-origin API (types generated from backend/openapi.json). The runtime is this small
 * function instead of openapi-fetch's (about 2 KB of gzipped JS on every route, docs/spec/07 item 5): path and query
 * parameters, JSON bodies, and the CSRF header on every state-changing method (withCsrf). It answers like
 * openapi-fetch: `{ data, response }` when ok, `{ error, response }` otherwise, with error parsed as JSON when it is
 * JSON and left as text when it is not; an empty body gives neither.
 */
export function createApiClient<Paths = paths>({
  baseUrl = "",
  fetch: fetchImpl = defaultFetch,
}: ApiClientOptions = {}): ApiClient<Paths> {
  const root = baseUrl.replace(/\/$/, "");
  const send = withCsrf(fetchImpl, `${root}${CSRF_PATH}`);

  async function call(method: Method, path: string, { params, body, headers, signal }: CallOptions = {}) {
    const url = `${root}${fillPath(path, params?.path)}${queryString(params?.query)}`;
    const init: RequestInit = { method, credentials: "same-origin", headers: new Headers(headers), signal };
    if (body !== undefined) {
      (init.headers as Headers).set("Content-Type", "application/json");
      init.body = JSON.stringify(body);
    }
    const response = await send(url, init);
    const text = await response.text(); // "" for 204 and every other empty body
    if (!text) return response.ok ? { data: undefined, response } : { error: undefined, response };
    if (response.ok) return { data: JSON.parse(text), response };
    try {
      return { error: JSON.parse(text), response };
    } catch {
      return { error: text, response };
    }
  }

  const method = (name: Method) => (path: string, options?: CallOptions) => call(name, path, options);
  return {
    GET: method("GET"),
    POST: method("POST"),
    PUT: method("PUT"),
    PATCH: method("PATCH"),
    DELETE: method("DELETE"),
  } as unknown as ApiClient<Paths>;
}

export const api = createApiClient();
