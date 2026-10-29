import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page } from "@playwright/test";

/**
 * The page has settled: after an in-app navigation the new page's <title> arrives with its streamed metadata, a moment
 * after its content, so a check that reads the whole document (axe's document-title) waits for it.
 */
export async function settled(page: Page) {
  await expect(page).toHaveTitle(/\S/);
  // A colour transition still running (a button that just changed variant, 150 ms) would let axe measure a colour
  // halfway between two states; wait for every finite animation and transition to finish first. Infinite ones (a
  // pending hint's pulse) never finish and are left out, and so are scroll-driven ones (the landing's reveal, P23-2),
  // which follow the scroll position rather than time and stay "running" while they are attached (checkScreen makes
  // sure axe still reads those items: see revealsAtRest).
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every(
        (a) =>
          a.playState !== "running" ||
          a.effect?.getTiming().iterations === Infinity ||
          !(a.timeline instanceof DocumentTimeline),
      ),
  );
}

/**
 * The page-level rules every screen keeps (same as e2e/auth.spec.ts): axe finds nothing serious or critical
 * (AC-UX-4), at most one primary action (AC-UX-2), and no horizontal scroll (AC-UX-1, at 360 px in mobile-360).
 * `exclude`: selectors axe leaves out, for frames that run no script (axe cannot run inside them and would wait for
 * each one), such as the API's marked Tier-2 page in its sandbox. The caller checks what axe then skips (for a frame,
 * its title). `strict`: no axe violation of any impact at all (minor and moderate too), the P16 polish's rule for the
 * screens it finished (docs/platform/tasks/P16-C1.md, item 7).
 */
/**
 * Items that reveal on scroll (globals.css .reveal) are partly transparent while they come into view, and axe skips what it
 * cannot see. When any is not fully opaque where the page stands, the axe pass runs under reduced motion, where they
 * sit in place; a page scrolled through first (e2e/smoke.spec.ts) is checked with its motion as it is.
 */
async function revealsAtRest(page: Page): Promise<boolean> {
  return page.evaluate(() => [...document.querySelectorAll(".reveal")].every((el) => getComputedStyle(el).opacity === "1"));
}

export async function checkScreen(page: Page, { exclude = [], strict = false }: { exclude?: string[]; strict?: boolean } = {}) {
  await settled(page);
  const reduce = !(await revealsAtRest(page));
  if (reduce) await page.emulateMedia({ reducedMotion: "reduce" });
  let axe = new AxeBuilder({ page }).withTags([
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
    "wcag22aa",
    "best-practice",
  ]);
  for (const selector of exclude) axe = axe.exclude(selector);
  const results = await axe.analyze();
  if (reduce) await page.emulateMedia({ reducedMotion: null });
  const failing = strict
    ? results.violations
    : results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(
    failing,
    JSON.stringify(
      failing.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) })),
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

/**
 * Stacked links each keep their own tap area (WCAG 2.2 target size, docs/spec/07 item 6): every box is at least
 * 44 px tall and no two boxes overlap.
 */
export async function expectSeparateTargets(targets: Locator) {
  await settled(targets.page());
  const boxes = [];
  for (const target of await targets.all()) {
    const box = await target.boundingBox();
    expect(box, (await target.textContent()) ?? "").not.toBeNull();
    boxes.push({ name: (await target.textContent()) ?? "", ...box! });
  }
  expect(boxes.length).toBeGreaterThan(0);
  for (const box of boxes) expect(box.height, box.name).toBeGreaterThanOrEqual(44);
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const [a, b] = [boxes[i], boxes[j]];
      const overlap = a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
      expect(overlap, `${a.name} overlaps ${b.name}`).toBe(false);
    }
  }
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
