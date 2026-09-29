// @vitest-environment node
import { fileURLToPath } from "node:url";

import { PHASE_PRODUCTION_BUILD } from "next/constants";
import loadConfig from "next/dist/server/config";
import { describe, expect, it } from "vitest";

import nextConfig from "./next.config";
import { HEADER_RULES } from "./security-headers";

// security-headers.test.ts proves the header rules are right when sources match in exact case; these tests prove the
// app's real config (next.config.ts, as next-intl's plugin returns it) turns exact-case matching on and sends those
// rules. Without the flag, "/_NEXT/static/x.js" (an HTML 404 page) would be served without X-Frame-Options.
describe("next.config.ts", () => {
  it("matches header and rewrite sources in exact case", () => {
    expect(nextConfig.experimental?.caseSensitiveRoutes).toBe(true);
  });

  it("routes /api and the published provenance keys, and nothing else, to the API", async () => {
    const rewrites = await nextConfig.rewrites?.();
    const sources = (Array.isArray(rewrites) ? rewrites : []).map((rule) => rule.source);
    expect(sources).toEqual(["/api/:path*", "/.well-known/provenance-keys.json"]);
  });

  it("sends exactly the header rules of security-headers.ts", async () => {
    expect(await nextConfig.headers?.()).toEqual(HEADER_RULES);
  });

  // `next build` reads the config this way and writes both into routes-manifest.json, which the server then follows.
  // Loading transpiles next.config.ts and brings in Next's config machinery: about 7 s on a cold run, over vitest's
  // default 5 s, and over 30 s once on a busy Windows machine. The limit guards against a hang, not slowness.
  it(
    "keeps exact-case matching once Next.js has loaded and validated the config for a build",
    { timeout: 60_000 },
    async () => {
      const loaded = await loadConfig(PHASE_PRODUCTION_BUILD, fileURLToPath(new URL(".", import.meta.url)));
      expect(loaded.experimental.caseSensitiveRoutes).toBe(true);
      expect(await loaded.headers?.()).toEqual(HEADER_RULES);
    },
  );
});
