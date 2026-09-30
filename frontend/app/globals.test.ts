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
  "accent-strong": "color-mix(in oklab, var(--jacaranda) 84%, var(--ink))",
  "wash-soft": "color-mix(in oklab, var(--jacaranda-wash) 55%, var(--paper))",
  "error-wash": "color-mix(in oklab, var(--error) 7%, var(--field))",
  "ok-wash": "color-mix(in oklab, var(--ok) 7%, var(--field))",
  "error-line": "color-mix(in oklab, var(--error) 45%, var(--paper))",
  "ok-line": "color-mix(in oklab, var(--ok) 45%, var(--paper))",
  "accent-line": "color-mix(in oklab, var(--jacaranda) 35%, var(--paper))",
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

  it("has one overlay shadow, offset with a soft blur and tinted from ink", () => {
    expect(css).toMatch(/--shadow-overlay: 0 12px 28px -12px rgb\(22 35 47 \/ 0\.28\), 0 2px 6px -2px rgb\(22 35 47 \/ 0\.12\);/);
    expect(css.match(/--shadow-/g)).toHaveLength(1);
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
