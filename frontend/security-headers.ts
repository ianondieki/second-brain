// Response headers for every web page (next.config.ts headers()). The API sets its own (backend main.py).
// HSTS and an enforced, nonce-based CSP come with the Caddy edge in Phase 8; until then the CSP only reports.

/**
 * Report-only baseline. Next.js inlines its bootstrap scripts (self.__next_f.push) and React sets style attributes,
 * so script-src and style-src need 'unsafe-inline' until the nonce CSP; everything else is same-origin only.
 * (frame-ancestors is ignored in a report-only policy; X-Frame-Options: DENY enforces it meanwhile.)
 */
export const CSP_REPORT_ONLY = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

export const SECURITY_HEADERS: ReadonlyArray<{ key: string; value: string }> = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Content-Security-Policy-Report-Only", value: CSP_REPORT_ONLY },
];
