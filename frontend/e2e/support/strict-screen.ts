import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page } from "@playwright/test";

import { settled } from "./screen";

/**
 * The stricter page check of the screens P16 part C2 polished (the organisation portal, the shared tracker and the
 * staff console): everything `checkScreen` asks (at most one primary action, AC-UX-2; no horizontal scroll, AC-UX-1)
 * and axe finds no violation of any impact, not only serious or critical ones (P16-C2 card, item 7). Same rule tags
 * as `checkScreen`; `exclude` as there, for frames that run no script (the marked Tier-2 page).
 */
export async function checkScreenStrict(page: Page, { exclude = [] }: { exclude?: string[] } = {}) {
  await settled(page);
  let axe = new AxeBuilder({ page }).withTags([
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
    "wcag22aa",
    "best-practice",
  ]);
  for (const selector of exclude) axe = axe.exclude(selector);
  const { violations } = await axe.analyze();
  expect(
    violations,
    JSON.stringify(
      violations.map((v) => ({ id: v.id, impact: v.impact, targets: v.nodes.map((n) => n.target) })),
      null,
      2,
    ),
  ).toEqual([]);
  expect(await page.locator("[data-primary]").count()).toBeLessThanOrEqual(1);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "horizontal scroll").toBeLessThanOrEqual(0);
}

/**
 * Stacked row links each keep their own tap area (WCAG 2.2 target size, docs/spec/07 item 6), measured as the person
 * taps them: a link stretched over its row (`::after` absolutely positioned at inset 0, as Row draws it) is measured
 * as the row it covers; any other link as its own box. Every area is at least 44 px tall and no two overlap. Without
 * the stretch, a row title's own box (one line of text) is under 44 px, so the check fails.
 */
export async function expectSeparateTapTargets(targets: Locator) {
  await settled(targets.page());
  const boxes = [];
  for (const target of await targets.all()) {
    const box = await target.evaluate((element) => {
      const after = getComputedStyle(element, "::after");
      let rect = element.getBoundingClientRect();
      const stretched =
        after.content !== "none" &&
        after.position === "absolute" &&
        ["top", "right", "bottom", "left"].every((side) => after.getPropertyValue(side) === "0px");
      if (stretched) {
        let block = element.parentElement;
        while (block && getComputedStyle(block).position === "static") block = block.parentElement;
        if (block) rect = block.getBoundingClientRect();
      }
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, name: element.textContent ?? "" };
    });
    boxes.push(box);
  }
  expect(boxes.length).toBeGreaterThan(0);
  for (const box of boxes) expect(box.height, box.name).toBeGreaterThanOrEqual(44);
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const [a, b] = [boxes[i], boxes[j]];
      // Rows share their hairline edge: touching is not overlapping.
      const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height - 0.5 && b.y < a.y + a.height - 0.5;
      expect(overlap, `${a.name} overlaps ${b.name}`).toBe(false);
    }
  }
}
