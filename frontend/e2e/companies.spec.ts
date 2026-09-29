import { expect, test, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkScreen, expectEmptyState } from "./support/screen";

// REQ-DIR-01 (F1): Developer › Companies against the compose stack with the provisional directory seeded
// (`python -m bridge.seed`, dev and test only), in both projects (360 px and desktop).

const SERVER_STEP = { timeout: 20_000 };

/** The organisation rows on the page. */
const rows = (page: Page) => page.locator("main article");

test("signed-out visits to the directory go to the login page", async ({ page }) => {
  for (const path of ["/dev/companies", "/dev/companies/01a0ecd8-2e13-71dd-809a-2e817be8fcf3"]) {
    await page.goto(path);
    await expect(page, path).toHaveURL(/\/login$/);
  }
});

test.describe("a signed-in developer", () => {
  test.beforeEach(async ({ page }) => {
    await signUpDeveloper(page);
  });

  test("reaches Companies from the developer navigation and browses by niche", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Developer" });
    const items = nav.getByRole("link");
    expect(await items.count()).toBeLessThanOrEqual(5); // AC-UX-1
    await expect(nav.getByRole("link", { name: "Home" })).toHaveAttribute("aria-current", "page");
    await nav.getByRole("link", { name: "Companies" }).click();
    await expect(page).toHaveURL(/\/dev\/companies$/, SERVER_STEP);
    await expect(nav.getByRole("link", { name: "Companies" })).toHaveAttribute("aria-current", "page");

    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Companies");
    await expect(page.locator("[data-primary]")).toHaveText("Show companies");
    expect(await page.getByRole("heading", { level: 2 }).count()).toBeGreaterThan(0); // niche headings
    const count = await rows(page).count();
    expect(count).toBeGreaterThan(0);
    for (const row of await rows(page).all()) {
      // Name, type/county and the verification badge; at most two chips (AC-UX-1), never a logo.
      await expect(row.getByRole("link")).toHaveCount(1);
      await expect(row.locator("[data-badge]")).toHaveCount(1);
      await expect(row.locator("img")).toHaveCount(0);
    }
    await checkScreen(page);
  });

  test("searches by name, filters by county, pages, and clears", async ({ page }) => {
    await page.goto("/dev/companies");
    await page.getByLabel("Search by name").fill("county government");
    await page.getByRole("button", { name: "Show companies" }).click();
    await expect(page).toHaveURL(/q=county\+government/, SERVER_STEP);
    for (const name of await rows(page).getByRole("link").allTextContents()) {
      expect(name.toLowerCase()).toContain("county government");
    }

    // Filters sit in a disclosure; picking a county narrows to it.
    await page.getByText("Filters", { exact: true }).click();
    await page.getByLabel("County").selectOption("KE-30"); // Nairobi City
    await page.getByRole("button", { name: "Show companies" }).click();
    await expect(page).toHaveURL(/county=KE-30/, SERVER_STEP);
    await expect(page.getByText("Filters (1 chosen)")).toBeVisible();
    expect(await rows(page).count()).toBeGreaterThan(0);
    for (const row of await rows(page).all()) await expect(row.locator("p").first()).toContainText("Nairobi");
    await checkScreen(page);

    await page.getByRole("link", { name: "Clear filters" }).click();
    await expect(page).toHaveURL(/\/dev\/companies$/, SERVER_STEP);

    // 85 seeded organisations at 30 a page: there is a next page, and from it a way back to the first.
    await page.getByRole("link", { name: "Next page" }).click();
    await expect(page).toHaveURL(/cursor=/, SERVER_STEP);
    await expect(rows(page).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "First page" })).toBeVisible();
  });

  test("an empty result is one sentence and one action", async ({ page }) => {
    await page.goto("/dev/companies?q=no%20organisation%20has%20this%20name");
    await expectEmptyState(page, "No organisations match these filters.", "Clear filters");
    await checkScreen(page);
    await page.getByRole("link", { name: "Clear filters" }).click();
    await expect(rows(page).first()).toBeVisible(SERVER_STEP);

    await page.goto("/dev/companies?cursor=not-a-cursor");
    await expectEmptyState(page, "The list changed after this page loaded.", "First page");
  });

  test("opens an organisation's page, and an unknown one reads as not listed", async ({ page }) => {
    await page.goto("/dev/companies");
    const first = rows(page).first();
    const name = (await first.getByRole("link").textContent())?.trim() ?? "";
    await first.getByRole("link").click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(name, SERVER_STEP);
    await expect(page.locator("[data-badge]")).toHaveCount(1);
    await expect(page.getByRole("term")).toContainText(["Organisation type", "County", "Niches"]);
    await checkScreen(page);

    await page.goto("/dev/companies/00000000-0000-4000-8000-000000000000");
    await expectEmptyState(page, "This organisation is not in the directory.", "All companies");
  });
});
