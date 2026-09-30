import { expect, test, type Page } from "@playwright/test";

import {
  caseOfProposal,
  type DemoItem,
  DEMO_ADMIN,
  DEMO_CLAIM_ORG,
  DEMO_MODERATOR,
  DEMO_PASSWORD,
  expectDemoQueues,
  negativeTeaser,
  P6_PROBLEM_TITLE,
  P6_TITLE,
  publishAs,
  publishNewVersion,
  reopenDemoItem,
  signInThroughScreens,
  teaserStatus,
  vulnerabilityTeaser,
} from "./support/moderation-scene";
import { newDeveloper, newStaffAdmin, OWNER_DATABASE_URL } from "./support/research-scene";
import { checkScreen, expectSeparateTargets } from "./support/screen";
import { ownerSql, PASSWORD } from "./support/tracker-scene";

// REQ-MOD-01, REQ-ADM-01 and the REQ-DIR-03 claims queue (M2 walkthrough step 6, P15): staff open the moderation
// queue, read a held proposal's public summary with its flagged field marked, and decide it; staff admins read the
// claims queue. Against the compose stack with the demo seed, in both projects (360 px and desktop). Every screen is
// checked with axe, the one-primary-action rule and no horizontal scroll.

const SERVER_STEP = { timeout: 20_000 };

async function hydrated(page: Page) {
  await page.locator('main [data-hydrated="true"]').first().waitFor(SERVER_STEP);
}

/** The console's navigation: the rail from 1024 px; on phones the tab bar only with two sections or more. */
async function openSection(page: Page, name: string, desktop: boolean) {
  const nav = page.getByRole("navigation", { name: "Staff console" });
  await nav.getByRole("link", { name }).click();
  await expect(nav.getByRole("link", { name })).toHaveAttribute("aria-current", "page", SERVER_STEP);
  expect(await nav.getByRole("link").count()).toBeLessThanOrEqual(5); // AC-UX-1
  if (!desktop) await expect(nav).toBeVisible(); // the bottom tab bar
}

test.describe("walkthrough step 6 (the demo seed)", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL reads the demo's queues").toBeTruthy();
    expectDemoQueues();
  });
  test.setTimeout(150_000);

  // Each demo login signs in from one project only (the API refuses a TOTP code used twice), and each project decides
  // its own demo item: the desktop run is the demo moderator approving P6, the 360 px run the demo admin approving the
  // new problem P6 describes. Before each run the item is put back as the seed left it (a retry, the other project's
  // timing and a local rerun all start from the same state).
  const itemOf = (project: string): DemoItem => (project === "desktop" ? "proposal" : "problem");
  test.beforeEach(({}, info) => {
    reopenDemoItem(itemOf(info.project.name));
    expectDemoQueues(itemOf(info.project.name));
  });

  test("staff approve the demo's held proposal from the moderation queue, and it publishes", async ({
    page,
    browser,
    baseURL,
  }, info) => {
    const desktop = info.project.name === "desktop";
    const developer = await browser.newContext({ baseURL });
    await newDeveloper(developer.request);
    const p6 = ownerSql("SELECT id FROM proposals WHERE title = :'title';", { title: P6_TITLE });

    if (desktop) {
      // The moderator signs in and lands on Moderation, their one section.
      await signInThroughScreens(page, DEMO_MODERATOR, DEMO_PASSWORD);
      await expect(page).toHaveURL(/\/admin\/moderation$/, SERVER_STEP);
      const nav = page.getByRole("navigation", { name: "Staff console" });
      await expect(nav.getByRole("link")).toHaveText(["Moderation"]);
      await expect(nav.getByRole("link", { name: "Moderation" })).toHaveAttribute("aria-current", "page");
    } else {
      // The admin lands on Research and opens Moderation from the tab bar.
      await signInThroughScreens(page, DEMO_ADMIN, DEMO_PASSWORD);
      await expect(page).toHaveURL(/\/admin\/research$/, SERVER_STEP);
      await openSection(page, "Moderation", desktop);
      await expect(page).toHaveURL(/\/admin\/moderation$/, SERVER_STEP);
    }
    await expect(page.getByRole("heading", { name: "Moderation", level: 1 })).toBeVisible();
    await expect(page.locator("[data-primary]")).toHaveText("Review the oldest case");

    // This run's item waits with the reason it was filed (P6 held and hidden; its problem public while checked). The
    // other project's item is not asserted: it may be decided at any moment. Every row has at most two tags.
    const title = desktop ? P6_TITLE : P6_PROBLEM_TITLE;
    const row = page.locator("[data-case]").filter({ hasText: title });
    if (desktop) {
      await expect(row).toContainText("Hidden until decided");
      await expect(row).toContainText("Speaks negatively of a named organisation");
    } else {
      await expect(row).toContainText("Public while checked");
      await expect(row).toContainText("New problem from a developer");
    }
    for (const row of await page.locator("[data-case]").all()) {
      expect(await row.locator("[data-chip]").count()).toBeLessThanOrEqual(2); // AC-UX-1
    }
    await expectSeparateTargets(page.locator("[data-case-link]"));
    await checkScreen(page);
    if (desktop) expect(await teaserStatus(developer.request, p6)).toBe(404); // held: nobody else can read it

    await row.getByRole("link", { name: title }).click();
    await expect(page).toHaveURL(/\/admin\/moderation\/cases\/[0-9a-f-]{36}$/, SERVER_STEP);
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    if (desktop) {
      // The flagged field is marked with a mark and a word, the others are not.
      const flagged = page.locator('[data-field="problem_statement"]');
      await expect(flagged).toHaveAttribute("data-flagged", "");
      await expect(flagged.locator("dt")).toContainText("Flagged");
      await expect(page.locator("[data-flagged]")).toHaveCount(1);
      await expect(page.locator('[data-field="summary"]')).toBeVisible();
    }
    await expect(page.locator("[data-primary]")).toHaveText("Approve");
    await checkScreen(page);

    await hydrated(page);
    await page.getByRole("button", { name: "Approve" }).click();
    const done = desktop ? "Approved. The proposal is public now." : "Approved. The problem is published.";
    const status = page.getByRole("status").filter({ hasText: done });
    await expect(status).toBeVisible(SERVER_STEP);
    await expect(status).toBeFocused();
    // The refreshed header says what is true now.
    await expect(page.locator('[data-header-tag="outcome"]')).toHaveText("Approved", SERVER_STEP);
    await expect(page.locator('[data-header-tag="visibility"]')).toHaveCount(0);
    await checkScreen(page);

    if (desktop) expect(await teaserStatus(developer.request, p6)).toBe(200); // published
    await developer.close();

    // The decided view lists it, with who decided it.
    await page.goto("/admin/moderation?view=decided");
    const decided = page.locator("[data-case]").filter({ hasText: title });
    await expect(decided).toContainText("Approved");
    await expect(decided).toContainText(`Approved by ${desktop ? DEMO_MODERATOR.name : DEMO_ADMIN.name} on`);
    await checkScreen(page);
  });

  test("a staff admin reads the claims queue with the demo claim, and cannot decide it", async ({
    page,
    browser,
    baseURL,
  }, info) => {
    const desktop = info.project.name === "desktop";
    const admin = await newStaffAdmin(browser, baseURL!);
    await signInThroughScreens(page, admin, PASSWORD);
    await expect(page).toHaveURL(/\/admin\/research$/, SERVER_STEP);
    await openSection(page, "Claims", desktop);
    await expect(page).toHaveURL(/\/admin\/claims$/, SERVER_STEP);
    await expect(page.getByRole("heading", { name: "Claims", level: 1 })).toBeVisible();

    // County C's E2 claim awaits review, its review time a mark and words; no personal or registration details.
    const row = page.locator("[data-claim]").filter({ hasText: DEMO_CLAIM_ORG });
    await expect(row).toContainText("Asks for E2 (registration documents)");
    const sla = row.locator("[data-sla]");
    await expect(sla).toHaveText(/^(Due in \d+ business days?|Due today|Overdue)$/);
    await expect(sla.locator("svg")).toHaveCount(1);
    await expect(row).not.toContainText("owner@county-c.example");
    await expect(page.locator("main button")).toHaveCount(0);
    await expect(page.locator("[data-primary]")).toHaveCount(0);
    await checkScreen(page);

    await row.getByRole("link", { name: DEMO_CLAIM_ORG }).click();
    await expect(page).toHaveURL(/\/admin\/claims\/[0-9a-f-]{36}$/, SERVER_STEP);
    await expect(page.getByRole("heading", { name: DEMO_CLAIM_ORG, level: 1 })).toBeVisible();
    await expect(page.locator("[data-read-only]")).toHaveText(
      "Deciding claims is not part of this prototype, so this page is for reading only.",
    );
    await expect(page.getByRole("heading", { name: "Evidence for E2" })).toBeVisible();
    await expect(page.getByText("owner@county-c.example")).toBeVisible();
    await expect(page.locator("main button")).toHaveCount(0);
    await checkScreen(page);

    // The other views, each its own address.
    await page.getByRole("link", { name: "Back to Claims" }).click();
    await page.getByRole("navigation", { name: "Claim views" }).getByRole("link", { name: "Closed" }).click();
    await expect(page).toHaveURL(/\/admin\/claims\?view=closed$/, SERVER_STEP);
    await expect(
      page.getByRole("navigation", { name: "Claim views" }).getByRole("link", { name: "Closed" }),
    ).toHaveAttribute("aria-current", "page");
    await checkScreen(page);
  });
});

test.describe("a moderator", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL makes the staff and the authors' D1 level").toBeTruthy();
  });
  test.setTimeout(180_000);

  test("confirms a stale sign-in, sees a new version reload the case, and approves it", async ({
    page,
    browser,
    baseURL,
  }, info) => {
    const author = await publishAs(browser, baseURL!, negativeTeaser());
    const caseId = caseOfProposal(author.teaser.title);
    const moderator = await newStaffAdmin(browser, baseURL!, { role: "moderator" });
    await signInThroughScreens(page, moderator, PASSWORD);
    await expect(page).toHaveURL(/\/admin\/moderation$/, SERVER_STEP);
    if (info.project.name !== "desktop") {
      await expect(page.getByRole("navigation", { name: "Staff console" })).toBeHidden(); // one section: no tab bar
    }

    // Claims are the staff admin's.
    await page.goto("/admin/claims");
    await expect(page.locator("[data-empty-state] p")).toHaveText("Claims are for staff admins.");
    await checkScreen(page);

    await page.goto(`/admin/moderation/cases/${caseId}`);
    await expect(page.getByRole("heading", { name: author.teaser.title, level: 1 })).toBeVisible();
    await expect(page.locator('[data-field="problem_statement"]')).toHaveAttribute("data-flagged", "");
    await hydrated(page);

    // Reject asks once more, with focus on the question; Cancel gives focus back to Reject.
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    const question = page.getByRole("group", {
      name: "Reject this proposal? It stays hidden. A new version from its author is checked again.",
    });
    await expect(question).toBeFocused();
    await checkScreen(page);
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeFocused();

    // Meanwhile the author publishes a new version, and the moderator's second factor grows old.
    const statement = "Customers cannot tell which bundle rule set each airtime charge on their statements.";
    await publishNewVersion(author, { ...author.teaser, problem_statement: statement });
    moderator.staleSecondFactor();

    // Approve asks for a fresh code first, then the decision runs and finds the new version: the case reloads.
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.locator('[data-refusal="step_up_required"]')).toBeVisible(SERVER_STEP);
    await expect(page.getByLabel("Code from your app")).toBeFocused();
    await checkScreen(page);
    await page.getByLabel("Code from your app").fill(await moderator.code());
    await page.getByRole("button", { name: "Confirm" }).click();
    const changed = page.getByRole("status").filter({ hasText: "The author published a new version" });
    await expect(changed).toBeVisible(SERVER_STEP);
    await expect(changed).toBeFocused();
    await expect(page.locator('[data-field="problem_statement"] dd')).toHaveText(statement, SERVER_STEP);
    await expect(page.getByText("case_changed")).toHaveCount(0); // never the API's words
    await checkScreen(page);

    // Approving the version now shown publishes it.
    expect(await teaserStatus(author.request, author.proposalId)).toBe(404);
    await page.getByRole("button", { name: "Approve" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Approved. The proposal is public now." })).toBeVisible(
      SERVER_STEP,
    );
    expect(await teaserStatus(author.request, author.proposalId)).toBe(200);
    await checkScreen(page);
    await author.context.close();
  });

  test("can only reject vulnerability content, which stays hidden", async ({ page, browser, baseURL }) => {
    const author = await publishAs(browser, baseURL!, vulnerabilityTeaser());
    const caseId = caseOfProposal(author.teaser.title);
    const moderator = await newStaffAdmin(browser, baseURL!, { role: "moderator" });
    await signInThroughScreens(page, moderator, PASSWORD);
    await expect(page).toHaveURL(/\/admin\/moderation$/, SERVER_STEP);

    await page.goto(`/admin/moderation/cases/${caseId}`);
    await expect(page.locator("[data-reasons]")).toContainText("Describes a security weakness");
    await expect(page.locator('[data-blocked="cannot_approve_vulnerability"]')).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
    await expect(page.locator("[data-primary]")).toHaveText("Reject");
    await checkScreen(page);

    await hydrated(page);
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await page.getByRole("button", { name: "Yes, reject" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Rejected. It is hidden now." })).toBeVisible(SERVER_STEP);
    expect(await teaserStatus(author.request, author.proposalId)).toBe(404);
    await checkScreen(page);
    await author.context.close();
  });
});
