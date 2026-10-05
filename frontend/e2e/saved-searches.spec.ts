import { expect, test, type APIRequestContext } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkWidths } from "./support/discover-scene";

// REQ-PERS-03, REQ-TREND-02 (P21 track C, D-57 (7)) against the compose stack, in both projects: a developer saves a
// Discover search with words, niche and county, applies it from the Saved searches panel, turns its alerts off, deletes
// it, meets the cap of 10, and turns on the saved-search digest in notification settings (off by default, C6). Every
// screen keeps the page rules at 360, 375 and 1440 px.

const SERVER_STEP = { timeout: 20_000 };
const SEARCH = "/dev/discover?niche=agriculture&county=KE-32&words=water";

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

test.describe("saved Discover searches", () => {
  test.setTimeout(120_000);
  test.beforeEach(async ({ page }) => {
    await signUpDeveloper(page, "Wanjiku Mwangi");
  });

  test("save, apply, alerts off, delete", async ({ page }, info) => {
    await page.goto(SEARCH);
    await expect(page.getByRole("searchbox", { name: "Words in a problem" })).toHaveValue("water");
    const strip = page.locator("[data-saved-searches]");
    await expect(strip.locator("[data-saved-empty]")).toHaveText(
      "Save the list and filters you use, to come back in one tap and hear about new matches.",
    );
    await checkWidths(page, info);

    // Save: a suggested name, what it keeps, alerts on by default.
    await strip.getByRole("button", { name: "Save this search" }).click();
    const name = strip.getByRole("textbox", { name: "Name" });
    await expect(name).toHaveValue(/^Agriculture in /);
    await expect(strip.getByRole("checkbox", { name: "Tell me each morning when something new matches" })).toBeChecked();
    await checkWidths(page, info);
    await name.fill("Water in the fields");
    await strip.getByRole("button", { name: "Save search" }).click();
    await expect(strip.getByRole("status")).toHaveText("Saved: Water in the fields.", SERVER_STEP);
    const saved = strip.getByRole("listitem").filter({ hasText: "Water in the fields" });
    await expect(saved.locator("[data-facts]")).toContainText("“water”");
    await expect(saved.getByRole("switch", { name: "Alerts Water in the fields" })).toHaveAttribute("aria-checked", "true");
    await checkWidths(page, info);

    // Apply it from a plain Discover: the name is the link, the words come back in the box.
    await page.goto("/dev/discover");
    await strip.getByRole("button", { name: "Saved searches (1)" }).click();
    await strip.getByRole("link", { name: "Water in the fields" }).click();
    await expect(page).toHaveURL(/\/dev\/discover\?niche=agriculture&county=KE-32&words=water$/, SERVER_STEP);
    await expect(page.getByRole("searchbox", { name: "Words in a problem" })).toHaveValue("water");

    // Alerts off, kept after a reload.
    await strip.getByRole("button", { name: "Saved searches (1)" }).click();
    const alerts = strip.getByRole("switch", { name: "Alerts Water in the fields" });
    await alerts.click();
    await expect(alerts).toHaveAttribute("aria-checked", "false");
    await page.waitForLoadState("networkidle");
    await page.reload();
    await strip.getByRole("button", { name: "Saved searches (1)" }).click();
    await expect(strip.getByRole("switch", { name: "Alerts Water in the fields" })).toHaveAttribute("aria-checked", "false");
    await checkWidths(page, info);

    // Delete behind a confirmation; the strip is its empty state again.
    await strip.getByRole("button", { name: "Delete Water in the fields" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this saved search?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(dialog).toBeHidden(SERVER_STEP);
    await expect(strip.locator("[data-saved-empty]")).toBeVisible();
    await expect(strip.getByRole("status")).toHaveText("Deleted: Water in the fields.");
    await checkWidths(page, info);
  });

  test("ten is the most: the eleventh is refused and Save says why", async ({ page }, info) => {
    const headers = { "X-CSRF-Token": await csrf(page.request) };
    for (let i = 1; i <= 10; i++) {
      const response = await page.request.post("/api/me/saved-searches", {
        headers,
        data: { name: `Search ${i}`, view: i % 2 ? "problems" : "briefs", words: `word${i}` },
      });
      expect(response.status(), await response.text()).toBe(201);
    }
    const eleventh = await page.request.post("/api/me/saved-searches", { headers, data: { name: "Eleven", view: "problems" } });
    expect(eleventh.status()).toBe(409);

    await page.goto("/dev/discover?view=briefs");
    const strip = page.locator("[data-saved-searches]");
    const save = strip.getByRole("button", { name: "Save this search" });
    await expect(save).toHaveAttribute("aria-disabled", "true");
    await expect(strip.locator("[data-saved-limit]")).toHaveText(
      "You have 10 saved searches, the most you can keep. Delete one to save this search.",
    );
    await save.click({ force: true }); // aria-disabled, yet a person can still press it: nothing opens
    await expect(strip.getByRole("textbox", { name: "Name" })).toHaveCount(0);
    await strip.getByRole("button", { name: "Saved searches (10)" }).click();
    await expect(strip.getByRole("listitem")).toHaveCount(10);
    await checkWidths(page, info);
  });

  test("the daily email is off by default and can be turned on in notification settings", async ({ page }, info) => {
    await page.goto("/settings/notifications");
    const email = page.getByRole("group", { name: "Email" });
    const digest = email.getByRole("checkbox", {
      name: "Send me a daily email with how many new problems or Briefs match my saved searches.",
    });
    await expect(digest).not.toBeChecked();
    await checkWidths(page, info);
    await digest.check();
    await page.getByRole("button", { name: "Save choices" }).click();
    await expect(page.getByText("Your choices are saved.")).toBeVisible(SERVER_STEP);
    await page.reload();
    await expect(digest).toBeChecked();
  });
});
