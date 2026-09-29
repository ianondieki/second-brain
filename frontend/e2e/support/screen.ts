import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

/**
 * The page-level rules every screen keeps (same as e2e/auth.spec.ts): axe finds nothing serious or critical
 * (AC-UX-4), at most one primary action (AC-UX-2), and no horizontal scroll (AC-UX-1, at 360 px in mobile-360).
 */
export async function checkScreen(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    serious,
    JSON.stringify(
      serious.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) })),
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

/** Every empty state is one sentence and one action (AC-UX-5). */
export async function expectEmptyState(page: Page, sentence: string, action: string) {
  const empty = page.locator("[data-empty-state]");
  await expect(empty).toHaveCount(1);
  await expect(empty.locator("p")).toHaveText(sentence);
  await expect(empty.getByRole("link")).toHaveCount(1);
  await expect(empty.getByRole("link")).toHaveText(action);
}
