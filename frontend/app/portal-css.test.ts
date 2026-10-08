// @vitest-environment node
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// D-67 (P25; REQ-UX-06): the organisation portal's, the console's and the signed-out screens' styles (app/portal.css),
// imported by globals.css so every page has them with no script: what moves stands still under reduced motion,
// forced colours keep the shapes a fill alone drew, long lists skip off-screen rows, headers stay in view.

const portal = readFileSync(join(process.cwd(), "app/portal.css"), "utf8");
const globals = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");

/** Every `@media <query> {` block's body (balanced braces), joined. */
function media(query: string): string {
  let out = "";
  let from = 0;
  for (;;) {
    const start = portal.indexOf(`@media ${query} {`, from);
    if (start < 0) return out;
    let depth = 0;
    for (let i = portal.indexOf("{", start); i < portal.length; i += 1) {
      if (portal[i] === "{") depth += 1;
      if (portal[i] === "}" && --depth === 0) {
        out += portal.slice(start, i);
        from = i;
        break;
      }
    }
  }
}

describe("portal.css", () => {
  it("is imported by globals.css, right after Tailwind", () => {
    expect(globals.split("\n").slice(0, 2)).toEqual(['@import "tailwindcss";', '@import "./portal.css";']);
  });

  it("stops the shortlist star's pop under reduced motion", () => {
    expect(portal).toMatch(/\[data-pop\] > svg \{\s*animation: star-pop/);
    expect(media("(prefers-reduced-motion: reduce)")).toMatch(/\[data-pop\] > svg \{\s*animation: none/);
  });

  it("keeps the shapes a fill drew in forced colours: the greeting band, the decision panel, the notice's disc", () => {
    const forced = media("(forced-colors: active)");
    for (const selector of [".org-greet", ".decision-panel", ".notice-mark", ".item-card:has(.item-card-link:focus-visible)"]) {
      expect(forced, selector).toContain(selector);
    }
  });

  it("skips off-screen notifications and keeps each day's name in view", () => {
    expect(portal).toMatch(/\.notice-row \{\s*content-visibility: auto;/);
    expect(portal).toMatch(/\.notice-day \{\s*position: sticky;/);
  });

  it("aligns a row of cards part by part (subgrid) and focuses the card around its one link", () => {
    expect(portal).toMatch(/\.item-grid > li \{[^}]*grid-template-rows: subgrid;/);
    expect(portal).toMatch(/\.item-card:has\(\.item-card-link:focus-visible\) \{\s*outline: 2px solid var\(--accent\);/);
  });

  it("puts the Brief's preview beside the form from 1024 px and under its sections before", () => {
    expect(portal).toContain('grid-template-areas: "fields" "aside" "submit";');
    expect(portal).toContain('grid-template-areas: "fields aside" "submit aside";');
  });
});
