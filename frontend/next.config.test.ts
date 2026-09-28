// @vitest-environment node
import { fileURLToPath } from "node:url";

import { PHASE_PRODUCTION_SERVER } from "next/constants";
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

  it("sends exactly the header rules of security-headers.ts", async () => {
    expect(await nextConfig.headers?.()).toEqual(HEADER_RULES);
  });

  it("keeps exact-case matching once Next.js has loaded and validated the config", async () => {
    const loaded = await loadConfig(PHASE_PRODUCTION_SERVER, fileURLToPath(new URL(".", import.meta.url)));
    expect(loaded.experimental.caseSensitiveRoutes).toBe(true);
    expect(await loaded.headers?.()).toEqual(HEADER_RULES);
  });
});
