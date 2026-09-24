import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// The API is same-origin: /api/* is rewritten to FastAPI (docs/spec/08 Frontend), so session and CSRF cookies
// stay first-party. API_ORIGIN is the backend's address as seen from the Next.js server.
const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");
export default withNextIntl(nextConfig);
