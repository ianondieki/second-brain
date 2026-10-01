// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// REQ-UX-01..04 (P16 design system): every colour mix that was repeated inline is a named token in globals.css, exposed
// as a Tailwind utility, and no component spells one of them out again (docs/platform/design/p16-design-system.md).

const root = fileURLToPath(new URL("..", import.meta.url));
const css = readFileSync(join(root, "app/globals.css"), "utf8");

// The plan's token table, as Tailwind writes the mix inside an arbitrary value (spaces become underscores).
const MIXES: Record<string, string> = {
  "accent-strong": "color-mix(in oklab, var(--accent) 84%, var(--ink))",
  "wash-soft": "color-mix(in oklab, var(--accent-wash) 55%, var(--paper))",
  "error-wash": "color-mix(in oklab, var(--error) 7%, var(--field))",
  "ok-wash": "color-mix(in oklab, var(--ok) 7%, var(--field))",
  "error-line": "color-mix(in oklab, var(--error) 45%, var(--paper))",
  "ok-line": "color-mix(in oklab, var(--ok) 45%, var(--paper))",
  "accent-line": "color-mix(in oklab, var(--accent) 35%, var(--paper))",
  "warm-line": "color-mix(in oklab, var(--warm) 45%, var(--paper))",
  scrim: "color-mix(in oklab, var(--ink) 45%, transparent)",
};

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("design tokens", () => {
  it.each(Object.entries(MIXES))("defines --%s once and exposes it as a colour utility", (name, mix) => {
    expect(css).toContain(`--${name}: ${mix};`);
    expect(css).toContain(`--color-${name}: var(--${name});`);
  });

  // Two elevations (D-52): the card's, very soft and wide, and the overlay's; both offset with a blur and tinted from
  // ink in light mode, from black in dark mode; each is declared for light, dark and the system-dark fallback.
  it("has a card shadow and an overlay shadow, offset with a soft blur, for both modes", () => {
    expect(css).toMatch(/--shadow-card: 0 1px 0 rgb\(26 25 22 \/ 0\.04\), 0 16px 40px -24px rgb\(26 25 22 \/ 0\.22\);/);
    expect(css).toMatch(/--shadow-overlay: 0 16px 40px -16px rgb\(26 25 22 \/ 0\.24\), 0 2px 6px -2px rgb\(26 25 22 \/ 0\.1\);/);
    expect(css.match(/--shadow-card: 0 /g)).toHaveLength(3);
    expect(css.match(/--shadow-overlay: 0 /g)).toHaveLength(3);
  });

  // Dark mode is its own set of steps, not a flip: every colour token the light set declares, the dark set declares.
  it("declares every colour token for dark mode too", () => {
    const light = css.slice(css.indexOf("\n:root {"), css.indexOf("\nhtml[data-theme=\"dark\"] {"));
    const dark = css.slice(css.indexOf("\nhtml[data-theme=\"dark\"] {"), css.indexOf("\n@media (prefers-color-scheme: dark)"));
    const names = (block: string) => [...block.matchAll(/^\s+(--[a-z-]+): #/gm)].map((m) => m[1]).sort();
    expect(names(dark)).toEqual(names(light));
    expect(dark).toContain("color-scheme: dark;");
  });

  it("is read through its utility: no component writes a token's mix inline", () => {
    const inline = Object.values(MIXES).map((mix) => mix.replaceAll(", ", ",").replaceAll(" ", "_"));
    const found = [...sources(join(root, "app")), ...sources(join(root, "components"))].flatMap((file) => {
      const text = readFileSync(file, "utf8");
      return inline.filter((mix) => text.includes(mix)).map((mix) => `${file}: ${mix}`);
    });
    expect(found).toEqual([]);
  });
});
