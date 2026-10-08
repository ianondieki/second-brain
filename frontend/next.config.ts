import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

import { CASE_SENSITIVE_ROUTES, HEADER_RULES } from "./security-headers";

// The API is same-origin: /api/* is rewritten to FastAPI (docs/spec/08 Frontend), so session and CSRF cookies
// stay first-party. API_ORIGIN is the backend's address as seen from the Next.js server.
// Rewrites are resolved at build time: set API_ORIGIN when running `next build` (the Dockerfile takes it as an ARG).
const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

/**
 * The design lab (app/(lab)/design-lab, P18 step 1) is development only. Its pages and layout are `*.lab.tsx`, an
 * extension only `next dev` (or DESIGN_LAB=1, for a local Lighthouse run of the lab) resolves as routes; a production
 * build resolves `*.stub.tsx` there instead: two one-line pages that answer 404 and a pass-through layout, so the
 * route set (and Next's generated route types, which must agree between `.next/dev/types` and `.next/types`) is the
 * same in both modes while the lab's screens, fixtures and self-hosted fonts are never compiled for production.
 */
export const DESIGN_LAB = process.env.NODE_ENV === "development" || process.env.DESIGN_LAB === "1";
export const PAGE_EXTENSIONS = [DESIGN_LAB ? "lab.tsx" : "stub.tsx", "tsx", "ts", "jsx", "js"];

/** The vendored woff2 files (public/fonts/LICENCES.md); next.config.test.ts checks the list against the folder. */
export const FONT_FILES = [
  "bricolage-grotesque-v2.woff2",
  "fraunces-ext-v1.woff2",
  "fraunces-italic-v1.woff2",
  "fraunces-v1.woff2",
  "hanken-grotesk-v1.woff2",
  "ibm-plex-mono-latin-v1.woff2",
];

/**
 * The self-hosted fonts (public/fonts, OFL, the versioned woff2 files security-headers.ts caches) are readable from any
 * origin. The marked full proposal (backend proposals/render.py, REQ-PROV-03) is framed in a sandbox without
 * allow-same-origin, so its document has an opaque origin and its font requests are CORS requests from origin "null":
 * without this header the browser drops the response and the page falls back to a system face. The files are public,
 * so the header reveals nothing; a credentialed request is never allowed by "*". The rule names the files themselves:
 * Next applies header rules before it looks for the file, so a name pattern would also hand the header to the HTML 404
 * page of any matching name. The query a request carries (the frame's `?frame=1`) is not part of the match.
 */
export const FONT_CORS = {
  source: `/fonts/:file(${FONT_FILES.map((name) => name.replaceAll(".", "\\.")).join("|")})`,
  headers: [{ key: "Access-Control-Allow-Origin", value: "*" }],
};

const nextConfig: NextConfig = {
  output: "standalone",
  pageExtensions: PAGE_EXTENSIONS,
  poweredByHeader: false,
  // Exact-case matching of the header and rewrite sources below (see security-headers.ts).
  experimental: { caseSensitiveRoutes: CASE_SENSITIVE_ROUTES },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      // The published provenance keys (REQ-PROV-02): served by the API outside /api, linked from /verify.
      { source: "/.well-known/provenance-keys.json", destination: `${apiOrigin}/.well-known/provenance-keys.json` },
    ];
  },
  // nosniff everywhere; the document-only headers on everything but the /_next/static build assets; the fonts' CORS.
  async headers() {
    return [...HEADER_RULES.map(({ source, headers }) => ({ source, headers: [...headers] })), FONT_CORS];
  },
};

// Messages are precompiled at build time, so the browser gets the format-only runtime instead of the ICU parser
// (docs/spec/07 item 5: at most 150 KB, i.e. 150,000 bytes, of gzipped JS per route; `npm run budget`).
const withNextIntl = createNextIntlPlugin({
  requestConfig: "./i18n/request.ts",
  experimental: { messages: { path: "./locales", format: "json", locales: "infer", precompile: true } },
});
export default withNextIntl(nextConfig);
