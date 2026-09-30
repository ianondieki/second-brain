import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

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
