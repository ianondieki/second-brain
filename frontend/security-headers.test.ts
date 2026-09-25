import { describe, expect, it } from "vitest";

import { CSP_REPORT_ONLY, SECURITY_HEADERS } from "./security-headers";

const byName = Object.fromEntries(SECURITY_HEADERS.map(({ key, value }) => [key, value]));

describe("web security headers", () => {
  it("forbid framing and MIME sniffing, and limit referrers and device features", () => {
    expect(byName["X-Frame-Options"]).toBe("DENY");
    expect(byName["X-Content-Type-Options"]).toBe("nosniff");
    expect(byName["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(byName["Permissions-Policy"]).toBe("camera=(), microphone=(), geolocation=()");
  });

  it("report a same-origin CSP baseline (enforced nonce CSP comes with the Phase 8 edge)", () => {
    expect(byName["Content-Security-Policy-Report-Only"]).toBe(CSP_REPORT_ONLY);
    for (const directive of [
      "default-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
      "object-src 'none'",
    ]) {
      expect(CSP_REPORT_ONLY).toContain(directive);
    }
    expect(byName["Content-Security-Policy"]).toBeUndefined();
  });
});
