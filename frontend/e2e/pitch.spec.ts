import { expect, test, type Locator, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import {
  apiPost,
  draftIdea,
  e2OrgMember,
  listedOrg,
  OWNER_DATABASE_URL,
  publishIdea,
  runTag,
  viewFullDetails,
} from "./support/pitch-scene";
import { checkScreen } from "./support/screen";
import { makeD1 } from "./support/verification";
import { loginReturningTo } from "./support/login";

// REQ-PROP-03 (F2 picker, AC-PROP-1/a from the developer's side), REQ-DIR-04 (held tags, AC-DIR-1's sentence),
// REQ-PROV-03 and REQ-REPO-03 ("Who has seen this") against the compose stack, in both projects (360 px and desktop):
// publish, pitch an E2 and an E0 organisation, read what was sent and what is saved, withdraw the saved one, and see
// the organisation's view once its member accepted the NDA. The API must run with FEATURE_TIER2_ENABLED=true.

const SERVER_STEP = { timeout: 20_000 };
const E0_SENTENCE = (name: string) =>
  `${name} isn't on the platform yet. Your proposal is saved and they'll see it if they join and verify. We don't email them on your behalf.`;

test("signed-out visits to the picker go to the login page", async ({ page }) => {
  await page.goto("/dev/ideas/01a0ecd8-2e13-71dd-809a-2e817be8fcf3/pitch");
  await expect(page).toHaveURL(loginReturningTo("/dev/ideas/01a0ecd8-2e13-71dd-809a-2e817be8fcf3/pitch"));
});

/** Searches the picker by name and ticks the organisation's row. */
async function choose(page: Page, name: string) {
  await page.getByLabel("Search by name, niche or county").fill(name);
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await page.waitForURL((url) => url.searchParams.get("q") === name, SERVER_STEP);
  const box = page.getByRole("checkbox", { name, exact: true }).first();
  await expect(box).toBeEnabled(SERVER_STEP); // hydrated
  await box.check();
}

function pitchRow(page: Page, name: string): Locator {
  return page.getByRole("list", { name: "Companies you pitched this idea to" }).getByRole("listitem").filter({ hasText: name });
}

test.describe("a D1 developer with a published idea", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL raises the developer to D1 and verifies the E2 organisation").toBeTruthy();
  });
  test.setTimeout(150_000);

  let email = "";
  test.beforeEach(async ({ page }) => {
    email = await signUpDeveloper(page);
    makeD1(email);
  });

  test("pitches an E2 and an E0 company, withdraws the saved pitch, and sees who opened the details", async ({
    page,
    browser,
    baseURL,
  }) => {
    const idea = await publishIdea(page.request, `Maziwa baridi ${runTag()}`);
    const buyer = await e2OrgMember(browser, baseURL!);
    const listed = listedOrg(email);
    try {
      await page.goto(`/dev/ideas/${idea.id}`);
      await expect(page.locator("[data-primary]")).toHaveText("Pitch to companies");
      await expect(page.locator("section[aria-labelledby='pitches-heading'] [data-empty-state] p")).toHaveText(
        "You have not pitched this idea yet.",
      );
      const views = page.locator("section[aria-labelledby='views-heading']");
      await expect(views.locator("[data-empty-state] p")).toHaveText("Nobody has opened the full details yet.");
      await expect(views.locator("[data-empty-state]").getByRole("link")).toHaveCount(1);
      await expect(views).toContainText("every view is logged and watermarked to the viewer");
      await checkScreen(page);

      // The picker: the directory by niche with badges, the cap, one primary action.
      await page.locator("[data-primary]").click();
      await expect(page).toHaveURL(new RegExp(`/dev/ideas/${idea.id}/pitch$`), SERVER_STEP);
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Pitch to companies");
      await expect(page.locator("[data-cap]")).toHaveText(/^\d+ of \d+ pitches left for this idea on your plan\.$|no limit/);
      await expect(page.locator("[data-primary]")).toHaveText("Pitch");
      await expect(page.locator("[data-badge]").first()).toBeVisible();
      await checkScreen(page);

      // Choices survive a new search: the E2 buyer first, then the E0 company.
      await choose(page, buyer.orgName);
      const buyerRow = page.locator(`[data-org-row="${buyer.orgId}"]`).first();
      await expect(buyerRow.locator("[data-badge='e2']")).toBeVisible();
      await expect(buyerRow.locator("[data-outcome]")).toHaveText("Gets it now");
      await choose(page, listed.name);
      // The buyer, chosen in the first search, is listed first by name with its outcome, and can be unticked there.
      const chosen = page.locator("[data-chosen-group]");
      await expect(chosen.getByRole("heading", { name: "Chosen in other searches" })).toBeVisible();
      await expect(chosen.getByRole("checkbox", { name: buyer.orgName })).toBeChecked();
      await expect(chosen.locator("[data-outcome]")).toHaveText("Gets it now");
      const listedRow = page.locator(`[data-org-row="${listed.id}"]`).first();
      await expect(listedRow.locator("[data-badge='e0']")).toBeVisible();
      await expect(listedRow.locator("[data-outcome]")).toHaveText("Saved until they verify");
      await expect(page.getByText(/^2 of \d+ chosen$/)).toBeVisible();
      await checkScreen(page);

      await page.locator("[data-primary]").click();
      const result = page.locator("[data-pitch-result]");
      await expect(result.getByRole("heading", { name: "Pitched" })).toBeFocused(SERVER_STEP);
      await expect(result.getByRole("heading", { name: "Sent now (1)" })).toBeVisible();
      await expect(result).toContainText(buyer.orgName);
      await expect(result.getByRole("heading", { name: "Saved until they verify (1)" })).toBeVisible();
      await expect(result).toContainText(E0_SENTENCE(listed.name));
      await expect(result).toContainText("A record of this pitch goes to your email address.");
      await expect(page.locator("[data-primary]")).toHaveText("Back to your idea");
      await checkScreen(page);

      // The idea's pitches: sent and saved, one chip each; the saved one can be withdrawn.
      await page.locator("[data-primary]").click();
      await expect(page).toHaveURL(new RegExp(`/dev/ideas/${idea.id}$`), SERVER_STEP);
      await expect(pitchRow(page, buyer.orgName).locator("[data-status]")).toHaveText("Sent");
      await expect(pitchRow(page, buyer.orgName).getByRole("button")).toHaveCount(0);
      await expect(pitchRow(page, listed.name).locator("[data-status]")).toHaveText("Saved until they verify");
      await expect(pitchRow(page, listed.name)).toContainText(E0_SENTENCE(listed.name));
      for (const row of await page.getByRole("list", { name: "Companies you pitched this idea to" }).getByRole("listitem").all()) {
        expect(await row.locator("[data-status], [data-chip]").count()).toBeLessThanOrEqual(2); // AC-UX-1
      }
      await checkScreen(page);

      await pitchRow(page, listed.name).getByRole("button", { name: `Withdraw the pitch to ${listed.name}` }).click();
      const dialog = page.getByRole("dialog", { name: "Withdraw this pitch?" });
      await expect(dialog).toContainText(`${listed.name} has not seen it.`);
      await dialog.getByRole("button", { name: "Keep it" }).click();
      await expect(dialog).toBeHidden();
      await pitchRow(page, listed.name).getByRole("button", { name: `Withdraw the pitch to ${listed.name}` }).click();
      await dialog.getByRole("button", { name: "Withdraw", exact: true }).click();
      await expect(pitchRow(page, listed.name).locator("[data-status]")).toHaveText("Withdrawn", SERVER_STEP);
      await expect(pitchRow(page, listed.name).getByRole("button")).toHaveCount(0);
      await expect(page.locator("#pitches-heading")).toBeFocused();

      // Who has seen this: the buyer's member accepts the NDA and opens the marked details.
      await viewFullDetails(buyer, idea.id);
      await page.reload();
      const seen = views.getByRole("list", { name: "Views of the full details, newest first" }).getByRole("listitem");
      await expect(seen).toHaveCount(1);
      await expect(seen.first()).toContainText(`${buyer.name}, ${buyer.orgName}`);
      await expect(seen.first()).toContainText(/Nairobi time/);
      await expect(seen.first()).toContainText("Version 1");
      await checkScreen(page);

      // The buyer is now pitched: the picker says so and refuses the row.
      await page.goto(`/dev/ideas/${idea.id}/pitch?q=${encodeURIComponent(buyer.orgName)}`);
      const again = page.locator(`[data-org-row="${buyer.orgId}"]`).first();
      await expect(again.locator("[data-reason]")).toHaveText(`This idea is already pitched to ${buyer.orgName}.`);
      await expect(again.getByRole("checkbox")).toBeDisabled();
    } finally {
      await buyer.close();
    }
  });

  test("sees every choice a link carries by name before pitching it", async ({ page, browser, baseURL }) => {
    const idea = await publishIdea(page.request, `Maji ${runTag()}`);
    const buyer = await e2OrgMember(browser, baseURL!);
    const listed = listedOrg(email);
    try {
      // A shared or crafted link: a search for one company, and a choice of another the developer never saw.
      await page.goto(`/dev/ideas/${idea.id}/pitch?q=${encodeURIComponent(listed.name)}&sel=${buyer.orgId}`);
      const chosen = page.locator("[data-chosen-group]");
      await expect(chosen.getByRole("checkbox", { name: buyer.orgName })).toBeChecked();
      await expect(chosen.locator(`[data-org-row="${buyer.orgId}"] [data-badge='e2']`)).toBeVisible();
      // Unticked there, it is not sent.
      await chosen.getByRole("checkbox", { name: buyer.orgName }).uncheck();
      await page.getByRole("checkbox", { name: listed.name, exact: true }).first().check();
      await expect(page.getByText(/^1 of \d+ chosen$/)).toBeVisible();
      await checkScreen(page);
      await page.locator("[data-primary]").click();
      const result = page.locator("[data-pitch-result]");
      await expect(result.getByRole("heading", { name: "Saved until they verify (1)" })).toBeVisible(SERVER_STEP);
      await expect(result).not.toContainText(buyer.orgName);
      // A link to an organisation the directory does not list shows nothing and sends nothing.
      await page.goto(`/dev/ideas/${idea.id}/pitch?sel=0199a000-0000-7000-8000-00000000dead`);
      await expect(page.locator("[data-chosen-group]")).toHaveCount(0);
      await expect(page.getByText(/^0 of \d+ chosen$/)).toBeVisible();
    } finally {
      await buyer.close();
    }
  });

  test("hears why nothing was sent when a company was pitched meanwhile", async ({ page }) => {
    const idea = await publishIdea(page.request, `Maji safi ${runTag()}`);
    const listed = listedOrg(email);
    await page.goto(`/dev/ideas/${idea.id}/pitch`);
    await choose(page, listed.name);
    // Another tab pitches the same company first.
    await apiPost(page.request, `/api/me/proposals/${idea.id}/tags`, { org_ids: [listed.id] }, 201);
    await page.locator("[data-primary]").click();
    const alert = page.getByRole("alert").filter({ hasText: "Nothing was sent" });
    await expect(alert).toHaveText(
      "Nothing was sent: 1 of the companies you chose cannot be pitched to now, so they are unticked with the reason by each.",
      SERVER_STEP,
    );
    const row = page.locator(`[data-org-row="${listed.id}"]`).first();
    await expect(row.getByRole("checkbox")).not.toBeChecked();
    await expect(row.locator("[data-reason]")).toHaveText(`This idea is already pitched to ${listed.name}.`);
    await expect(page.getByText(/^0 of \d+ chosen$/)).toBeVisible();
    await checkScreen(page);

    // Focus is never hidden under the sticky bar and the tab bar (WCAG 2.4.11): after a refusal the bar stays the
    // summary and Pitch, both bars fit inside the focus scroll padding, and a focused field lands above them.
    const covered = () =>
      page.evaluate(() => {
        const bar = document.querySelector("[data-action-bar]")!.getBoundingClientRect().height;
        const tabs = document.querySelector("[data-tab-bar]")!;
        const tabHeight = getComputedStyle(tabs).position === "fixed" ? tabs.getBoundingClientRect().height : 0;
        const padding = parseFloat(getComputedStyle(document.documentElement).scrollPaddingBottom);
        return { covered: bar + tabHeight, padding };
      });
    const { covered: height, padding } = await covered();
    expect(height).toBeLessThanOrEqual(padding);
    // From the bottom of the page, Shift+Tab back up to the search's fields, as a keyboard user would.
    await page.locator("[data-intent='pitch']").focus();
    const niche = page.locator("#pitch-niche");
    for (let i = 0; i < 200 && !(await niche.evaluate((el) => el === document.activeElement)); i++) {
      await page.keyboard.press("Shift+Tab");
    }
    await expect(niche).toBeFocused();
    const box = await niche.boundingBox();
    const viewport = page.viewportSize()!;
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height - height);
  });

  test("cannot pitch a draft, and the picker says why", async ({ page }) => {
    const idea = await draftIdea(page.request, `Rasimu ${runTag()}`);
    await page.goto(`/dev/ideas/${idea.id}/pitch`);
    const empty = page.locator("[data-empty-state]");
    await expect(empty.locator("p")).toHaveText("Publish this idea before you pitch it.");
    await expect(empty.getByRole("link")).toHaveText("Back to your idea");
    await expect(page.locator("[data-primary]")).toHaveCount(0);
    await checkScreen(page);

    await page.goto(`/dev/ideas/${idea.id}`);
    await expect(page.getByRole("heading", { name: "Pitches" })).toHaveCount(0); // nothing registered yet
    await expect(page.getByRole("heading", { name: "Who has seen this" })).toHaveCount(0);
    await expect(page.locator("[data-primary]")).toHaveText("Continue editing");
  });
});
