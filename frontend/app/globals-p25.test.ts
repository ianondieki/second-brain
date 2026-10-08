// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// D-67 (P25; REQ-UX-06): the HCI floor and the motion primitives live in globals.css, so every page inherits them
// with no script. These read the stylesheet: what moves stands still under reduced motion; forced colours keep the
// focus ring and the shapes that a fill alone drew; more contrast darkens the secondary ink and the lines.

const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
const reduced = css.slice(css.lastIndexOf("@media (prefers-reduced-motion: reduce) {"));

/** The body of the first `@media <query> {` block (balanced braces). */
function media(query: string): string {
  const start = css.indexOf(`@media ${query} {`);
  expect(start, query).toBeGreaterThanOrEqual(0);
  let depth = 0;
  for (let i = css.indexOf("{", start); i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    if (css[i] === "}" && --depth === 0) return css.slice(start, i);
  }
  return "";
}

describe("reduced motion", () => {
  it("stops the palette's entrance and every view transition", () => {
    expect(reduced).toMatch(/\.palette\[open\] \{\s*animation: none !important;/);
    expect(reduced).toMatch(/::view-transition-group\(\*\),\s*::view-transition-old\(\*\),\s*::view-transition-new\(\*\) \{\s*animation: none !important;/);
    expect(reduced).toContain(".count,"); // CountUp's figures stand at their value
  });

  it("keeps the route cross-fade short and eased out, and the root still", () => {
    // Both sides in the same time and curve: blended, what does not change between the pages stays still.
    expect(css).toMatch(/::view-transition-old\(\.page-exit\) \{\s*animation: vt-fade-out 180ms var\(--ease-out\) both;/);
    expect(css).toMatch(/::view-transition-new\(\.page-enter\) \{\s*animation: vt-fade-in 180ms var\(--ease-out\) both;/);
    expect(css).toMatch(/::view-transition-group\(nav-current\),\s*::view-transition-group\(\.title-morph\) \{\s*animation-duration: 220ms;/);
    expect(css).toMatch(/::view-transition-old\(root\),\s*::view-transition-new\(root\) \{\s*animation: none;/);
  });

  it("gives a pressed button a 1 px settle in 120 ms", () => {
    expect(css).toMatch(/\.btn:active \{\s*transform: translateY\(1px\);\s*transition-duration: 120ms;/);
  });
});

describe("the HCI floor", () => {
  it("draws one focus ring, in the system highlight under forced colours, and keeps drawn shapes", () => {
    expect(css).toMatch(/:focus-visible \{\s*outline: var\(--focus-ring\);\s*outline-offset: var\(--focus-offset\);/);
    const forced = media("(forced-colors: active)");
    expect(forced).toMatch(/:focus-visible \{\s*outline: 2px solid Highlight;/);
    for (const shape of [".btn", "[data-chip]", ".search-pill", '.nav-item[aria-current="page"]']) expect(forced).toContain(shape);
    expect(forced).toContain("border: 1px solid CanvasText;");
    expect(forced).toMatch(/\.palette-option\[aria-selected="true"\] \{\s*outline: 2px solid Highlight;/);
  });

  it("darkens the secondary ink and the lines when more contrast is asked for", () => {
    const more = media("(prefers-contrast: more)");
    expect(more).toContain("--ink-soft: #3f3a52;");
    expect(more).toContain("--line: #9d9584;");
  });

  it("keeps a focused control clear of the sticky top bar from 1024 px", () => {
    expect(css).toMatch(/html:has\(\[data-top-bar\]\[data-sticky\]\) \{\s*scroll-padding-block-start: 5\.5rem;/);
  });

  it("has container queries, subgrid rows for card grids, content-visibility and tabular figures", () => {
    expect(css).toMatch(/\.cq \{\s*container-type: inline-size;/);
    expect(css).toMatch(/\.card-grid > \.card-sub,\s*\.card-sub > \.card-sub \{[^}]*grid-template-rows: subgrid;/);
    expect(css).toMatch(/\.cv-auto \{\s*content-visibility: auto;\s*contain-intrinsic-size: auto var\(--cv-size, 9rem\);/);
    expect(css).toMatch(/td,\s*th,\s*time,\s*\.figure \{\s*font-variant-numeric: tabular-nums lining-nums;/);
    expect(css).toContain("@container page-hero (width >= 40rem)");
  });

  it("never puts cv-auto on a subgrid card (layout containment would cut it off the row's shared tracks)", () => {
    const files = (readdirSync(process.cwd(), { recursive: true }) as string[]).filter(
      (file) => /\.tsx$/.test(file) && !/(^|\/)(node_modules|\.next)\//.test(file),
    );
    expect(files.length).toBeGreaterThan(50);
    const both = files.filter((file) =>
      (readFileSync(join(process.cwd(), file), "utf8").match(/className=\{?["`][^"`]*["`]/g) ?? []).some(
        (name) => /\bcard-sub\b/.test(name) && /\bcv-auto\b/.test(name),
      ),
    );
    expect(both).toEqual([]);
  });

  it("sets the hero's eyebrow in the mono face, sentence case (no capitals transform)", () => {
    const eyebrow = css.slice(css.indexOf(".page-eyebrow {"), css.indexOf("}", css.indexOf(".page-eyebrow {")));
    expect(eyebrow).toContain("font-family: var(--font-mono);");
    expect(eyebrow).not.toContain("text-transform");
  });
});
