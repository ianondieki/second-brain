import { expect, test, type Locator, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkWidths, publishedProblemTitle, seededTrend, shot } from "./support/discover-scene";
import { expectEmptyState } from "./support/screen";

// REQ-TREND-02, REQ-PERS-01, REQ-PERS-03 (P12-F): the M2 walkthrough's step 4 against the compose stack with the demo
// seed (as the CI e2e job runs it): a new developer picks liked niches, sees Discover with trending problems, their
// badges, chips and sources, trending projects beside their problems (AC-TREND-2) and the opportunity gap, sees
// "Recommended for you" on Home with the pursuit chip, a Why chip and the reasons (AC-PERS-1, AC-PERS-2 at 360 px),
// and opens a problem card. Every screen keeps the page rules at 360, 375 and 1440 px (axe, at most one primary
// action, no horizontal scroll). E2E_SHOTS_DIR saves screenshots at 375 px and 1440 px for the task card.

const SERVER_STEP = { timeout: 20_000 };
const PURSUIT_CHIP = /^(Pursue|Consider|Not now) · (Strong fit|Good fit|Stretch)$/;

const recommended = (page: Page) => page.locator("[data-home=recommended]");

/** At most two chips on every card (docs/spec/07 item 2, AC-UX-1); the rest are listed when a card is expanded. */
async function expectAtMostTwoChips(cards: Locator) {
  for (const card of await cards.all()) expect(await card.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
}

test("signed-out visits to Discover and the niches page go to the login page", async ({ page }) => {
  for (const path of ["/dev/discover", "/dev/discover?view=gap", "/dev/discover/niches"]) {
    await page.goto(path);
    await expect(page, path).toHaveURL(/\/login$/);
  }
});

test.describe("a new developer", () => {
  test.beforeEach(async ({ page }) => {
    await signUpDeveloper(page, "Wanjiku Mwangi");
  });

  test("picks liked niches, sees Discover and Home recommendations with their chips, and opens a problem card", async ({
    page,
  }, info) => {
    test.setTimeout(150_000); // one walk through five screens, each checked at two widths on the mobile project
    const trend = await seededTrend(page.request);

    // Home before any niche: the picker prompt is the section's empty state (one sentence, one action).
    const section = recommended(page);
    await expect(section.getByRole("heading", { level: 2 })).toHaveText("Recommended for you");
    await expect(section.locator("[data-empty-state] p")).toHaveText(
      "Choose 3 to 5 niches you like to get problems recommended to you.",
    );
    await checkWidths(page, info);
    await section.getByRole("link", { name: "Choose your niches" }).click();

    // The picker: 3 to 5, checked before sending; it can change but never be cleared.
    await expect(page).toHaveURL(/\/dev\/discover\/niches$/, SERVER_STEP);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Niches you like");
    await expect(page.locator("[data-primary]")).toHaveText("Save niches");
    await page.getByLabel("Networks & Telecommunications").check();
    await page.getByLabel("Microfinance & SACCOs").check();
    await expect(page.getByText("2 of 5 chosen")).toBeVisible();
    await page.getByRole("button", { name: "Save niches" }).click();
    await expect(page.getByText("Choose at least 3 niches.")).toBeVisible();
    await page.getByLabel("Health").check();
    await page.getByRole("button", { name: "Save niches" }).click();
    await expect(page.getByText("Saved. Your recommendations now use these niches.")).toBeVisible(SERVER_STEP);
    await expect(page.locator("[data-profiling=off]")).toHaveText("Off: only your niches and county are used.");
    await checkWidths(page, info);
    await shot(page, info, "p12f-niches");
    await page.reload();
    for (const name of ["Networks & Telecommunications", "Microfinance & SACCOs", "Health"]) {
      await expect(page.getByLabel(name)).toBeChecked();
    }

    // Discover, from the developer navigation (five items at most).
    const nav = page.getByRole("navigation", { name: "Developer" });
    expect(await nav.getByRole("link").count()).toBeLessThanOrEqual(5);
    await nav.getByRole("link", { name: "Discover" }).click();
    await expect(page).toHaveURL(/\/dev\/discover$/, SERVER_STEP);
    await expect(nav.getByRole("link", { name: "Discover" })).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Discover");
    await expect(page.getByRole("heading", { level: 2 })).toHaveText("Trending problems");
    const problems = page.locator("article[data-problem]");
    expect(await problems.count()).toBeGreaterThan(0);
    expect(await problems.count()).toBeLessThanOrEqual(20);
    await expectAtMostTwoChips(problems);

    // The demo's trending problem: its self-explaining badge, a Why chip, its sources and the project beside it.
    const card = page.locator(`article[data-problem="${trend.problemId}"]`);
    await expect(card).toHaveAttribute("data-trending", "");
    await expect(card.locator("[data-badge]")).toContainText(/^Trending in .+: .+/);
    expect(await card.locator("[data-chip=why]").count()).toBeGreaterThanOrEqual(1);
    await expect(card.getByRole("link", { name: trend.title })).toHaveAttribute("href", `/problems/${trend.problemId}`);
    await card.getByText("More about this problem").click();
    await expect(card.getByRole("heading", { name: "Newest sources" })).toBeVisible();
    await expect(card.getByRole("heading", { name: "Projects solving it" })).toBeVisible();
    await checkWidths(page, info);
    await shot(page, info, "p12f-discover");

    // Trending projects, each beside the problem it solves (AC-TREND-2), never counting organisations.
    await page.getByRole("navigation", { name: "Lists" }).getByRole("link", { name: "Projects" }).click();
    await expect(page).toHaveURL(/view=projects/, SERVER_STEP);
    await expect(page.getByRole("heading", { level: 2 })).toHaveText("Trending projects");
    const projects = page.locator("article[data-project]");
    expect(await projects.count()).toBeGreaterThan(0);
    for (const project of await projects.all()) {
      await expect(project.locator("[data-solves] a")).toHaveAttribute("href", /^\/problems\/[0-9a-f-]{36}$/);
      await expect(project).not.toContainText(/\d+ (companies|organisations)/);
    }
    await expectAtMostTwoChips(projects);
    await expect(page.locator(`[data-solves="${trend.problemId}"]`).first()).toBeVisible();
    await checkWidths(page, info);
    await shot(page, info, "p12f-projects");

    // The opportunity gap: under-served rising problems only.
    await page.getByRole("navigation", { name: "Lists" }).getByRole("link", { name: "Opportunity gap" }).click();
    await expect(page).toHaveURL(/view=gap/, SERVER_STEP);
    await expect(page.getByRole("heading", { level: 2 })).toHaveText("Opportunity gap");
    for (const count of await page.locator("article[data-problem] [data-proposals]").all()) {
      expect(Number(await count.getAttribute("data-proposals"))).toBeLessThan(3);
    }
    await checkWidths(page, info);

    // Niche filter: the list narrows to that niche, and the choice shows on the disclosure.
    await page.goto("/dev/discover");
    await page.getByText("Filters", { exact: true }).click();
    await page.getByLabel("Niche").selectOption("networks-telecommunications");
    await page.getByRole("button", { name: "Show" }).click();
    await expect(page).toHaveURL(/niche=networks-telecommunications/, SERVER_STEP);
    await expect(page.getByText("Filters (1 chosen)")).toBeVisible();
    expect(await problems.count()).toBeGreaterThan(0);
    for (const problem of await problems.all()) await expect(problem).toContainText("Networks & Telecommunications");
    await checkWidths(page, info);

    // Home: recommendations with the pursuit chip, one Why chip, the reasons, Why and Why not on demand.
    await nav.getByRole("link", { name: "Home" }).click();
    await expect(page).toHaveURL(/\/dev$/, SERVER_STEP);
    await expect(section.locator("[data-personalised]")).toHaveAttribute("data-personalised", "off");
    await expect(section.getByRole("link", { name: "Recommendation settings" })).toHaveAttribute(
      "href",
      "/dev/discover/niches#profiling",
    );
    const rows = section.locator("article[data-recommendation]");
    expect(await rows.count()).toBeGreaterThan(0);
    expect(await rows.count()).toBeLessThanOrEqual(3);
    for (const row of await rows.all()) {
      await expect(row.locator("[data-chip=pursuit]")).toHaveText(PURSUIT_CHIP);
      await expect(row.locator("[data-chip=why]")).toHaveCount(1);
      await expect(row.locator("[data-chip]")).toHaveCount(2);
      for (const chip of await row.locator("[data-chip]").all()) await expect(chip).not.toContainText(/profit|revenue/i);
    }
    const first = rows.first();
    await first.getByText("Why this, and why not").click();
    await expect(first.getByRole("heading", { name: /^Why “(Pursue|Consider|Not now)”$/ })).toBeVisible();
    expect(await first.getByRole("listitem").count()).toBeGreaterThanOrEqual(2); // ≥1 reason and ≥1 Why
    await checkWidths(page, info);
    await shot(page, info, "p12f-home");

    // Open a problem card from a recommendation.
    const title = (await first.getByRole("heading", { level: 3 }).textContent())!.trim();
    await first.getByRole("heading", { level: 3 }).getByRole("link").click();
    await expect(page).toHaveURL(/\/problems\/[0-9a-f-]{36}$/, SERVER_STEP);
    const problemId = new URL(page.url()).pathname.split("/").pop()!;
    expect(await publishedProblemTitle(page.request, problemId)).toBe(title);
  });

  test("starts a proposal from a Discover problem with the problem already linked", async ({ page }) => {
    await page.goto("/dev/discover");
    const card = page.locator("article[data-problem]").first();
    const title = (await card.getByRole("heading", { level: 3 }).textContent())!.trim();
    const problemId = (await card.getAttribute("data-problem"))!;
    await card.getByRole("link", { name: "Start a proposal from this problem" }).click();
    await expect(page).toHaveURL(new RegExp(`/dev/ideas/new\\?problem=${problemId}$`), SERVER_STEP);
    await expect(page.getByRole("radio", { name: /Link a listed problem/ })).toBeChecked();
    const linked = page.getByRole("region", { name: /Linked problems/ });
    await expect(linked).toBeVisible(SERVER_STEP);
    await expect(linked.getByRole("listitem")).toHaveCount(1);
    await expect(linked.getByRole("button", { name: `Remove ${title}` })).toBeVisible();
  });

  test("an empty filtered list is one sentence and one action", async ({ page }, info) => {
    await page.goto("/dev/discover?county=KE-47&niche=basic-education");
    await expectEmptyState(page, "Nothing here for this niche and county yet.", "Clear filters");
    await checkWidths(page, info);
    await page.locator("[data-empty-state]").getByRole("link", { name: "Clear filters" }).click();
    await expect(page).toHaveURL(/\/dev\/discover$/, SERVER_STEP);
  });
});
