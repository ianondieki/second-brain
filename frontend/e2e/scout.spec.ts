import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { pathOf, waitForMessage } from "./support/mailpit";
import {
  childNiche,
  OWNER_DATABASE_URL,
  publishUntagged,
  setRoles,
  signUpScoutOrg,
  upgradeOrg,
} from "./support/scout-scene";
import { expectEmptyState, settled } from "./support/screen";
import { checkScreenStrict } from "./support/strict-screen";
import { tag } from "./support/tracker-scene";

// REQ-SCOUT-02 frontend (P10-F), the M2 walkthrough's step 1 (docs/platform/prototype-m2-plan.md §3), with
// REQ-ENG-04's stage 0: an organisation sets up its Scout Agent (a 402 for a schedule its plan lacks links to the
// upgrade; the simulated checkout upgrades it), a developer publishes a matching proposal nobody was pitched, the
// on_new scout finds it, the EM3 digest links to the match page, a signatory expresses interest with a fresh code,
// the developer accepts with a fresh code (EM2) and shares the full proposal with a fresh code, and the organisation
// opens it under the Evaluation NDA. The organisation sees only the developer's handle until the developer accepts.
// Each screen passes axe, keeps one primary action and has no horizontal scroll (360 px and 1440 px projects).
//
// Needs E2E_DATABASE_OWNER_URL, the worker (scouts.on_new, EM2, EM3) and an API with FEATURE_TIER2_ENABLED=true and
// the fake payment provider. E2E_SHOTS_DIR saves screenshots at 375 px and 1440 px.

const SERVER_STEP = { timeout: 20_000 };
const DONE = "Done. The tracker is up to date.";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only roles and verification levels").toBeTruthy();
});

async function shot(page: Page, info: TestInfo, name: string) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const size = page.viewportSize()!;
  const width = info.project.name.startsWith("mobile") ? 375 : 1440;
  await page.setViewportSize({ width, height: size.height });
  await page.screenshot({ path: join(dir, `${name}-${width}.jpg`), fullPage: true, type: "jpeg", quality: 70, scale: "css" });
  await page.setViewportSize(size);
}

test("signed-out visits to the scout screens go to the login page", async ({ page }) => {
  const id = "0199b000-0000-7000-8000-00000000e001";
  for (const path of ["/org/inbox?tab=matches", `/org/inbox/matches/${id}`, "/org/inbox/scouts/new", `/org/inbox/scouts/${id}`]) {
    await page.goto(path);
    await expect(page, path).toHaveURL(/\/login$/);
  }
});

test("a scout finds a proposal; interest, acceptance and the full proposal follow (M2 step 1)", async ({
  page,
  browser,
}, info) => {
  test.setTimeout(420_000);
  const orgContext = await browser.newContext({ ...info.project.use });
  const orgPage = await orgContext.newPage();
  try {
    const org = await signUpScoutOrg(orgPage.request);
    const niche = await childNiche(orgPage.request);
    const keyword = `maziwa${tag()}`;

    // 1. Inbox › Scout matches: no scout yet, so the tab is its empty state.
    await orgPage.goto("/org/inbox");
    await orgPage.getByRole("navigation", { name: "Inbox sections" }).getByRole("link", { name: "Scout matches" }).click();
    await expect(orgPage).toHaveURL(/\/org\/inbox\?tab=matches$/, SERVER_STEP);
    await expectEmptyState(
      orgPage,
      `Set up your Scout Agent and it brings proposals that fit ${org.orgName} here.`,
      "Set up Scout Agent",
    );
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-empty");
    // A member who does not configure scouts gets the member's empty state instead.
    setRoles(org, "{reviewer}");
    await orgPage.reload();
    await expectEmptyState(
      orgPage,
      `${org.orgName} has no Scout Agent yet; an owner or admin can set one up.`,
      "See proposals sent to you",
    );
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-empty-member");
    setRoles(org, "{owner,admin,signatory,reviewer}");
    await orgPage.reload();
    await orgPage.getByRole("link", { name: "Set up Scout Agent" }).click();
    await expect(orgPage).toHaveURL(/\/org\/inbox\/scouts\/new$/, SERVER_STEP);

    // 2. The form. An on_new scout is not on the free plan: the 402 links to the next plan's checkout.
    await expect(orgPage.locator("[data-plan-cap]")).toHaveText("1 Scout Agent is included in your plan.");
    await expect(orgPage.locator("form[data-scout-form][data-hydrated='true']")).toBeVisible();
    await orgPage.locator(`[id="scout-niches-${niche.id}"]`).check();
    await orgPage.getByLabel("Keywords to look for").fill(`${keyword}, chillers`);
    await orgPage.locator("#scout-recipients").getByLabel(org.person.name).check();
    await orgPage.getByLabel(/As soon as a proposal is published/).check();
    // The plan lacks that schedule: said at once, with the checkout of the plan that has it.
    const planNote = orgPage.locator("[data-plan-note]");
    await expect(planNote).toContainText("Your plan does not include this schedule.");
    const inlineUpgrade = planNote.getByRole("link", { name: "Upgrade your plan" });
    await expect(inlineUpgrade).toHaveAttribute(
      "href",
      new RegExp(`^/billing/upgrade\\?plan=[a-z_]+&org=${org.orgId}&next=%2Forg%2Finbox%2Fscouts%2Fnew%3Frestore%3D1$`),
    );
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-form");
    // The unsaved draft survives the checkout round trip (kept in this tab); the way back carries restore=1.
    await inlineUpgrade.click();
    await expect(orgPage).toHaveURL(/\/billing\/upgrade\?/, SERVER_STEP);
    await orgPage.goto("/org/inbox/scouts/new?restore=1");
    await expect(orgPage.getByText("Your unsaved settings are back.")).toBeVisible();
    await expect(orgPage.locator(`[id="scout-niches-${niche.id}"]`)).toBeChecked();
    await expect(orgPage.getByLabel("Keywords to look for")).toHaveValue(`${keyword}, chillers`);
    await expect(orgPage.getByLabel(/As soon as a proposal is published/)).toBeChecked();
    await expect(orgPage.locator("#scout-recipients").getByLabel(org.person.name)).toBeChecked();
    await orgPage.getByRole("button", { name: "Save scout" }).click();
    const refused = orgPage.locator("main").getByRole("alert");
    await expect(refused).toContainText("Your plan does not include this", SERVER_STEP);
    await expect(refused.getByRole("link", { name: "Upgrade your plan" })).toHaveAttribute(
      "href",
      new RegExp(`^/billing/upgrade\\?plan=[a-z_]+&org=${org.orgId}&next=%2Forg%2Finbox%2Fscouts%2Fnew%3Frestore%3D1$`),
    );
    await checkScreenStrict(orgPage);

    // 3. Upgraded (simulated M-Pesa), Preview says an on_new scout sends new proposals only; then Save.
    await upgradeOrg(orgPage.request, org.orgId, "org_growth");
    await orgPage.getByRole("button", { name: "Preview matches" }).click();
    await expect(orgPage.locator("[data-preview-note]")).toHaveText(
      "Shows what the last 30 days would have matched; this scout sends new proposals only.",
      SERVER_STEP,
    );
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-preview");
    await orgPage.getByRole("button", { name: "Save scout" }).click();
    await expect(orgPage).toHaveURL(/\/org\/inbox\?tab=matches$/, SERVER_STEP);
    await expect(orgPage.locator("[data-scout]")).toContainText("When a proposal is published");
    await expectEmptyState(
      orgPage,
      "No matches yet: proposals that fit your scout appear here as the scout finds them.",
      "Change the scout",
    );

    // Pause and resume from the scout's page; the status shows beside the control.
    await orgPage.locator("[data-scout]").getByRole("link", { name: /^Change the scout that looks for / }).click();
    await expect(orgPage).toHaveURL(/\/org\/inbox\/scouts\/[0-9a-f-]{36}$/, SERVER_STEP);
    await expect(orgPage.locator("form[data-scout-form][data-hydrated='true']")).toBeVisible();
    await orgPage.getByRole("button", { name: "Pause the scout" }).click();
    await expect(orgPage.getByText("This scout is paused: it finds nothing new until you resume it.")).toBeVisible(
      SERVER_STEP,
    );
    await expect(orgPage.locator("#scout-status")).toContainText("Paused");
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-paused");
    await orgPage.getByRole("button", { name: "Resume the scout" }).click();
    await expect(orgPage.locator("#scout-status")).toContainText("Active", SERVER_STEP);
    await orgPage.getByRole("link", { name: "Back to scout matches" }).click();
    await expect(orgPage).toHaveURL(/\/org\/inbox\?tab=matches$/, SERVER_STEP);

    // 4. A developer publishes a matching proposal, pitched to nobody: the publication runs the on_new scout.
    const dev = await publishUntagged(page.request, niche.id, keyword);
    // No piece of the developer's name, in any case, reaches the organisation before INTEREST_CONFIRMED.
    const NAME = new RegExp(dev.name.split(/\s+/).join("|"), "i");

    // 5. The match appears, by the developer's handle only.
    const row = orgPage.locator("[data-match]").filter({ hasText: dev.title });
    await expect(async () => {
      await orgPage.reload();
      await expect(row).toHaveCount(1, { timeout: 1_000 });
    }).toPass({ timeout: 90_000, intervals: [2_000] });
    await expect(row).toContainText("By ");
    await expect(row.locator("[data-why-source]")).toBeVisible();
    expect(await row.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
    await expect(orgPage.locator("main")).not.toContainText(NAME);
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-matches");

    // 6. EM3 reaches the reviewer seat; its item link opens the match page.
    const em3 = await waitForMessage(orgPage.request, org.person.email, /^Scout digest/, 60_000, dev.title);
    // The item of this proposal (numbered "1. …", "2. …"; another test's proposal may share the digest).
    const item = em3.text.split(/\n(?=\d+\. )/).find((block) => block.includes(dev.title)) ?? "";
    const link = /https?:\/\/[^\s"<>]+\/org\/inbox\/matches\/[0-9a-f-]{36}\?org=[0-9a-f-]{36}/.exec(item)?.[0];
    expect(link, "EM3 links to the match page").toBeTruthy();
    expect(em3.text).toContain(dev.title);
    expect(em3.text).not.toMatch(NAME);

    // A member who is not a signatory sees the button disabled, with the reason.
    setRoles(org, "{owner,admin,reviewer}");
    await orgPage.goto(pathOf(link!));
    await expect(orgPage.locator("[data-interest-reason='role_required']")).toContainText(
      `Only a signatory of ${org.orgName} can express interest.`,
    );
    await expect(orgPage.getByRole("button", { name: "Express interest" })).toBeDisabled();
    await checkScreenStrict(orgPage);
    setRoles(org, "{owner,admin,signatory,reviewer}");

    // 7. The signatory expresses interest; the second factor is 13 hours old, so a fresh code is asked for.
    await orgPage.reload();
    await expect(orgPage.getByRole("heading", { level: 1 })).toHaveText(dev.title);
    await expect(orgPage.locator("main")).not.toContainText(NAME);
    await expect(orgPage.locator("[data-primary]")).toHaveText("Express interest");
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-match");
    org.person.staleSecondFactor();
    await orgPage.getByRole("button", { name: "Express interest" }).click();
    await expect(orgPage.locator("form[data-interest-form][data-hydrated='true']")).toBeVisible();
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-interest-form");
    await orgPage.getByRole("button", { name: "Send interest" }).click();
    const orgCode = orgPage.getByLabel("Authenticator code");
    await expect(orgCode).toBeVisible(SERVER_STEP);
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-interest-stepup");
    await orgCode.fill(await org.person.code());
    await orgPage.getByRole("button", { name: "Confirm and continue" }).click();
    await expect(orgPage).toHaveURL(/\/org\/engagements\/[0-9a-f-]{36}$/, SERVER_STEP);
    const engagementId = new URL(orgPage.url()).pathname.split("/").pop()!;
    await expect(orgPage.locator("main")).toContainText("the developer's handle. You see their name once contact is agreed.");
    await expect(orgPage.locator("main")).not.toContainText(NAME);
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-org-stage0");

    // 8. N17 tells the developer; they accept with a fresh code (INTEREST_CONFIRMED) and EM2 is sent.
    await waitForMessage(page.request, dev.person.email, / is interested in /);
    dev.person.staleSecondFactor();
    await page.goto(`/dev/engagements/${engagementId}`);
    const actions = page.locator("[data-actions]");
    await expect(actions.getByRole("button", { name: "Accept the interest" })).toBeVisible();
    await checkScreenStrict(page);
    await shot(page, info, "scout-dev-stage0");
    await actions.getByRole("button", { name: "Accept the interest" }).click();
    await expect(actions.getByLabel("Authenticator code")).toBeVisible();
    await checkScreenStrict(page);
    await actions.getByLabel("Authenticator code").fill(await dev.person.code());
    await actions.getByRole("button", { name: "Confirm and continue" }).click();
    await expect(page.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
    const em2 = await waitForMessage(page.request, dev.person.email, /^Good news: .* approved/);
    expect(em2.subject).toContain(dev.title);
    expect(em2.text).toContain("will contact you shortly to agree on pursuing the project");
    expect(em2.text).toContain("Your full proposal has not been shared yet");

    // 9. The developer shares the full proposal, again with a fresh code.
    dev.person.staleSecondFactor();
    await page.reload();
    const share = page.locator("[data-tier2-share]");
    await share.getByRole("button", { name: "Share the full proposal" }).click();
    await expect(share.locator("[data-share-confirm]")).toContainText(
      "every view is logged and watermarked to the viewer",
    );
    await checkScreenStrict(page);
    await shot(page, info, "scout-dev-share");
    await share.getByRole("button", { name: "Share the full proposal" }).click();
    await expect(share.getByLabel("Authenticator code")).toBeVisible(SERVER_STEP);
    await checkScreenStrict(page);
    await shot(page, info, "scout-dev-share-stepup");
    await share.getByLabel("Authenticator code").fill(await dev.person.code());
    await share.getByRole("button", { name: "Confirm and continue" }).click();
    await expect(page.locator("[data-tier2-share='shared']")).toContainText(
      `You shared the full proposal with ${org.orgName}`,
      SERVER_STEP,
    );
    await expect(page.locator("#share-status")).toBeFocused();
    await checkScreenStrict(page);
    await shot(page, info, "scout-dev-shared");

    // 10. The organisation now sees the developer's name, and opens the full proposal under the NDA.
    await orgPage.goto(`/org/engagements/${engagementId}`);
    await settled(orgPage);
    await expect(orgPage.locator("main")).toContainText(`From ${dev.name}`);
    const shared = orgPage.locator("[data-tier2-share='shared']");
    await expect(shared).toContainText(`The developer shared the full proposal with ${org.orgName}`);
    await checkScreenStrict(orgPage);
    await shot(orgPage, info, "scout-org-shared");
    await shared.getByRole("link", { name: "Open the full proposal" }).click();
    await expect(orgPage).toHaveURL(new RegExp(`/org/inbox/${dev.proposalId}$`), SERVER_STEP);
    await orgPage.getByRole("button", { name: "Accept and view" }).click();
    const frame = orgPage.frameLocator("[data-tier2-frame]");
    await expect(frame.getByRole("heading", { level: 1 })).toHaveText(dev.title, SERVER_STEP);
    await expect(frame.getByText("Solar chillers with a shared booking queue and per-litre billing.")).toBeVisible();
    await checkScreenStrict(orgPage, { exclude: ["[data-tier2-frame]"] });
  } finally {
    await orgContext.close();
  }
});
