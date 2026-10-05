import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { checkScreen, expectEmptyState } from "./support/screen";
import {
  makeReviewer,
  makeViewer,
  OWNER_DATABASE_URL,
  pitchFromNewDeveloper,
  signUpOrgMember,
  verifyOrg,
  type OrgMember,
  type Pitched,
} from "./support/org-scene";

// REQ-REPO-02 (P21 track B, D-57 (5)-(6)) against the compose stack, in both projects (360 px and desktop): a reviewer
// stars two proposals in the Inbox, finds them on the Shortlist with who added them, compares them on their Tier-1
// facts only and removes one; a viewer reads the shortlist but cannot change it (B1, B4, B6). Every screen keeps the
// page rules (axe with no violation at all, at most one primary action, no horizontal scroll).

const SERVER_STEP = { timeout: 20_000 };
const TIER2_TEXT = "Solar chillers with a shared booking queue"; // the scene's confidential approach

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

function entry(page: Page, pitched: Pitched) {
  return page.locator(`[data-shortlist-entry="${pitched.proposalId}"]`);
}

test.describe("the organisation shortlist", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL verifies the test organisation and sets the roles").toBeTruthy();
  });
  test.setTimeout(180_000);

  let member: OrgMember;
  test.beforeEach(async ({ page }) => {
    member = await signUpOrgMember(page.request);
    verifyOrg(member, "e2");
  });

  test("a reviewer stars two proposals, compares them on their public facts and removes one", async ({
    page,
    browser,
    baseURL,
  }) => {
    makeReviewer(member);
    const older = await pitchFromNewDeveloper(browser, baseURL!, [member.orgId]);
    const newer = await pitchFromNewDeveloper(browser, baseURL!, [member.orgId]);

    // Nothing shortlisted yet: the Shortlist tab is its empty state.
    await page.goto("/org/inbox/shortlist");
    const tabs = page.getByRole("navigation", { name: "Inbox sections" });
    await expect(tabs.getByRole("link", { name: "Shortlist" })).toHaveAttribute("aria-current", "page");
    await expectEmptyState(page, "Nothing is on the shortlist yet: star a proposal in the Inbox to keep it here.", "Open the Inbox");
    await checkScreen(page, { strict: true });

    // The Inbox: a star on each row, off; pressing it turns it on at once and it stays on (B6).
    await tabs.getByRole("link", { name: "Sent to you" }).click();
    await expect(page).toHaveURL(/\/org\/inbox$/, SERVER_STEP);
    for (const pitched of [newer, older]) {
      const row = page.locator(`article[data-proposal="${pitched.proposalId}"]`);
      const star = row.getByRole("button", { name: "Add to shortlist" });
      await expect(star).toHaveAttribute("data-shortlist", "off");
      await star.click();
      await expect(row.getByRole("button", { name: "Remove from shortlist" })).toHaveAttribute("data-shortlist", "on");
      expect(await row.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
    }
    await page.waitForLoadState("networkidle");
    await page.reload();
    await expect(page.getByRole("button", { name: "Remove from shortlist" })).toHaveCount(2);
    await checkScreen(page, { strict: true });

    // The proposal page knows it too.
    await page.goto(`/org/inbox/${newer.proposalId}`);
    await expect(page.getByRole("button", { name: "Remove from shortlist" })).toHaveAttribute("data-shortlist", "on");

    // The Shortlist: both, newest first, each with who added it and when.
    await page.goto("/org/inbox/shortlist");
    const entries = page.locator("[data-shortlist-entry]");
    await expect(entries).toHaveCount(2);
    await expect(entries.nth(0)).toContainText(older.title); // starred last, so newest on the shortlist
    for (const pitched of [newer, older]) {
      await expect(entry(page, pitched).locator("[data-added-by]")).toHaveText(new RegExp(`^Added by ${member.name} on \\d`));
    }
    await expect(page.locator("[data-primary]")).toHaveText("Compare");
    await checkScreen(page, { strict: true });

    // Compare needs 2: one ticked keeps the press and says so; two open the page at ?ids=a,b.
    await page.getByRole("checkbox", { name: `Compare ${newer.title}` }).check();
    await page.getByRole("button", { name: "Compare" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Choose at least 2" })).toBeVisible();
    await page.getByRole("checkbox", { name: `Compare ${older.title}` }).check();
    await expect(page.getByText("2 of 4 chosen")).toBeVisible();
    await page.getByRole("button", { name: "Compare" }).click();
    await expect(page).toHaveURL(
      new RegExp(`/org/inbox/shortlist/compare\\?ids=${older.proposalId},${newer.proposalId}$`),
      SERVER_STEP,
    );
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Compare proposals");
    await expect(page.locator("[data-tier1-note]")).toContainText("public teaser facts only");
    for (const pitched of [newer, older]) {
      await expect(page.getByRole("link", { name: pitched.title, exact: true })).toHaveAttribute("href", `/org/inbox/${pitched.proposalId}`);
    }
    await expect(page.getByText(TIER2_TEXT)).toHaveCount(0); // Tier 1 only (B4)
    await expect(page.getByText("Wants to run a pilot").filter({ visible: true }).first()).toBeVisible(); // the table at 1440, the cards at 360
    await checkScreen(page, { strict: true });

    // Too few ids: one sentence and the way back.
    await page.goto(`/org/inbox/shortlist/compare?ids=${newer.proposalId}`);
    await expectEmptyState(page, "Choose 2 to 4 proposals from the shortlist to compare.", "Back to the shortlist");
    await checkScreen(page, { strict: true });

    // Remove one: the list is read again; one left cannot be compared.
    await page.goto("/org/inbox/shortlist");
    await entry(page, older).getByRole("button", { name: `Remove ${older.title} from the shortlist` }).click();
    await expect(entries).toHaveCount(1, SERVER_STEP);
    await expect(page.getByText("Compare opens once the shortlist holds 2 proposals")).toBeVisible();
    await expect(page.locator("[data-primary]")).toHaveCount(0);
    await checkScreen(page, { strict: true });

    // A proposal of another organisation's Inbox cannot be added (B3, 404).
    const elsewhere = await page.request.put(`/api/orgs/${member.orgId}/shortlist/01a0ee62-0000-7000-8000-000000000000`, {
      headers: { "X-CSRF-Token": await csrf(page.request) },
    });
    expect(elsewhere.status()).toBe(404);
  });

  test("a viewer reads the shortlist but cannot change it", async ({ page, browser, baseURL }) => {
    const pitched = await pitchFromNewDeveloper(browser, baseURL!, [member.orgId]);
    // Starred while the member could (admin and signatory after verifyOrg), then left a viewer.
    const added = await page.request.put(`/api/orgs/${member.orgId}/shortlist/${pitched.proposalId}`, {
      headers: { "X-CSRF-Token": await csrf(page.request) },
    });
    expect(added.status(), await added.text()).toBe(200);
    makeViewer(member);

    await page.goto("/org/inbox");
    const row = page.locator(`article[data-proposal="${pitched.proposalId}"]`);
    await expect(row.locator("[data-shortlisted]")).toHaveText("Shortlisted");
    await expect(row.getByRole("button", { name: /shortlist/ })).toHaveCount(0);
    await checkScreen(page, { strict: true });

    await page.goto("/org/inbox/shortlist");
    await expect(entry(page, pitched)).toContainText(pitched.title);
    await expect(page.getByRole("button", { name: /^Remove/ })).toHaveCount(0);
    await checkScreen(page, { strict: true });

    // The API agrees (B1): a viewer's add and remove are refused.
    const headers = { "X-CSRF-Token": await csrf(page.request) };
    expect((await page.request.delete(`/api/orgs/${member.orgId}/shortlist/${pitched.proposalId}`, { headers })).status()).toBe(403);
    expect((await page.request.put(`/api/orgs/${member.orgId}/shortlist/${pitched.proposalId}`, { headers })).status()).toBe(403);
  });
});
