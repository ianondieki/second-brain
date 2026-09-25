import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// The API is same-origin: /api/* is rewritten to FastAPI (docs/spec/08 Frontend), so session and CSRF cookies
// stay first-party. API_ORIGIN is the backend's address as seen from the Next.js server.
// Rewrites are resolved at build time: set API_ORIGIN when running `next build` (the Dockerfile takes it as an ARG).
const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

// Messages are precompiled at build time, so the browser gets the format-only runtime instead of the ICU parser
// (docs/spec/07 item 5: at most 150 KB of gzipped JS per route).
const withNextIntl = createNextIntlPlugin({
  requestConfig: "./i18n/request.ts",
  experimental: { messages: { path: "./locales", format: "json", locales: "infer", precompile: true } },
});
export default withNextIntl(nextConfig);
