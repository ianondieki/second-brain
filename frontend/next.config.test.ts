// @vitest-environment node
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { buildCustomRoute } from "next/dist/lib/build-custom-route";
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import loadConfig from "next/dist/server/config";
import { describe, expect, it } from "vitest";

import nextConfig, { FONT_CORS, PAGE_EXTENSIONS } from "./next.config";
import { HEADER_RULES } from "./security-headers";

/** The headers the app's real config sends for a path, every matching rule compiled as `next build` does. */
async function headersFor(path: string): Promise<Record<string, string>> {
  const sent: Record<string, string> = {};
  for (const rule of (await nextConfig.headers?.()) ?? []) {
    const { regex } = buildCustomRoute("header", rule);
    // Exact case, as experimental.caseSensitiveRoutes makes the server match (security-headers.test.ts).
    if (new RegExp(regex).test(path)) for (const { key, value } of rule.headers) sent[key] = value;
  }
  return sent;
}

const FONT_FILES = readdirSync(fileURLToPath(new URL("./public/fonts", import.meta.url))).filter((name) =>
  name.endsWith(".woff2"),
);

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

  // The design lab (app/(lab)/design-lab, P18) is development only: its `*.lab.tsx` files are routes for `next dev`,
  // and a production build takes the `*.stub.tsx` 404 stand-ins at the same addresses instead, which keeps the lab's
  // fixtures and fonts out of the image. vitest runs with NODE_ENV "test", where the lab is off as in production.
  it("resolves the design lab's stubs, not its pages, outside development", () => {
    expect(PAGE_EXTENSIONS).toEqual(["stub.tsx", "tsx", "ts", "jsx", "js"]);
    expect(nextConfig.pageExtensions).toEqual(PAGE_EXTENSIONS);
  });

  it("sends exactly the header rules of security-headers.ts and the fonts' CORS rule", async () => {
    expect(await nextConfig.headers?.()).toEqual([...HEADER_RULES, FONT_CORS]);
  });

  // The marked full proposal (backend proposals/render.py) is framed with a sandbox and no allow-same-origin, so its
  // document's origin is opaque and its font requests are CORS requests from origin "null". The self-hosted woff2
  // files are public (OFL), so any origin may read them; nothing else gets the header.
  it.each(FONT_FILES)("lets any origin read the font /fonts/%s", async (file) => {
    expect(await headersFor(`/fonts/${file}`)).toMatchObject({
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "public, max-age=31536000, immutable",
      "X-Content-Type-Options": "nosniff",
    });
  });

  it.each([
    "/",
    "/org/inbox",
    "/api/orgs/x/proposals/y/tier2",
    "/fonts/LICENCES.md",
    "/fonts/OFL.txt",
    "/fonts/og/fraunces-og-v1.ttf",
    "/fonts/og/x-v1.woff2",
    "/fonts/missing.woff2",
    "/FONTS/hanken-grotesk-v1.woff2",
    "/fonts/hanken-grotesk-v1.woff2/x",
    "/_next/static/media/font.woff2",
  ])("lets no other origin read %s", async (path) => {
    expect(await headersFor(path)).not.toHaveProperty("Access-Control-Allow-Origin");
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
      expect(await loaded.headers?.()).toEqual([...HEADER_RULES, FONT_CORS]);
    },
  );
});
