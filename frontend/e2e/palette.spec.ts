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

  // Escape closes it and focus is back where it was (opened from the keyboard on the page: the Search button).
  await combo.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(search).toBeFocused();

  // Opened from the Search button with the keyboard: Escape, the Close button and the backdrop each give it focus back.
  await search.focus();
  await search.press("Enter");
  await expect(combo).toBeFocused();
  await combo.press("Escape");
  await expect(search).toBeFocused();
  await search.press("Enter");
  await dialog.getByRole("button", { name: /^Close/ }).click();
  await expect(search).toBeFocused();
  await search.press("Enter");
  await expect(combo).toBeFocused();
  // The listbox is not a Tab stop: Tab from the field goes to Close, then out of the list never into it.
  await combo.press("Tab");
  await expect(dialog.getByRole("button", { name: /^Close/ })).toBeFocused();
  await page.mouse.click(5, 600); // the backdrop, outside the dialog
  await expect(dialog).toHaveCount(0);
  await expect(search).toBeFocused();

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

test('Ctrl K opens the palette, "/" does not (no single-key shortcut), and the arrows walk its options', async ({ page }) => {
  await signUpDeveloper(page, "Kiprono Bett");
  await page.locator("main").click({ position: { x: 4, y: 4 } });
  await page.keyboard.press("/");
  const dialog = page.getByRole("dialog", { name: "Search or jump to" });
  await expect(dialog).toHaveCount(0);
  await page.keyboard.press("Control+k");
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

test("the palette searches the API: problems people raised, with the typed letters marked", async ({ page }) => {
  await signUpDeveloper(page, "Wambui Njoroge");
  await page.locator("body").press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Search or jump to" });
  await dialog.getByRole("combobox").pressSequentially("sacco");
  const problems = dialog.getByRole("group", { name: "Problems" });
  await expect(problems).toBeVisible({ timeout: 10_000 });
  await expect(problems.getByRole("option").first().locator("mark")).toHaveText(/sacco/i);
  await checkScreen(page, { strict: true });
  await dialog.getByRole("combobox").press("Escape");
});

test("Home greets on Nairobi's photograph and keeps the person's own last 26 weeks", async ({ page }) => {
  await signUpDeveloper(page, "Kamau Gitau");
  await expect(page.locator("[data-greeting]")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Kamau Gitau");
  const calendar = page.locator("[data-home='calendar']");
  await expect(calendar.getByRole("heading", { name: "Your last 26 weeks" })).toBeVisible();
  // A new account has done nothing yet: one sentence, no grid.
  await expect(calendar.locator("[data-activity='empty']")).toHaveText("Nothing yet: what you do on Wazo shows here, day by day.");
  await checkScreen(page, { strict: true });
});
