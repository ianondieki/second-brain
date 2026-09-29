import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

import { CASE_SENSITIVE_ROUTES, HEADER_RULES } from "./security-headers";

// The API is same-origin: /api/* is rewritten to FastAPI (docs/spec/08 Frontend), so session and CSRF cookies
// stay first-party. API_ORIGIN is the backend's address as seen from the Next.js server.
// Rewrites are resolved at build time: set API_ORIGIN when running `next build` (the Dockerfile takes it as an ARG).
const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
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
  // nosniff everywhere; the document-only headers on everything but the /_next/static build assets.
  async headers() {
    return HEADER_RULES.map(({ source, headers }) => ({ source, headers: [...headers] }));
  },
};

// Messages are precompiled at build time, so the browser gets the format-only runtime instead of the ICU parser
// (docs/spec/07 item 5: at most 150 KB, i.e. 150,000 bytes, of gzipped JS per route; `npm run budget`).
const withNextIntl = createNextIntlPlugin({
  requestConfig: "./i18n/request.ts",
  experimental: { messages: { path: "./locales", format: "json", locales: "infer", precompile: true } },
});
export default withNextIntl(nextConfig);
