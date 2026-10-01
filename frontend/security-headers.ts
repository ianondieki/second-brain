// Response headers for the web app (next.config.ts headers()). The API sets its own (backend main.py).
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

export interface Header {
  key: string;
  value: string;
}

/** Sent with every response, build assets included: the browser must not guess another type than the declared one. */
export const NOSNIFF: Header = { key: "X-Content-Type-Options", value: "nosniff" };

/** The fonts under /fonts carry a version suffix in their names, so they can be cached for a year without revalidation. */
export const FONT_CACHE: Header = { key: "Cache-Control", value: "public, max-age=31536000, immutable" };

/**
 * Headers that only mean something on a document: framing, referrers, device features and the CSP. They are not sent
 * with the hashed build assets under /_next/static (scripts, CSS) or the fonts under /fonts, where they change nothing but add about
 * 0.4 KB to every file a route downloads over HTTP/1.1 (docs/spec/07 item 5: the JS budget). A worker script takes
 * its CSP from its own response, so a future service worker must be served from outside /_next/static.
 */
export const PAGE_HEADERS: ReadonlyArray<Header> = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Content-Security-Policy-Report-Only", value: CSP_REPORT_ONLY },
];

/**
 * next.config.ts experimental.caseSensitiveRoutes. Next.js matches header, rewrite and redirect sources without
 * regard to case by default, so the lookahead below would also exempt "/_NEXT/static/x.js", an HTML 404 page, from
 * the page headers (framable). Build assets are served only at their exact-case paths, so exact-case matching loses
 * nothing; it also stops "/API/..." from reaching the API through the /api rewrite (the API's paths are lower case).
 */
export const CASE_SENSITIVE_ROUTES = true;

/** The rules next.config.ts headers() returns (path-to-regexp sources, as Next.js matches them). */
export const HEADER_RULES: ReadonlyArray<{ source: string; headers: Header[] }> = [
  { source: "/:path*", headers: [NOSNIFF] },
  // The self-hosted fonts (public/fonts, versioned file names): cached like the hashed build assets, so a returning
  // visitor's headline never waits for a revalidation round trip.
  { source: "/fonts/:file([^/]+-v\\d+\\.woff2)", headers: [FONT_CACHE] },
  // Every path except /_next/static/… and the versioned font files (a /fonts/… 404 is a document too): a negative
  // lookahead, as in the Next.js middleware matcher examples.
  { source: "/((?!_next/static/|fonts/[^/]+-v\\d+\\.woff2$).*)", headers: [...PAGE_HEADERS] },
];
