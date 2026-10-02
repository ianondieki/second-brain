import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Browser, type Page, type TestInfo } from "@playwright/test";

import { appToday, plusDays } from "./support/clock";
import { checkScreen } from "./support/screen";
import { OWNER_DATABASE_URL, pitchFromDeveloper, signUpOrg, type DevSide, type OrgSide } from "./support/tracker-scene";
import { loginReturningTo } from "./support/login";

// REQ-ENG-03 (AC-TRACK-3, AC-TRACK-4 prototype part), REQ-UX-01: the engagement tracker walked by both parties in
// their own browsers against the compose stack, SUBMITTED → CLOSED, plus a decline and a withdrawal; the same
// History for both parties; the whose-turn banner, the 5-group stepper, the action buttons from the API only, the
// inline step-up (ADR-002), and the page rules (axe, one primary action, no horizontal scroll) on each screen.
//
// Needs E2E_DATABASE_OWNER_URL (test-only state: D1/D2, E2, signatory, an old second factor) and an API with
// FEATURE_DEALS_ENABLED=true and FEATURE_TIER2_ENABLED=true. E2E_SHOTS_DIR saves screenshots at 375 px (mobile
// project) and 1440 px (desktop) for the task card.

const SERVER_STEP = { timeout: 20_000 };
const DONE = "Done. The tracker is up to date.";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
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

/** Presses one of the caller's buttons and waits until the step ran and the tracker refreshed without it. */
async function step(page: Page, name: string) {
  const actions = page.locator("[data-actions]");
  await actions.getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
  await expect(actions.getByRole("button", { name, exact: true })).toHaveCount(0, SERVER_STEP);
}

/** Opens a form step, lets `fill` complete it, submits it, and waits for the refreshed tracker. */
async function formStep(page: Page, name: string, fill: () => Promise<void>) {
  const actions = page.locator("[data-actions]");
  await actions.getByRole("button", { name, exact: true }).click();
  await expect(actions.locator("[data-command-form]")).toBeVisible();
  await fill();
  await checkScreen(page, { strict: true });
  await actions.locator("[data-command-form]").getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
  await expect(actions.locator("[data-command-form]")).toHaveCount(0);
}

async function banner(page: Page) {
  return page.locator("[data-whose-turn]");
}


interface Scene {
  dev: DevSide;
  org: OrgSide;
  devPage: Page;
  orgPage: Page;
  close: () => Promise<void>;
}

/** The developer on the test's page, the organisation in its own browser context of the same project. */
async function scene(page: Page, browser: Browser, info: TestInfo): Promise<Scene> {
  const orgContext = await browser.newContext({ ...info.project.use });
  const orgPage = await orgContext.newPage();
  const org = await signUpOrg(orgPage.request);
  const dev = await pitchFromDeveloper(page.request, org.orgId);
  return { dev, org, devPage: page, orgPage, close: () => orgContext.close() };
}

test("signed-out visits to the tracker screens go to the login page", async ({ page }) => {
  for (const path of ["/dev/engagements", "/org/engagements", "/dev/engagements/0199b000-0000-7000-8000-00000000e001"]) {
    await page.goto(path);
    await expect(page, path).toHaveURL(loginReturningTo(path)); // back there after signing in (P16-C1)
  }
});

test("both parties walk an engagement from Submitted to Closed", async ({ page, browser }, info) => {
  test.setTimeout(300_000);
  const { dev, org, devPage, orgPage, close } = await scene(page, browser, info);
  const devTracker = `/dev/engagements/${dev.engagementId}`;
  const orgTracker = `/org/engagements/${dev.engagementId}`;

  try {
    // Developer Home: the engagement waits on the organisation, so it is listed after "Needs you".
    await devPage.goto("/dev");
    const nav = devPage.getByRole("navigation", { name: "Developer" });
    expect(await nav.getByRole("link").count()).toBeLessThanOrEqual(5); // AC-UX-1
    await expect(nav.getByRole("link", { name: "Engagements" })).toHaveAttribute("href", "/dev/engagements");
    await expect(devPage.locator("[data-primary]")).toHaveText("New proposal");
    const homeRow = devPage.locator("[data-home='others'] article").filter({ hasText: dev.title });
    await expect(homeRow.locator("[data-chip]")).toHaveText(["Proposal submitted"]);
    await checkScreen(devPage);
    await shot(devPage, info, "dev-home");

    await nav.getByRole("link", { name: "Engagements" }).click();
    await expect(devPage).toHaveURL(/\/dev\/engagements$/, SERVER_STEP);
    await expect(nav.getByRole("link", { name: "Engagements" })).toHaveAttribute("aria-current", "page");
    // Grouped by proposal (docs/spec/07 item 1): the idea is the group's heading, each row an organisation (P16-C1).
    const group = devPage.locator("main section[data-proposal]").filter({
      has: devPage.getByRole("heading", { level: 2, name: dev.title }),
    });
    const row = group.locator("article").filter({ hasText: org.orgName });
    await expect(row.getByRole("heading", { level: 3 })).toHaveText(org.orgName);
    expect(await row.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
    await checkScreen(devPage);
    await shot(devPage, info, "dev-list");

    await row.getByRole("link", { name: org.orgName }).click();
    await expect(devPage).toHaveURL(new RegExp(`${devTracker}$`), SERVER_STEP);
    await expect(await banner(devPage)).toContainText(`Awaiting: ${org.orgName}`);
    await expect(await banner(devPage)).toContainText(`Next step for ${org.orgName}: Start the review`);
    const stepper = devPage.getByRole("list", { name: "Stages" });
    await expect(stepper.locator("[aria-current='step']")).toContainText("Review");
    await expect(stepper.locator("[aria-current='step']")).toContainText("Now: Proposal submitted");
    await expect(devPage.locator("[data-actions]").getByRole("button")).toHaveText(["Withdraw"]);
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "dev-tracker-submitted");

    // The organisation: the Inbox row's stage chip opens the tracker; the Engagements list puts it under "Needs us".
    await orgPage.goto("/org/inbox");
    const inboxChip = orgPage.locator(`[data-chip='stage'][data-engagement='${dev.engagementId}']`);
    await expect(inboxChip).toHaveAttribute("href", orgTracker, SERVER_STEP);
    const orgNav = orgPage.getByRole("navigation", { name: "Organisation" });
    expect(await orgNav.getByRole("link").count()).toBeLessThanOrEqual(5); // AC-UX-1
    await orgNav.getByRole("link", { name: "Engagements" }).click();
    await expect(orgPage).toHaveURL(/\/org\/engagements$/, SERVER_STEP);
    await expect(orgNav.getByRole("link", { name: "Engagements" })).toHaveAttribute("aria-current", "page");
    const orgRow = orgPage.locator("[data-group='needs'] article").filter({ hasText: dev.title });
    // Until INTEREST_CONFIRMED the organisation sees the pseudonymous handle, never the name (docs/spec/06 6.1; the
    // P10 backend's review fix, tasks/REQ-SCOUT-02.md MAJOR 1).
    await expect(orgRow).toContainText("From ");
    await expect(orgRow).not.toContainText("Achieng Otieno");
    // Nor any piece of it: the handle is random since the REQ-AUTH-01 fix (it was the name slugged,
    // "achieng-otieno-2b2356"): "dev-" and eight Crockford base32 characters.
    await expect(orgRow).not.toContainText(/achieng|otieno/i);
    await expect(orgRow).toContainText(/From dev-[0-9a-hjkmnp-tv-z]{8}/);
    await expect(orgRow.locator("[data-chip='turn']")).toHaveText("Our turn");
    await checkScreen(orgPage, { strict: true });
    await shot(orgPage, info, "org-list");
    await orgRow.getByRole("link", { name: dev.title }).click();
    await expect(orgPage).toHaveURL(new RegExp(`${orgTracker}$`), SERVER_STEP);
    await expect(await banner(orgPage)).toContainText("Awaiting: you");
    await expect(orgPage.locator("[data-primary]")).toHaveText("Start the review");
    await checkScreen(orgPage, { strict: true });
    await step(orgPage, "Start the review");
    await expect(orgPage.getByRole("list", { name: "Stages" })).toContainText("Now: Under review");

    await formStep(orgPage, "Approve to proceed (non-binding)", async () => {
      await expect(orgPage.getByLabel("Contact person")).toHaveValue(/.+/);
      await orgPage.getByLabel("How they will make contact").selectOption("email");
      // The platform's day, which the API checks the contact-by date against (the test clock may run ahead).
      await orgPage.getByLabel("Contact by").fill(await appToday(orgPage.request));
    });
    await expect(orgPage.getByRole("list", { name: "Stages" }).locator("[aria-current='step']")).toContainText(
      "Contact and NDA",
    );
    await orgPage.getByRole("button", { name: "Show the developer's contact details" }).click();
    await expect(orgPage.locator("[data-contact-revealed]")).toContainText(/dev-.*@example\.com/, SERVER_STEP);

    // An old second factor: the endorsement asks for a fresh code inline, then runs once more (ADR-002).
    org.person.staleSecondFactor();
    await orgPage.reload();
    await orgPage.locator("[data-actions]").getByRole("button", { name: "Mark first contact made" }).click();
    await expect(orgPage.getByLabel("Authenticator code")).toBeVisible(SERVER_STEP);
    await checkScreen(orgPage, { strict: true });
    await shot(orgPage, info, "org-step-up");
    await orgPage.getByLabel("Authenticator code").fill(await org.person.code());
    await orgPage.getByRole("button", { name: "Confirm and continue" }).click();
    await expect(orgPage.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
    await expect(orgPage.locator("[data-endorsement='org']")).toContainText("Endorsed");
    await expect(orgPage.locator("[data-endorsement='org']")).toContainText("Authenticator code");

    // Dual endorsement of first contact, then the mutual NDA signed by both.
    await devPage.reload();
    await expect(devPage.locator("[data-endorsement='org']")).toContainText("Rita Wanjiru");
    await expect(devPage.locator("[data-endorsement='org']")).toContainText(/EAT/);
    await expect(devPage.locator("[data-endorsement='developer']")).toContainText("Not endorsed yet");
    await checkScreen(devPage, { strict: true });
    await step(devPage, "Confirm first contact");
    await step(devPage, "Send the mutual NDA");
    await expect(await banner(devPage)).toContainText(`Awaiting: you and ${org.orgName}`);
    await step(devPage, "Sign the mutual NDA");
    await orgPage.reload();
    await step(orgPage, "Sign the mutual NDA");
    await expect(orgPage.locator("[data-signature='mutual_nda']")).toHaveCount(2);

    await orgPage.getByRole("navigation", { name: "Engagement sections" }).getByRole("link", { name: "Documents" }).click();
    await expect(orgPage.locator("[data-document='mutual_nda']")).toContainText("Matches the recorded fingerprint");
    await checkScreen(orgPage, { strict: true });
    await orgPage.getByRole("navigation", { name: "Engagement sections" }).getByRole("link", { name: "Tracker" }).click();

    // Terms by the organisation, marked final by the developer, signed by both.
    await formStep(orgPage, "Propose terms", async () => {
      await orgPage.getByLabel("Intellectual property").selectOption("non_exclusive_licence");
      await orgPage.getByLabel("Deliverable").fill("Pilot at two co-ops");
      await orgPage.getByLabel("Amount (KES)").fill("250000");
      await orgPage.getByLabel("Due date").fill(plusDays(await appToday(orgPage.request), 60));
    });
    await devPage.reload();
    await expect(devPage.locator("[data-agreement='draft']")).toContainText("Non-exclusive licence");
    await step(devPage, "Mark the terms final");
    await step(devPage, "Sign the agreement");
    await orgPage.reload();
    await step(orgPage, "Sign the agreement");

    // The milestone sub-tracker, then delivery.
    await devPage.reload();
    await expect(devPage.getByRole("list", { name: "Stages" }).locator("[aria-current='step']")).toContainText(
      "Implementation",
    );
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "dev-tracker-implementation");
    await step(devPage, "Start milestone 1");
    await step(devPage, "Submit milestone 1 for review");
    await orgPage.reload();
    await expect(orgPage.locator("[data-milestone-row='1']")).toContainText("Review due by");
    await step(orgPage, "Accept milestone 1");
    await devPage.reload();
    await step(devPage, "Submit the final delivery");

    // Acceptance: the organisation signs first, then the developer countersigns.
    await orgPage.reload();
    await step(orgPage, "Accept the delivery");
    await step(orgPage, "Sign the acceptance certificate");
    await devPage.reload();
    await step(devPage, "Sign the acceptance certificate");

    // Final payment: recorded by the organisation, confirmed by the developer.
    await orgPage.reload();
    await formStep(orgPage, "Record the final payment", async () => {
      await orgPage.getByLabel("Amount paid (KES)").fill("250,000");
      await orgPage.getByLabel("Reference (optional)").fill("QK12ABC345");
    });
    await expect(orgPage.locator("[data-payment='recorded']")).toContainText("KES 250,000");
    await devPage.reload();
    await formStep(devPage, "Confirm the payment", async () => {
      await devPage.getByLabel("Amount received (KES)").fill("250000");
    });

    await expect(await banner(devPage)).toContainText("This engagement is closed.");
    await expect(devPage.getByRole("list", { name: "Stages" }).locator("[data-state='completed']")).toHaveCount(5);
    await expect(devPage.locator("[data-actions]")).toHaveCount(0);
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "dev-tracker-closed");

    // AC-TRACK-3: the same History for both parties.
    await devPage.goto(`${devTracker}?tab=history`);
    await orgPage.goto(`${orgTracker}?tab=history`);
    const devEvents = await devPage.locator("[data-event]").allTextContents();
    const orgEvents = await orgPage.locator("[data-event]").allTextContents();
    expect(devEvents.length).toBeGreaterThan(15);
    expect(orgEvents).toEqual(devEvents);
    await expect(devPage.locator("[data-chain='verified']")).toBeVisible();
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "dev-history");
  } finally {
    await close();
  }
});

test("the organisation declines with a reason and the developer sees where it ended", async ({ page, browser }, info) => {
  test.setTimeout(120_000);
  const { dev, orgPage, devPage, close } = await scene(page, browser, info);
  try {
    await orgPage.goto(`/org/engagements/${dev.engagementId}`);
    await formStep(orgPage, "Decline", async () => {
      await orgPage.getByLabel("Reason").selectOption("BUDGET");
    });
    await devPage.goto(`/dev/engagements/${dev.engagementId}`);
    await expect(await banner(devPage)).toContainText("This engagement has ended.");
    await expect(await banner(devPage)).toContainText("Reason: Budget");
    await expect(devPage.getByRole("list", { name: "Stages" }).locator("[data-state='ended']")).toContainText("Review");
    await expect(devPage.locator("[data-actions]")).toHaveCount(0);
    await checkScreen(devPage, { strict: true });
  } finally {
    await close();
  }
});

test("the developer withdraws after confirming, and the organisation's buttons go", async ({ page, browser }, info) => {
  test.setTimeout(120_000);
  const { dev, orgPage, devPage, close } = await scene(page, browser, info);
  try {
    await devPage.goto(`/dev/engagements/${dev.engagementId}`);
    await devPage.locator("[data-actions]").getByRole("button", { name: "Withdraw" }).click();
    await expect(devPage.getByText(/Withdraw this proposal from/)).toBeVisible();
    await checkScreen(devPage, { strict: true });
    await step(devPage, "Withdraw");
    await expect(await banner(devPage)).toContainText("This engagement has ended.");
    await orgPage.goto(`/org/engagements/${dev.engagementId}`);
    await expect(orgPage.locator("[data-actions]")).toHaveCount(0);
    await expect(orgPage.getByRole("list", { name: "Stages" }).locator("[data-state='ended']")).toHaveCount(1);
  } finally {
    await close();
  }
});
