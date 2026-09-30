import { expect, test, type Page } from "@playwright/test";

import { checkScreen, expectEmptyState } from "./support/screen";
import {
  listedOrgId,
  makeViewer,
  OWNER_DATABASE_URL,
  pitchFromNewDeveloper,
  signUpOrgMember,
  verifyOrg,
  type OrgMember,
} from "./support/org-scene";

// REQ-PROP-03 (Inbox), REQ-REPO-01, REQ-PROV-03 and REQ-SEC-01 (the Evaluation NDA and the marked Tier-2 page) against
// the compose stack, in both projects (360 px and desktop). The API must run with FEATURE_TIER2_ENABLED=true.

const SERVER_STEP = { timeout: 20_000 };

test("signed-out visits to the organisation screens go to the login page", async ({ page }) => {
  for (const path of ["/org/inbox", "/org/inbox/01a0ee62-f783-733e-9321-9f34ec389ac2"]) {
    await page.goto(path);
    await expect(page, path).toHaveURL(/\/login$/);
  }
});

async function expectOrgNav(page: Page, current: "Home" | "Inbox") {
  const nav = page.getByRole("navigation", { name: "Organisation" });
  expect(await nav.getByRole("link").count()).toBeLessThanOrEqual(5); // AC-UX-1
  await expect(nav.getByRole("link", { name: current })).toHaveAttribute("aria-current", "page");
}

test.describe("an organisation member", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL verifies the test organisation and the developer").toBeTruthy();
  });
  test.setTimeout(120_000);

  let member: OrgMember;
  test.beforeEach(async ({ page }) => {
    member = await signUpOrgMember(page.request);
  });

  test("sees an empty Inbox that says what verification unlocks", async ({ page, browser, baseURL }) => {
    await page.goto("/org");
    await expectOrgNav(page, "Home");
    await page.getByRole("link", { name: "Open the Inbox" }).click();
    await expect(page).toHaveURL(/\/org\/inbox$/, SERVER_STEP);
    await expectOrgNav(page, "Inbox");
    await expectEmptyState(
      page,
      `Proposals reach ${member.orgName} once its verification is finished.`,
      "Back to home",
    );
    await checkScreen(page, { strict: true });

    // An organisation the member does not belong to is never swapped for their own one.
    await page.goto("/org/inbox?org=01a0ee62-0000-7000-8000-0000000000ff");
    await expectEmptyState(page, "Your account is not a member of this organisation.", "Open your Inbox");
    await page.goto("/org/inbox/01a0ee62-f783-733e-9321-9f34ec389ac2?org=01a0ee62-0000-7000-8000-0000000000ff");
    await expectEmptyState(page, "Your account is not a member of this organisation.", "Open your Inbox");
    await page.goto("/org/inbox");

    // E1: a pitched proposal is held; the organisation sees only how many wait (AC-PROP-1/a).
    verifyOrg(member, "e1");
    const held = await pitchFromNewDeveloper(browser, baseURL!, [member.orgId]);
    await page.reload();
    await expectEmptyState(
      page,
      `1 proposal waits until ${member.orgName} is verified with registration documents (E2).`,
      "Back to home",
    );
    await expect(page.getByText(held.title)).toHaveCount(0);
    await checkScreen(page, { strict: true });
  });

  test("opens a pitched proposal: teaser, Evaluation NDA, then the marked full proposal", async ({
    page,
    browser,
    baseURL,
  }) => {
    verifyOrg(member, "e2");
    const older = await pitchFromNewDeveloper(browser, baseURL!, [member.orgId]);
    const pitched = await pitchFromNewDeveloper(browser, baseURL!, [member.orgId]);

    await page.goto("/org");
    await expect(page.getByText(`Newest: ${pitched.title}, sent`)).toBeVisible();
    await expect(page.locator("[data-primary]")).toHaveText("Open the Inbox");
    await checkScreen(page, { strict: true });

    // Newest first, Tier 1 only, at most two chips per card.
    await page.goto("/org/inbox");
    const rows = page.locator("main article");
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText(pitched.title);
    await expect(rows.nth(1)).toContainText(older.title);
    await expect(rows.nth(0).locator("[data-chip]")).toHaveText("New");
    for (const row of await rows.all()) expect(await row.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
    await expect(page.getByText("Solar chillers with a shared booking queue")).toHaveCount(0); // no Tier 2 here
    await checkScreen(page, { strict: true });

    await page.getByRole("link", { name: pitched.title }).click();
    await expect(page).toHaveURL(new RegExp(`/org/inbox/${pitched.proposalId}$`), SERVER_STEP);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(pitched.title);
    await expect(page.getByRole("link", { name: `Check certificate ${pitched.certId}` })).toHaveAttribute(
      "href",
      `/verify/${pitched.certId}`,
    );

    // The NDA step: the text, its version and SHA-256, and the logging notice exactly as the API sends it.
    const nda = (await (
      await page.request.get(`/api/orgs/${member.orgId}/proposals/${pitched.proposalId}/nda`)
    ).json()) as { version: string; sha256: string; body: string; logging_notice: { text: string } };
    await expect(page.getByRole("region", { name: `Evaluation NDA, version ${nda.version}` })).toContainText(
      "LEGAL-PLACEHOLDER",
    );
    await expect(page.locator(`[data-fingerprint="${nda.sha256}"]`)).toBeVisible();
    await expect(page.locator("[data-logging-notice]")).toHaveText(nda.logging_notice.text);
    await expect(page.locator("[data-primary]")).toHaveText("Accept and view");
    await expect(page.locator("[data-tier2-frame]")).toHaveCount(0);
    await checkScreen(page, { strict: true });

    await page.getByRole("button", { name: "Accept and view" }).click();
    await expect(page).toHaveURL(new RegExp(`/org/inbox/${pitched.proposalId}\\?view=full$`), SERVER_STEP);
    const frame = page.frameLocator("[data-tier2-frame]");
    await expect(frame.getByRole("heading", { level: 1 })).toHaveText(pitched.title, SERVER_STEP);
    await expect(frame.getByText("Solar chillers with a shared booking queue and per-litre billing.")).toBeVisible();
    await expect(frame.locator(".mark")).toContainText(`${member.name} · ${member.orgName}`); // the viewer's mark
    await expect(page.locator("[data-tier2-frame]")).toHaveAttribute(
      "sandbox",
      "allow-popups allow-popups-to-escape-sandbox",
    );
    await expect(page.locator("[data-tier2-frame]")).toHaveAttribute(
      "title",
      `Full proposal: ${pitched.title}, marked for you`,
    );
    // The marked page runs no script, so axe cannot run inside it: the frame is left out (its title is checked above).
    await checkScreen(page, { strict: true, exclude: ["[data-tier2-frame]"] });

    // Accepted once: coming back does not open (and log) the full proposal until asked.
    await page.getByRole("link", { name: "Close full proposal" }).click();
    await expect(page).toHaveURL(new RegExp(`/org/inbox/${pitched.proposalId}$`), SERVER_STEP);
    await expect(page.getByText(`You accepted version ${nda.version} of the Evaluation NDA on`)).toBeVisible();
    await expect(page.locator("[data-primary]")).toHaveText("View full proposal");
    await expect(page.locator("[data-tier2-frame]")).toHaveCount(0);
    await checkScreen(page, { strict: true });
  });

  test("gets one plain sentence for each reason the full proposal stays closed", async ({ page, browser, baseURL }) => {
    verifyOrg(member, "e2");

    // Not shared with this organisation (pitched elsewhere): grant_required, and the way back to the Inbox.
    const elsewhere = await pitchFromNewDeveloper(browser, baseURL!, [listedOrgId()]);
    await page.goto(`/org/inbox/${elsewhere.proposalId}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(elsewhere.title);
    const refusal = page.locator("[data-refusal]");
    await expect(refusal).toHaveAttribute("data-refusal", "grant_required");
    await expect(refusal.locator("p")).toHaveText(
      `The developer has not shared the full proposal with ${member.orgName}.`,
    );
    await expect(refusal.getByRole("link")).toHaveText("Back to the Inbox");
    await expect(page.locator("[data-primary]")).toHaveCount(0);
    await checkScreen(page, { strict: true });

    // A role that may not open full proposals: its own sentence, no action of the member's own.
    const pitched = await pitchFromNewDeveloper(browser, baseURL!, [member.orgId]);
    makeViewer(member);
    await page.goto(`/org/inbox/${pitched.proposalId}`);
    await expect(refusal).toHaveAttribute("data-refusal", "role_not_permitted");
    await expect(refusal.locator("p")).toHaveText(
      `Opening full proposals needs the reviewer, signatory or admin role. An admin of ${member.orgName} can give it to you.`,
    );
    await expect(refusal.getByRole("link")).toHaveCount(0);
    await checkScreen(page, { strict: true });

    // No such proposal: one sentence and one action, nothing confirmed.
    await page.goto("/org/inbox/01a0ee62-0000-7000-8000-000000000000");
    await expectEmptyState(page, `This proposal is not in the Inbox of ${member.orgName}.`, "Back to the Inbox");
    await checkScreen(page, { strict: true });
  });
});
