import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { signUpDeveloper, uniqueEmail } from "./support/accounts";
import { pathOf, waitForMessage, waitForSignInLink } from "./support/mailpit";
import { signUpOrgMember, verifyOrg } from "./support/org-scene";
import { checkScreen, settled } from "./support/screen";
import { signInMember, TELCO_A_MEMBERS, type Seat } from "./support/team-scene";
import { OWNER_DATABASE_URL } from "./support/tracker-scene";

// P28 track C (REQ-TEN-02; AT-C-1, AT-C-3 on the web) and D (REQ-ENG-17; AT-D-2 on the web).
//
// - Telco A's owner (the free plan, its two seats taken) is shown the seats paywall line when inviting, and sets a
//   niche's default reviewer and the escalation contact (each read back after a reload, then put back as the seed had
//   it). Strict axe at both projects, light and dark screenshots.
// - State Department D's owner (Growth in the seed) invites an address, sees it listed and revokes it.
// - An invitation link from a new, verified organisation (its own sender, so no run shares a sender's hourly limit):
//   signed out it sends no referrer; "Create an account" signs up in the invitee's mode; the confirmed account lands on
//   the organisation side's no-organisation state, opens the link again and accepts, landing on /org?org=<id>. A
//   developer account is told it cannot join (no Accept); someone else signed in is told only that the invitation is
//   for a different address; the used link is dead.
// - Telco A's Engagements list names the plan with CSV export; State Department D's offers "Export CSV", whose file
//   starts with the header row.
//
// Sends per run: one invitation each by Telco A's and State Department D's owners per project (four in all; the
// limits are 10 an hour per sender and 30 a day per organisation), and one by each run's new organisation, so three
// runs in an hour stay inside them. Needs the demo seed, Mailpit and E2E_DATABASE_OWNER_URL (the new organisation's
// verification). E2E_SHOTS_DIR saves the screens at 375 px (mobile project) and 1440 px, light and dark.

const STEP = { timeout: 20_000 };
const STATE_D_OWNER: Seat = { email: "owner@state-d.example", name: "Halima Yusuf" };
const STATE_D = "State Department D (fixture)";
const PASSWORD = "accent season in nairobi";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL verifies the new organisation (as a claim review would)").toBeTruthy();
});

async function shot(page: Page, info: TestInfo, name: string) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const width = info.project.name.startsWith("mobile") ? 375 : 1440;
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await settled(page); // the colours' own transitions finish first
    await page.screenshot({ path: join(dir, `${name}-${width}-${scheme}.png`), fullPage: true });
  }
  await page.emulateMedia({ colorScheme: null });
}

/** The page's own controls, after hydration (forms stay inert until then). */
async function hydrated(page: Page) {
  await expect(page.locator('[data-invite-form][data-hydrated="true"]')).toBeVisible(STEP);
}

async function invite(page: Page, email: string, role: string) {
  await page.getByLabel("Email address").fill(email);
  await page.getByRole("checkbox", { name: new RegExp(`^${role}`) }).check();
  await page.getByRole("button", { name: "Send invitation" }).click();
}

test("Telco A's owner meets the seats paywall, and sets a niche's default reviewer and the escalation contact", async ({
  browser,
}, info) => {
  test.setTimeout(180_000);
  const grace = await signInMember(browser, info, TELCO_A_MEMBERS.owner);
  const page = grace.page;
  try {
    // Home leads here (the portal's five sections are taken); so does the rail's footer from 1024 px.
    await page.goto("/org");
    await page.locator('[data-home="team"]').click();
    await expect(page).toHaveURL(/\/org\/team$/, STEP);
    await expect(page.getByRole("heading", { level: 1, name: "Team" })).toBeVisible();
    await expect(page.locator('[data-member] h3', { hasText: "Peter Kamau" })).toBeVisible();
    if (!info.project.name.startsWith("mobile")) {
      await expect(page.locator('[data-rail-footer="team"]')).toHaveAttribute("aria-current", "page");
    }
    await hydrated(page);
    await checkScreen(page, { strict: true });
    await shot(page, info, "team");

    // --- The free plan's seats are taken: the paywall line names the plan with more (402, limit_key seats) ----------
    await invite(page, uniqueEmail("seats"), "Viewer");
    const refusal = page.locator('[data-refusal="plan_limit"]');
    await expect(refusal).toHaveText(/^Every seat on your plan is taken\./, STEP);
    await expect(page.locator("[data-upgrade]")).toHaveAttribute("href", /^\/billing(\/upgrade\?plan=org_[a-z_]+&org=|\?org=)/);
    await checkScreen(page, { strict: true });

    // --- The default reviewer of Telco A's niche, read back after a reload, then as it was ----------------------------
    const select = page.locator("[data-niche-defaults] select").first();
    const before = await select.inputValue();
    await select.selectOption({ label: "Rita Njeri" });
    await page.getByRole("button", { name: "Save defaults" }).click();
    await expect(page.getByText(/^Defaults saved\./)).toBeVisible(STEP);
    await page.reload();
    await expect(page.locator("[data-niche-defaults] select").first().locator("option:checked")).toHaveText("Rita Njeri");
    await page.locator("[data-niche-defaults] select").first().selectOption(before);
    await page.getByRole("button", { name: "Save defaults" }).click();
    await expect(page.getByText(/^Defaults saved\./)).toBeVisible(STEP);

    // --- The escalation contact, likewise --------------------------------------------------------------------------
    const contact = page.getByLabel("Escalation contact");
    const was = await contact.inputValue();
    await contact.selectOption({ label: "Peter Kamau" });
    await page.getByRole("button", { name: "Save contact" }).click();
    await expect(page.getByText("Escalation contact saved.")).toBeVisible(STEP);
    await page.reload();
    await expect(page.getByLabel("Escalation contact").locator("option:checked")).toHaveText("Peter Kamau");
    await page.getByLabel("Escalation contact").selectOption(was);
    await page.getByRole("button", { name: "Save contact" }).click();
    await expect(page.getByText("Escalation contact saved.")).toBeVisible(STEP);
  } finally {
    await grace.close();
  }
});

test("State Department D's owner invites an address, sees it listed and revokes it", async ({ browser }, info) => {
  test.setTimeout(120_000);
  const halima = await signInMember(browser, info, STATE_D_OWNER, STATE_D);
  const page = halima.page;
  try {
    await page.goto("/org/team");
    await hydrated(page);
    const email = uniqueEmail("team");
    await invite(page, email, "Viewer");
    await expect(page.locator("[data-invited]")).toHaveText(`Invitation sent to ${email}. The link works for 7 days.`, STEP);
    const row = page.locator(`[data-invitation="${email}"]`);
    await expect(row).toBeVisible(STEP);
    await expect(row).toContainText("Invited by Halima Yusuf");
    await checkScreen(page, { strict: true });
    await row.getByRole("button", { name: `Revoke the invitation to ${email}` }).click();
    await expect(row).toHaveCount(0, STEP);
  } finally {
    await halima.close();
  }
});

test("an invitation link signs a new person up as the organisation's member, and nobody else", async ({ browser }, info) => {
  test.setTimeout(300_000);
  // The sender: a new organisation, verified as a claim review would leave it (E1), its owner signed in.
  const ownerContext = await browser.newContext({ ...info.project.use });
  const ownerPage = await ownerContext.newPage();
  const owner = await signUpOrgMember(ownerPage.request, "Inviter");
  verifyOrg(owner, "e1");
  const invitee = await browser.newContext({ ...info.project.use });
  const developer = await browser.newContext({ ...info.project.use });
  const grace = await signInMember(browser, info, TELCO_A_MEMBERS.owner);
  try {
    const address = uniqueEmail("invitee");
    await ownerPage.goto(`/org/team?org=${owner.orgId}`);
    await hydrated(ownerPage);
    await invite(ownerPage, address, "Reviewer");
    await expect(ownerPage.locator("[data-invited]")).toBeVisible(STEP);

    const mail = await waitForMessage(ownerPage.request, address, /an invitation to join a team/);
    const link = /https?:\/\/[^\s"<>]+(\/invitations\/[A-Za-z0-9_-]{43})/.exec(mail.text)?.[1];
    expect(link, "the email carries the invitation link").toBeTruthy();

    // Signed out: the organisation and the role, no referrer, and "Create an account" in the invitee's mode.
    const page = await invitee.newPage();
    const response = await page.goto(link!);
    expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Join ${owner.orgName}`);
    await expect(page.getByText(`${owner.orgName} invited you to join as reviewer.`)).toBeVisible();
    await checkScreen(page, { strict: true });
    await shot(page, info, "invitation-signed-out");
    await page.getByRole("link", { name: "Create an account" }).click();
    await expect(page.locator("[data-signup-invitation]")).toContainText(owner.orgName, STEP);
    await expect(page.getByRole("radio")).toHaveCount(0);
    await expect(page.getByLabel("Organisation name")).toHaveCount(0);
    await page.locator('form[data-hydrated="true"]').waitFor(STEP);
    await checkScreen(page, { strict: true });
    await page.getByLabel("Your name").fill("Wanjiku Mutua");
    await page.getByLabel("Email address").fill(address);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("checkbox", { name: /terms of service/ }).check();
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page).toHaveURL(/\/signup\/check-email$/, STEP);

    // The confirmed account is on the organisation side, with no organisation yet: the line says to open the link.
    await page.goto(pathOf(await waitForSignInLink(page.request, address)));
    await expect(page).toHaveURL(/\/org$/, STEP);
    await expect(page.locator('[data-home="no-org"]')).toContainText("open the invitation link in your email", STEP);
    await checkScreen(page, { strict: true });

    // A developer account: told it cannot join, no Accept.
    const devPage = await developer.newPage();
    await signUpDeveloper(devPage, "Kamau Njoroge");
    await devPage.goto(link!);
    await expect(devPage.locator('[data-invitation="developerAccount"]')).toBeVisible(STEP);
    await expect(devPage.getByRole("button", { name: "Accept and join" })).toHaveCount(0);

    // Someone else signed in: one sentence, nothing about the invited address.
    await grace.page.goto(link!);
    await grace.page.getByRole("button", { name: "Accept and join" }).click();
    const mismatch = grace.page.locator('[data-refusal="mismatch"]');
    await expect(mismatch).toHaveText(/This invitation is for a different email address\./, STEP);
    await expect(mismatch).not.toContainText(address);

    // The invitee opens the link again, accepts and lands in the organisation.
    await page.goto(link!);
    await checkScreen(page, { strict: true });
    await shot(page, info, "invitation-signed-in");
    await page.getByRole("button", { name: "Accept and join" }).click();
    await expect(page).toHaveURL(new RegExp(`/org\\?org=${owner.orgId}$`), STEP);
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Wanjiku", STEP);

    // Used, the link opens nothing: one calm sentence.
    await devPage.goto(link!);
    await expect(devPage.getByRole("heading", { level: 1 })).toHaveText("This invitation link no longer works");
    await checkScreen(devPage, { strict: true });
  } finally {
    await ownerContext.close();
    await invitee.close();
    await developer.close();
    await grace.close();
  }
});

test("the Engagements list names the plan with CSV export, and with it downloads the file", async ({ browser }, info) => {
  test.setTimeout(120_000);
  const grace = await signInMember(browser, info, TELCO_A_MEMBERS.owner);
  const halima = await signInMember(browser, info, STATE_D_OWNER, STATE_D);
  try {
    await grace.page.goto("/org/engagements");
    const line = grace.page.locator("[data-csv-off]");
    await expect(line).toHaveText("CSV export comes with the Growth plan. See plans");
    await expect(line.getByRole("link", { name: "See plans" })).toHaveAttribute("href", /^\/billing\?org=/);
    // Asked anyway, the export route comes back to the list and says why, without script.
    await grace.page.goto(`/org/engagements/export?org=${grace.orgId}`);
    await expect(grace.page).toHaveURL(/\/org\/engagements\?export=plan/, STEP);
    await expect(grace.page.locator('[data-export-refusal="plan"]')).toBeVisible();
    await checkScreen(grace.page, { strict: true });

    const page = halima.page;
    await page.goto("/org/engagements");
    const exportLink = page.getByRole("link", { name: "Export CSV" });
    await expect(exportLink).toHaveAttribute("href", `/org/engagements/export?org=${halima.orgId}`);
    await checkScreen(page, { strict: true });
    await shot(page, info, "engagements-csv");
    const download = await Promise.all([page.waitForEvent("download"), exportLink.click()]).then(([d]) => d);
    expect(download.suggestedFilename()).toMatch(/^engagements-\d{4}-\d{2}-\d{2}\.csv$/);
    const [header] = (await download.createReadStream().then(async (stream) => {
      const chunks: Buffer[] = [];
      for await (const chunk of stream) chunks.push(chunk as Buffer);
      return Buffer.concat(chunks).toString("utf-8");
    }))
      .replace(/^﻿/, "")
      .split(/\r?\n/);
    expect(header).toBe("reference,title,stage,stage_entered_on,due_on,other_party,assignee,procurement_route");
  } finally {
    await grace.close();
    await halima.close();
  }
});
