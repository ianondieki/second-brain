import { expect, test } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkScreen } from "./support/screen";

// The first-login tour (D-52; docs/spec/07): shows once on a new developer's home, is skippable from the first step,
// never a modal, and is remembered in this browser. The suite's storage state marks it done; this test clears that.
// P23-2: it is a slide show that advances every six seconds on the page's clock (Playwright's, installed here), stops
// for Pause, goes back with Back, and holds still under the person's hand.
test.use({ storageState: { cookies: [], origins: [] } });

test("the first-login tour shows once, slides on, pauses, goes back, can be skipped, and stays away", async ({ page }) => {
  await signUpDeveloper(page);
  await expect(page).toHaveURL(/\/dev$/, { timeout: 60_000 });
  // The page's timers on a clock the test moves (paused, so the checks below take no step's time); the tour is not
  // done yet, so it shows again after the reload.
  const now = Date.now();
  await page.clock.install({ time: now });
  await page.clock.pauseAt(now + 1_000);
  await page.reload();
  const first = page.getByRole("dialog", { name: "This is your home" });
  await expect(first).toBeVisible();
  await expect(first).not.toHaveAttribute("aria-modal", "true");
  await expect(page.locator("[data-primary]")).toHaveCount(1); // the page's own, not the tour's buttons
  await expect(page.locator("[data-tour] [data-primary]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();

  // Six seconds on: the next step slides in, and the live region says so; focus stays where it was.
  await page.mouse.move(0, 0);
  await page.clock.runFor(6_000);
  await expect(page.getByRole("dialog", { name: "Every idea gets a certificate" })).toBeVisible();
  await expect(page.locator("[data-tour] [aria-live='polite']")).toHaveText("Step 2 of 3: Every idea gets a certificate");

  // Pause holds it however long the clock runs.
  const pause = page.getByRole("button", { name: "Pause" });
  await pause.click();
  await expect(pause).toHaveAttribute("aria-pressed", "true");
  await page.mouse.move(0, 0);
  await page.clock.runFor(18_000);
  await expect(page.getByRole("dialog", { name: "Every idea gets a certificate" })).toBeVisible();
  // The page rules with the tour open (axe needs the page's own timers, so the clock runs again; Pause holds the tour).
  await page.clock.resume();
  await checkScreen(page, { strict: true });

  await page.getByRole("button", { name: "Back" }).click();
  await expect(page.getByRole("dialog", { name: "This is your home" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Back" })).toHaveCount(0);

  await page.getByRole("button", { name: "Skip tour" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
