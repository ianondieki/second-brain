import { expect, test } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkScreen } from "./support/screen";

// The first-login tour (D-52; docs/spec/07): shows once on a new developer's home, is skippable from the first step,
// never a modal, and is remembered in this browser. The suite's storage state marks it done; this test clears that.
test.use({ storageState: { cookies: [], origins: [] } });

test("the first-login tour shows once, can be skipped, and stays away", async ({ page }) => {
  await signUpDeveloper(page);
  await expect(page).toHaveURL(/\/dev$/, { timeout: 60_000 });
  const tour = page.getByRole("dialog", { name: "This is your home" });
  await expect(tour).toBeVisible();
  await expect(tour).not.toHaveAttribute("aria-modal", "true");
  await expect(page.locator("[data-primary]")).toHaveCount(1); // the page's own, not the tour's button
  await checkScreen(page);
  await tour.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("dialog", { name: "Every idea gets a certificate" })).toBeVisible();
  await page.getByRole("button", { name: "Skip tour" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
