import { expect, test } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { draftIdea, runTag } from "./support/pitch-scene";

// D-67 (P25; REQ-UX-06): My ideas' cards share their grid's rows (subgrid), so in a row of cards the meta lines start
// at the same height even when one title wraps over several lines.

test("two idea cards in a row put their meta lines at the same height", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signUpDeveloper(page, "Atieno Ouma");
  const tag = runTag();
  await draftIdea(page.request, `Short ${tag}`);
  await draftIdea(page.request, `A much longer idea title that wraps over two or three lines on a card ${tag}`);
  await page.goto("/dev/ideas");

  const cards = page.locator("article[data-idea]");
  await expect(cards).toHaveCount(2);
  const [first, second] = [await cards.nth(0).boundingBox(), await cards.nth(1).boundingBox()];
  expect(first?.y, "the two cards share a row at 1440 px").toBe(second?.y);
  const titles = [await cards.nth(0).locator("h2").boundingBox(), await cards.nth(1).locator("h2").boundingBox()];
  expect(Math.abs((titles[0]?.height ?? 0) - (titles[1]?.height ?? 0)), "one title wraps further").toBeGreaterThan(10);
  const metaTop = async (n: number) => (await cards.nth(n).locator(":scope > p").boundingBox())?.y;
  expect(await metaTop(0)).toBe(await metaTop(1));
});
