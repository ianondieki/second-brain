import { expect, test } from "@playwright/test";

import { checkScreen } from "./support/screen";

// REQ-AUD-01 (P28 track D, AT-D-1): the public /transparency page against the compose stack, in both projects (360 px
// and desktop). Before the first nightly run there is no root, so the page shows either the latest root with the
// earlier days or the one-sentence empty state; the signing keys show either way. Strict axe, no primary action, no
// horizontal scroll (checkScreen), and the way to /verify works.

const SERVER_STEP = { timeout: 20_000 };

test("the page shows the roots or its empty state, the keys, and meets the page rules", async ({ page }) => {
  await page.goto("/transparency");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Daily audit fingerprints");
  await expect(page).toHaveTitle(/Transparency/);

  const roots = page.locator("[data-transparency='roots']");
  const latest = roots.locator("[data-root]").first();
  const empty = roots.locator("[data-empty-state]");
  await expect(latest.or(empty)).toBeVisible();
  if (await empty.count()) {
    await expect(empty.locator("p")).toHaveText("The first daily fingerprint appears after the first full day.");
    await expect(empty.getByRole("link")).toHaveText(["Check a certificate"]);
  } else {
    await expect(latest.getByRole("heading", { level: 2 })).toHaveText(/^The fingerprint for \d{1,2} \w{3} \d{4}$/);
    await expect(latest.locator("[data-fingerprint]")).toHaveAttribute("data-fingerprint", /^[0-9a-f]{64}$/);
  }

  const keys = page.locator("[data-transparency='keys']");
  await expect(keys.getByRole("heading", { level: 2 })).toHaveText("Signing keys");
  await expect(keys.locator("[data-key]").first()).toBeVisible();
  await expect(keys.locator("[data-key-status]").first()).toHaveText(/In use|Retired/);

  await expect(page.locator("[data-primary]")).toHaveCount(0);
  await checkScreen(page, { strict: true });
});

test("how to check a certificate leads to /verify, and /verify and the footer lead back", async ({ page }) => {
  await page.goto("/transparency");
  await page.locator("[data-transparency='how-to']").getByRole("link", { name: "Check a certificate" }).click();
  await expect(page).toHaveURL(/\/verify$/, SERVER_STEP);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Check an authorship certificate");

  await page.getByRole("complementary").getByRole("link", { name: "transparency page" }).click();
  await expect(page).toHaveURL(/\/transparency$/, SERVER_STEP);

  await page.goto("/");
  await page.getByRole("contentinfo").getByRole("link", { name: "Transparency" }).click();
  await expect(page).toHaveURL(/\/transparency$/, SERVER_STEP);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Daily audit fingerprints");
});
