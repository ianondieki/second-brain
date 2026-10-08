import { expect, test } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkScreen } from "./support/screen";

// D-67 (P25; REQ-UX-01, REQ-UX-06): the command palette. From /dev, Ctrl K opens it (its code loads then), the keyboard
// reaches Discover, Enter goes there; Escape gives focus back; the open palette passes strict axe at both widths.

test("the palette opens with Ctrl K on /dev and jumps to Discover by keyboard", async ({ page }) => {
  await signUpDeveloper(page, "Njeri Kamau");
  const search = page.getByRole("banner").getByRole("button", { name: "Search or jump to" });
  await expect(search).toBeVisible();
  await checkScreen(page, { strict: true });

  await page.locator("body").press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Search or jump to" });
  await expect(dialog).toBeVisible();
  const combo = dialog.getByRole("combobox");
  await expect(combo).toBeFocused();
  await checkScreen(page, { strict: true });

  // Escape closes it and focus is back where it was.
  await combo.press("Escape");
  await expect(dialog).toHaveCount(0);

  await search.click();
  await expect(combo).toBeFocused();
  await combo.pressSequentially("disc");
  const discover = dialog.getByRole("option", { name: "Discover" });
  await expect(discover).toHaveAttribute("aria-selected", "true");
  await expect(combo).toHaveAttribute("aria-activedescendant", (await discover.getAttribute("id"))!);
  await expect(discover.locator("mark")).toHaveText("Disc");
  await combo.press("Enter");
  await expect(page).toHaveURL(/\/dev\/discover$/, { timeout: 20_000 });
  await expect(page.getByRole("navigation", { name: "Developer" }).getByRole("link", { name: "Discover" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});

test('"/" opens the palette outside a text field, and the arrows walk its options', async ({ page }) => {
  await signUpDeveloper(page, "Kiprono Bett");
  await page.locator("main").click({ position: { x: 4, y: 4 } });
  await page.keyboard.press("/");
  const dialog = page.getByRole("dialog", { name: "Search or jump to" });
  await expect(dialog).toBeVisible();
  const combo = dialog.getByRole("combobox");
  const options = dialog.getByRole("option");
  await expect(options.first()).toHaveAttribute("aria-selected", "true");
  await combo.press("ArrowDown");
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  await combo.press("End");
  await expect(options.last()).toHaveAttribute("aria-selected", "true");
  await combo.press("Escape");
  await expect(dialog).toHaveCount(0);
});
