import { expect, test } from "@playwright/test";

import { checkScreen } from "./support/screen";
import { OWNER_DATABASE_URL, seedTransparencyRoots, type SeededRoots } from "./support/transparency-scene";

// REQ-AUD-01 (P28 track D, AT-D-1): the public /transparency page against the compose stack, in both projects (360 px
// and desktop). Three signed roots are seeded first (support/transparency-scene.ts; idempotent, append-only), so the
// populated page is asserted on every run: the latest root as the sheet, the seeded days in the ledger, a signature
// disclosure, the keys; strict axe, no primary action, no horizontal scroll (checkScreen). The empty state cannot be
// reached on a shared stack (the roots table is append-only) and is covered by the vitest suite.

const SERVER_STEP = { timeout: 20_000 };

let seeded: SeededRoots;

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL seeds the transparency roots").toBeTruthy();
  seeded = seedTransparencyRoots();
  expect(seeded.days, "three seeded roots (needs a registered provenance key)").toHaveLength(3);
});

test("the page shows the latest root, the earlier days and the keys, and meets the page rules", async ({ page }) => {
  await page.goto("/transparency");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Daily audit fingerprints");
  await expect(page).toHaveTitle(/Transparency/);

  const roots = page.locator("[data-transparency='roots']");
  await expect(roots.locator("[data-empty-state]")).toHaveCount(0);
  const latest = roots.locator("section[data-root]");
  await expect(latest).toHaveAttribute("data-root", seeded.newest.day);
  await expect(latest.getByRole("heading", { level: 2 })).toHaveText(/^The fingerprint for \d{1,2} \w{3} \d{4}$/);
  await expect(latest.locator("[data-fingerprint]")).toHaveAttribute("data-fingerprint", seeded.newest.root);

  for (const day of seeded.days) await expect(roots.locator(`[data-root="${day}"]`)).toHaveCount(1);

  // A day's signature opens in place (native disclosure, named with its day).
  const row = roots.locator("li[data-root]").first();
  await expect(row).toBeVisible();
  const summary = row.locator("summary");
  await expect(summary).toHaveAttribute("aria-label", /^Signature for \d{1,2} \w{3} \d{4}$/);
  await summary.click();
  await expect(row.locator("details")).toHaveAttribute("open", "");

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
