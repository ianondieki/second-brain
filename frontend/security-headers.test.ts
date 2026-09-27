import { buildCustomRoute } from "next/dist/lib/build-custom-route";
import { describe, expect, it } from "vitest";

import { CSP_REPORT_ONLY, HEADER_RULES } from "./security-headers";

/**
 * The headers Next.js sends for a path. Each rule is compiled by buildCustomRoute, the function `next build` uses to
 * write the rules into routes-manifest.json, so this checks Next's own path matching; every matching rule applies.
 */
function headersFor(path: string): Record<string, string> {
  const sent: Record<string, string> = {};
  for (const rule of HEADER_RULES) {
    const { regex } = buildCustomRoute("header", { source: rule.source, headers: rule.headers });
    if (new RegExp(regex).test(path)) {
      for (const { key, value } of rule.headers) sent[key] = value;
    }
  }
  return sent;
}

const PAGES = ["/", "/signup", "/login", "/signup/check-email", "/settings/security", "/favicon.ico", "/api/auth/me"];
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
