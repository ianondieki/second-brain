import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { signUpDeveloper, uniqueEmail } from "./support/accounts";
import { waitForMessage } from "./support/mailpit";
import { letterTag, ownerSql } from "./support/research-scene";
import { checkScreen, settled } from "./support/screen";
import { send, signInMember, TELCO_A_MEMBERS } from "./support/team-scene";
import { OWNER_DATABASE_URL } from "./support/tracker-scene";

// P28 track C (REQ-TEN-02; AT-C-1, AT-C-3 on the web) and D (REQ-ENG-17; AT-D-2 on the web): Telco A's owner on
// Organisation › Team invites an address, sees it listed and revokes it, sets a niche's default reviewer and the
// escalation contact (each read back after a reload, then put back as the seed had it); the invitation link, read from
// Mailpit, joins a new account that signs in with the invited address, says "a different email address" to anyone
// else, sends no referrer, and is dead once used. The Engagements list names the plan with CSV export, and with that
// plan (for this test only) offers "Export CSV", whose file starts with the header row. Strict axe at both projects,
// light and dark. (P27's Team sheet on the tracker is e2e/team.spec.ts.)
//
// Needs the demo seed (Telco A's members), Mailpit, and E2E_DATABASE_OWNER_URL (the plan swap for the CSV test).
// E2E_SHOTS_DIR saves the screens at 375 px (mobile project) and 1440 px, light and dark.

const STEP = { timeout: 20_000 };

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL lets the CSV test give Telco A a plan with csv_export").toBeTruthy();
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

test("an owner invites and revokes, and sets a niche's default reviewer and the escalation contact", async ({
  browser,
}, info) => {
  test.setTimeout(180_000);
  const grace = await signInMember(browser, info, TELCO_A_MEMBERS.owner);
  const page = grace.page;
  try {
    await page.goto("/org/team");
    await expect(page.getByRole("heading", { level: 1, name: "Team" })).toBeVisible();
    await expect(page.locator('[data-member] h3', { hasText: "Peter Kamau" })).toBeVisible();
    await hydrated(page);
    await checkScreen(page, { strict: true });
    await shot(page, info, "team");

    // The account menu leads here on organisation screens (the tab bar's five sections are taken).
    await page.getByRole("button", { name: "Account" }).click();
    await expect(page.getByRole("link", { name: "Team" })).toHaveAttribute("href", /^\/org\/team/);
    await page.keyboard.press("Escape");

    // --- Invite, listed, revoke -----------------------------------------------------------------------------------
    const email = uniqueEmail("team");
    await page.getByLabel("Email address").fill(email);
    await page.getByRole("checkbox", { name: /^Viewer/ }).check();
    await page.getByRole("button", { name: "Send invitation" }).click();
    await expect(page.locator("[data-invited]")).toHaveText(`Invitation sent to ${email}. The link works for 7 days.`, STEP);
    const row = page.locator(`[data-invitation="${email}"]`);
    await expect(row).toBeVisible(STEP);
    await expect(row).toContainText("Invited by Grace Mwangi");
    await checkScreen(page, { strict: true });
    await row.getByRole("button", { name: `Revoke the invitation to ${email}` }).click();
    await expect(row).toHaveCount(0, STEP);

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

test("an invitation link joins the invited address, says nothing of it to anyone else, and dies once used", async ({
  browser,
}, info) => {
  test.setTimeout(240_000);
  const grace = await signInMember(browser, info, TELCO_A_MEMBERS.owner);
  const invitee = await browser.newContext({ ...info.project.use });
  const other = await browser.newContext({ ...info.project.use });
  try {
    const inviteePage = await invitee.newPage();
    // A name of its own per run, so the roster read below finds this run's member.
    const name = `Wanjiku ${letterTag()}`;
    const address = await signUpDeveloper(inviteePage, name);
    const otherPage = await other.newPage();
    await signUpDeveloper(otherPage, "Kamau Njoroge");

    // The owner invites the new account's address as a reviewer.
    await grace.page.goto("/org/team");
    await hydrated(grace.page);
    await grace.page.getByLabel("Email address").fill(address);
    await grace.page.getByRole("checkbox", { name: /^Reviewer/ }).check();
    await grace.page.getByRole("button", { name: "Send invitation" }).click();
    await expect(grace.page.locator("[data-invited]")).toBeVisible(STEP);

    const mail = await waitForMessage(grace.request, address, /invited you to join Telco A/);
    const link = /https?:\/\/[^\s"<>]+(\/invitations\/[A-Za-z0-9_-]{43})/.exec(mail.text)?.[1];
    expect(link, "the email carries the invitation link").toBeTruthy();

    // Signed out: the page names the organisation and the role, sends no referrer, and Sign in comes back here.
    const anon = await browser.newContext({ ...info.project.use });
    try {
      const anonPage = await anon.newPage();
      const response = await anonPage.goto(link!);
      expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
      await expect(anonPage.getByRole("heading", { level: 1 })).toHaveText("Join Telco A (fixture)");
      await expect(anonPage.getByText("Telco A (fixture) invited you to join as reviewer.")).toBeVisible();
      await expect(anonPage.getByRole("link", { name: "Sign in to accept" })).toHaveAttribute(
        "href",
        `/login?next=${encodeURIComponent(link!)}`,
      );
      await checkScreen(anonPage, { strict: true });
      await shot(anonPage, info, "invitation-signed-out");
    } finally {
      await anon.close();
    }

    // Someone else, signed in: one sentence, nothing about the invited address.
    await otherPage.goto(link!);
    await otherPage.getByRole("button", { name: "Accept and join" }).click();
    const refusal = otherPage.locator('[data-refusal="mismatch"]');
    await expect(refusal).toHaveText(/This invitation is for a different email address\./, STEP);
    await expect(refusal).not.toContainText(address);

    // The invited address accepts and becomes a reviewer of Telco A.
    await inviteePage.goto(link!);
    await checkScreen(inviteePage, { strict: true });
    await shot(inviteePage, info, "invitation-signed-in");
    await inviteePage.getByRole("button", { name: "Accept and join" }).click();
    await expect(inviteePage).not.toHaveURL(/\/invitations\//, STEP);
    const team = (await (await grace.request.get(`/api/orgs/${grace.orgId}/team`)).json()) as {
      members: Array<{ user_id: string; name: string; roles: string[] }>;
    };
    const joined = team.members.find((m) => m.name === name);
    expect(joined?.roles).toEqual(["reviewer"]);

    // Used, the link opens nothing: one calm sentence.
    await otherPage.goto(link!);
    await expect(otherPage.getByRole("heading", { level: 1 })).toHaveText("This invitation link no longer works");
    await checkScreen(otherPage, { strict: true });

    // Telco A as the seed had it: the new member leaves again (the owner's removal, AT-C-2's path).
    const removed = await send(grace.request, "delete", `/api/orgs/${grace.orgId}/members/${joined!.user_id}`);
    expect(removed.status(), await removed.text()).toBe(204);
  } finally {
    await grace.close();
    await invitee.close();
    await other.close();
  }
});

test("the Engagements list names the plan with CSV export, and with it offers the file", async ({ browser }, info) => {
  test.setTimeout(120_000);
  const grace = await signInMember(browser, info, TELCO_A_MEMBERS.owner);
  const page = grace.page;
  try {
    await page.goto("/org/engagements");
    const line = page.locator("[data-csv-off]");
    await expect(line).toHaveText("CSV export comes with the Growth plan. See plans");
    await expect(line.getByRole("link", { name: "See plans" })).toHaveAttribute("href", /^\/billing\?org=/);
    expect((await page.request.get(`/api/orgs/${grace.orgId}/engagements.csv`)).status()).toBeGreaterThanOrEqual(400);
    await checkScreen(page, { strict: true });

    // Telco A on Growth for this test only (the seed's free plan is put back in `finally`).
    const live = ownerSql(
      "SELECT id FROM subscriptions WHERE org_id = CAST(:'org' AS uuid) AND status = 'active';",
      { org: grace.orgId },
    );
    expect(live).toMatch(/^[0-9a-f-]{36}$/);
    ownerSql(
      "BEGIN;" +
        " UPDATE subscriptions SET status = 'cancelled' WHERE id = CAST(:'live' AS uuid);" +
        " INSERT INTO subscriptions (id, org_id, plan_id, status, current_period_start)" +
        " SELECT uuid7(), CAST(:'org' AS uuid), id, 'active', now() FROM plans WHERE code = 'org_growth';" +
        " COMMIT;",
      { org: grace.orgId, live },
    );
    try {
      await page.reload();
      const exportLink = page.getByRole("link", { name: "Export CSV" });
      await expect(exportLink).toHaveAttribute("href", `/api/orgs/${grace.orgId}/engagements.csv`);
      await checkScreen(page, { strict: true });
      await shot(page, info, "engagements-csv");
      const download = await Promise.all([page.waitForEvent("download"), exportLink.click()]).then(([d]) => d);
      expect(download.suggestedFilename()).toMatch(/^engagements-\d{4}-\d{2}-\d{2}\.csv$/);
      const body = (await page.request.get(`/api/orgs/${grace.orgId}/engagements.csv`)).body();
      const [header] = (await body).toString("utf-8").replace(/^﻿/, "").split(/\r?\n/);
      expect(header).toBe("reference,title,stage,stage_entered_on,due_on,other_party,assignee,procurement_route");
    } finally {
      ownerSql(
        "BEGIN;" +
          " DELETE FROM subscriptions s USING plans p WHERE s.plan_id = p.id AND p.code = 'org_growth'" +
          "   AND s.org_id = CAST(:'org' AS uuid);" +
          " UPDATE subscriptions SET status = 'active' WHERE id = CAST(:'live' AS uuid);" +
          " COMMIT;",
        { org: grace.orgId, live },
      );
    }
  } finally {
    await grace.close();
  }
});
