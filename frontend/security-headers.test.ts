import { buildCustomRoute } from "next/dist/lib/build-custom-route";
import { describe, expect, it } from "vitest";

import { CASE_SENSITIVE_ROUTES, CSP_REPORT_ONLY, HEADER_RULES } from "./security-headers";

/**
 * The headers Next.js sends for a path; every matching rule applies. Each rule is compiled by buildCustomRoute (what
 * `next build` writes into routes-manifest.json) and matched with the flags the server uses at runtime: "i" (any
 * case) unless experimental.caseSensitiveRoutes is on (next/dist/server/lib/router-utils/filesystem.js).
 */
function headersFor(path: string, caseSensitive: boolean = CASE_SENSITIVE_ROUTES): Record<string, string> {
  const sent: Record<string, string> = {};
  for (const rule of HEADER_RULES) {
    const { regex } = buildCustomRoute("header", { source: rule.source, headers: rule.headers });
    if (new RegExp(regex, caseSensitive ? "" : "i").test(path)) {
      for (const { key, value } of rule.headers) sent[key] = value;
    }
  }
  return sent;
}

// Proxied /api responses are FastAPI's own: they carry no Next.js headers, and the API's security headers are
// asserted by the backend tests (backend/tests/unit/test_app.py).
const PAGES = [
  "/",
  "/signup",
  "/login",
  "/signup/check-email",
  "/settings/security",
  "/favicon.ico",
  // Near misses of the build-asset prefix: pages (a 404 page is a document too) or Next's image endpoint.
  "/_NEXT/static/x.js",
  "/_Next/Static/chunks/x.js",
  "/_next/image",
  "/_next/static",
  "/_next/staticx",
];
const BUILD_ASSETS = [
  "/_next/static/chunks/0bma92pht_c97.js",
  "/_next/static/chunks/turbopack-43vu1xwipchft.js",
  "/_next/static/chunks/1a2b3c4d.css",
  "/_next/static/media/font.woff2",
];

describe("web security headers", () => {
  it.each(PAGES)("forbid framing and MIME sniffing, and limit referrers and device features on %s", (path) => {
    const sent = headersFor(path);
    expect(sent["X-Frame-Options"]).toBe("DENY");
    expect(sent["X-Content-Type-Options"]).toBe("nosniff");
    expect(sent["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(sent["Permissions-Policy"]).toBe("camera=(), microphone=(), geolocation=()");
    expect(sent["Content-Security-Policy-Report-Only"]).toBe(CSP_REPORT_ONLY);
  });

  it.each(BUILD_ASSETS)("send only nosniff with the build asset %s (the JS budget counts every byte)", (path) => {
    expect(headersFor(path)).toEqual({ "X-Content-Type-Options": "nosniff" });
  });

  it("match sources in exact case, since Next's default would exempt /_NEXT/static/... pages", () => {
    expect(CASE_SENSITIVE_ROUTES).toBe(true);
    expect(headersFor("/_NEXT/static/x.js", false)).toEqual({ "X-Content-Type-Options": "nosniff" });
  });

  it("report a same-origin CSP baseline (enforced nonce CSP comes with the Phase 8 edge)", () => {
    for (const directive of [
      "default-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "object-src 'none'",
    ]) {
      expect(CSP_REPORT_ONLY).toContain(directive);
    }
    expect(headersFor("/signup")["Content-Security-Policy"]).toBeUndefined();
  });
});
