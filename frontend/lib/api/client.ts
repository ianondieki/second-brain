import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

export const CSRF_COOKIE = "bridge_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** Read a cookie in the browser (the CSRF cookie is deliberately not httpOnly: double-submit, docs/spec/08). */
export function readCookie(name: string, source: string = typeof document === "undefined" ? "" : document.cookie) {
  for (const part of source.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}

/** Adds the double-submit CSRF header to every state-changing request. */
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (UNSAFE.has(request.method.toUpperCase())) {
      const token = readCookie(CSRF_COOKIE);
      if (token) request.headers.set(CSRF_HEADER, token);
    }
    return request;
  },
};

/** Typed client for the same-origin API (types generated from backend/openapi.json). */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
api.use(csrfMiddleware);
