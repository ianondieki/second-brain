// @vitest-environment node
import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";

import manifest, { BLOOM, PAPER } from "./manifest";

// P24 (REQ-UX-04): Wazo installs as a standalone app (Android's home screen), in the tokens' colours, with icons drawn
// from the mark; no service worker yet.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

describe("the web app manifest", () => {
  it("names Wazo, opens standalone at the start page, in the paper and bloom of the tokens", async () => {
    const m = await manifest();
    expect(m).toMatchObject({ name: "Wazo", short_name: "Wazo", start_url: "/", scope: "/", display: "standalone" });
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    const root = css.slice(css.indexOf("\n:root {"));
    expect(root).toContain(`--paper: ${PAPER};`);
    expect(root).toContain(`--accent: ${BLOOM};`);
    expect([m.background_color, m.theme_color]).toEqual([PAPER, BLOOM]);
  });

  it("lists a 192 and a 512 icon and a maskable one, each a committed PNG of that size", async () => {
    const icons = (await manifest()).icons!;
    expect(icons.map((i) => [i.sizes, i.purpose])).toEqual([
      ["192x192", "any"],
      ["512x512", "any"],
      ["512x512", "maskable"],
    ]);
    for (const icon of icons) {
      const file = readFileSync(join(process.cwd(), "public", icon.src));
      expect(icon.type).toBe("image/png");
      expect(file.subarray(1, 4).toString()).toBe("PNG");
      const [w, h] = [file.readUInt32BE(16), file.readUInt32BE(20)];
      expect(`${w}x${h}`).toBe(icon.sizes);
      expect(statSync(join(process.cwd(), "public", icon.src)).size).toBeLessThan(40_000);
    }
  });
});
