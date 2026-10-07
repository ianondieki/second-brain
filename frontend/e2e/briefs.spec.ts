import { expect, test, type Page } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff, signInThroughScreens } from "./support/moderation-scene";
import { apiPost, runTag } from "./support/pitch-scene";
import { newDeveloper } from "./support/research-scene";
import { checkScreen } from "./support/screen";
import { demoTotpSecret } from "./support/totp";
import { OWNER_DATABASE_URL, ownerSql } from "./support/tracker-scene";
import { makeD1 } from "./support/verification";

// REQ-DIR-05 (P19-F §F-B; docs/spec/06 6.2 last bullet, 6.5, 6.12): an organisation's reviewer posts a Problem Brief
// from the Problems section, staff approve it in the moderation queue, a developer finds it under Discover › Briefs,
// starts a proposal from it, and pitches with the organisation already chosen; the reviewer then closes it and it
// leaves Discover. Against the compose stack with the demo seed (python -m bridge.seed --demo), in both projects:
// each project posts for its own E2 fixture (Telco A at 360 px, SACCO B on desktop), so the claimed plan's one open
// Brief is never shared between parallel runs. Every screen is checked with strict axe, the one-primary-action rule
// and no horizontal scroll.
//
// The developer is a new D1 account per run, standing in for Amina: Amina's Free plan allows 3 active ideas and the
// demo seed already uses them, so a repeatable run cannot publish as her. The recorded walkthrough tells her story.

const SERVER_STEP = { timeout: 20_000 };

interface Scene {
  org: string;
  reviewer: DemoStaff;
  staff: DemoStaff;
}

const demoLogin = (email: string, name: string) => new DemoStaff(email, name, demoTotpSecret(email));

const SCENES: Record<string, Scene> = {
  "mobile-360": {
    org: "Telco A (fixture)",
    reviewer: demoLogin("reviewer@telco-a.example", "Rita Njeri"),
    staff: demoLogin("admin@staff.example", "Staff Admin (demo)"),
  },
  desktop: {
    org: "SACCO B (fixture)",
    reviewer: demoLogin("reviewer@sacco-b.example", "Samuel Mutua"),
    staff: demoLogin("moderator@staff.example", "Staff Moderator (demo)"),
  },
};

/**
 * The fixture organisation's id, with its earlier runs' Briefs out of the way so its claimed plan has room again.
 * Revision 0006's guard closes only published Briefs (for the owner too), so those are closed, and a draft left by a
 * failed run (its problem still pending review) is freed by archiving its problem, which no longer counts as open.
 */
function prepareOrg(org: string): string {
  const id = ownerSql(
    "SELECT o.id FROM organizations o WHERE o.legal_name = :'org' AND o.verification = 'e2'" +
      " AND EXISTS (SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id AND u.demo_account" +
      " WHERE m.org_id = o.id AND m.status = 'active');",
    { org },
  );
  expect(id, `${org}, E2, from the demo seed (python -m bridge.seed --demo)`).toMatch(/^[0-9a-f-]{36}$/);
  // Test data only: this organisation's Briefs that an earlier run (or a failed one) left open.
  ownerSql(
    "UPDATE problem_briefs SET status = 'closed' WHERE org_id = CAST(:'id' AS uuid) AND status = 'published';" +
      " UPDATE problems SET status = 'archived' WHERE org_id = CAST(:'id' AS uuid) AND source = 'org_brief'" +
      " AND status = 'pending_review';",
    { id },
  );
  return id;
}

/** "YYYY-MM-DD" in Nairobi, `days` from today. */
function nairobiDay(days: number): string {
  const at = new Date(Date.now() + days * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi", year: "numeric", month: "2-digit", day: "2-digit" }).format(at);
}

async function hydrated(page: Page) {
  await page.locator('main [data-hydrated="true"]').first().waitFor(SERVER_STEP);
}

test.describe("a Problem Brief", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL reads the demo's fixtures and makes the developer D1").toBeTruthy();
  });
  test.setTimeout(240_000);

  test("is posted by a reviewer, approved by staff, answered by a developer with the organisation chosen, then closed", async ({
    page,
    browser,
    baseURL,
  }, info) => {
    const scene = SCENES[info.project.name] ?? SCENES.desktop;
    const orgId = prepareOrg(scene.org);
    const title = `Generators at tower sites run dry ${runTag()}`;

    // --- The reviewer: Home's Problem Briefs tile, the Problems section, the form ---------------------------------
    await signInThroughScreens(page, scene.reviewer, DEMO_PASSWORD);
    await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
    await expect(page.locator("[data-stat='briefs']")).toContainText("Problem Briefs");
    const nav = page.getByRole("navigation", { name: "Organisation" });
    expect(await nav.getByRole("link").count()).toBe(5); // Home, Inbox, Engagements, Problems, Events (AC-UX-1: at most 5)
    await nav.getByRole("link", { name: "Problems" }).click();
    await expect(page).toHaveURL(/\/org\/problems$/, SERVER_STEP);
    await expect(nav.getByRole("link", { name: "Problems" })).toHaveAttribute("aria-current", "page");
    await expect(page.locator("[data-primary]")).toHaveText("Post a Brief");
    await checkScreen(page, { strict: true });

    await page.locator("[data-primary]").click();
    await expect(page).toHaveURL(/\/org\/problems\/new$/, SERVER_STEP);
    await hydrated(page);
    await expect(page.locator("[data-invited-note]")).toBeVisible();
    await checkScreen(page, { strict: true });

    // Checked before anything is sent.
    await page.getByRole("button", { name: "Post the Brief" }).click();
    await expect(page.getByText("Write a title.")).toBeVisible();
    await expect(page.getByLabel("Title")).toBeFocused();

    await page.getByLabel("Title").fill(title);
    await page.getByLabel("Problem statement").fill(
      "Field teams learn that a generator tank is empty only after the site stops serving calls, often at night.",
    );
    await expect(page.locator("[data-meter]")).toContainText("Words: 19 of 120.");
    await page.getByLabel("Who is affected (optional)").fill("Subscribers served by off-grid tower sites");
    await page.getByLabel("Niche").selectOption({ label: "Networks & Telecommunications" });
    await page.getByLabel("County").selectOption("KE-30");
    const bands = page.getByRole("group", { name: "Budget band" }).getByRole("radio");
    await bands.first().check();
    const band = (await page.getByRole("group", { name: "Budget band" }).locator("label").first().innerText()).trim();
    await page.getByLabel(/Proposals wanted by/).fill(nairobiDay(30));
    await checkScreen(page, { strict: true });
    await page.getByRole("button", { name: "Post the Brief" }).click();

    // The list, the new Brief first, in review.
    await expect(page).toHaveURL(/\/org\/problems(\?posted=1)?$/, SERVER_STEP);
    await expect(page.getByRole("status")).toHaveText("Brief sent for review. Staff read every Brief before developers see it.");
    await expect(page.getByRole("status")).toBeFocused(); // the form that had focus is gone
    await expect(page).toHaveURL(/\/org\/problems$/); // posted leaves the address: a reload does not repeat the note
    const first = page.locator("[data-brief]").first();
    await expect(first).toContainText(title);
    await expect(first.locator("[data-chip]")).toHaveText("In review");
    const briefId = (await first.getAttribute("data-brief"))!;
    expect(briefId).toMatch(/^[0-9a-f-]{36}$/);
    await checkScreen(page, { strict: true });

    // --- Staff approve it in the moderation queue -------------------------------------------------------------------
    const staffContext = await browser.newContext({ baseURL });
    const staffPage = await staffContext.newPage();
    await signInThroughScreens(staffPage, scene.staff, DEMO_PASSWORD);
    await expect(staffPage).toHaveURL(/\/admin\//, SERVER_STEP);
    await staffPage.goto("/admin/moderation");
    const row = staffPage.locator("[data-case]").filter({ hasText: title });
    await expect(row).toContainText(`Brief by ${scene.org}`);
    await expect(row).toContainText("New Brief from an organisation");
    expect(await row.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
    await row.getByRole("link", { name: title }).click();
    await expect(staffPage).toHaveURL(/\/admin\/moderation\/cases\/[0-9a-f-]{36}$/, SERVER_STEP);
    await expect(staffPage.locator('[data-field="affected_group"]')).toContainText("Who is affected");
    await checkScreen(staffPage, { strict: true });
    await hydrated(staffPage);
    await staffPage.getByRole("button", { name: "Approve" }).click();
    await expect(staffPage.getByRole("status").filter({ hasText: "Approved. The Brief is published to developers." })).toBeVisible(SERVER_STEP);
    await staffContext.close();

    // --- A developer finds it under Discover › Briefs and starts a proposal from it ---------------------------------
    const devContext = await browser.newContext({ baseURL });
    const email = await newDeveloper(devContext.request);
    makeD1(email);
    const devPage = await devContext.newPage();
    await devPage.goto("/dev/discover?view=briefs");
    const lists = devPage.getByRole("navigation", { name: "Lists" });
    await expect(lists.getByRole("link", { name: "Briefs" })).toHaveAttribute("aria-current", "page");
    const card = devPage.locator(`[data-brief="${briefId}"]`);
    await expect(card).toContainText(title);
    await expect(card.locator("[data-label='org_brief']")).toHaveText(`Posted by ${scene.org}`);
    await expect(card.locator("[data-brief-terms]")).toContainText(band);
    await expect(card.locator("[data-brief-terms]")).toContainText("Proposals by ");
    expect(await card.locator("[data-chip], [data-label]").count()).toBeLessThanOrEqual(2); // AC-UX-1
    await checkScreen(devPage, { strict: true });
    await card.getByRole("link", { name: "Start a proposal from this Brief" }).click();
    await expect(devPage).toHaveURL(new RegExp(`/dev/ideas/new\\?problem=${briefId}$`), SERVER_STEP);
    await expect(devPage.getByText(title).first()).toBeVisible(SERVER_STEP); // the Brief is linked from the start

    // P23-3 (REQ-TRACK-03): its problem page says when proposals close, counted to the Brief's deadline_at (the end
    // of its deadline day in Nairobi) from the API's own clock (X-App-Now).
    const read = await devContext.request.get(`/api/problems/${briefId}`);
    const deadlineAt = ((await read.json()) as { brief: { deadline_at: string } }).brief.deadline_at;
    const stamp = read.headers()["x-app-now"];
    expect(stamp, "the API stamps its clock").toBeTruthy();
    const expected = Math.floor((Date.parse(deadlineAt) - Date.parse(stamp)) / 60_000);
    await devPage.goto(`/problems/${briefId}`);
    const closes = devPage.locator("[data-problem] dl [data-timer]");
    await expect(closes).toHaveText(/^Proposals close in (\d+ days? )?(\d+ h )?\d+ min$/, SERVER_STEP);
    const [, d, h, m] = /^P(\d+)DT(\d+)H(\d+)M$/.exec((await closes.locator("time").getAttribute("datetime")) ?? "") ?? [];
    expect(Math.abs((Number(d) * 24 + Number(h)) * 60 + Number(m) - expected)).toBeLessThanOrEqual(2);
    await checkScreen(devPage, { strict: true });

    // The idea, published through the API with the Brief linked (the editor's own steps are proposal-wizard.spec's).
    const problem = (await (await devContext.request.get(`/api/problems/${briefId}`)).json()) as { niche: { id: string } };
    const draft = await apiPost<{ id: string }>(
      devContext.request,
      "/api/me/proposals",
      {
        teaser: {
          title: `Fuel-level alerts ${runTag()}`,
          niche_id: problem.niche.id,
          county_code: "KE-30",
          maturity: "prototype",
          ask: "pilot",
          problem_statement: "Operators learn about empty generator tanks too late.",
          summary: "A sensor on each tank texts the field team before it runs dry.",
        },
        confidential: { approach: "Ultrasonic level sensors with an SMS gateway and a per-site threshold." },
        problem_ids: [briefId],
      },
      201,
    );
    const attestations = (await (await devContext.request.get("/api/proposals/attestations")).json()) as { version: string };
    await apiPost(devContext.request, `/api/me/proposals/${draft.id}/publish`, {
      attestations: { created_it: true, not_owned_by_employer_or_client: true, no_third_party_confidential: true },
      attestation_text_version: attestations.version,
    });

    // The pitch starts with the organisation chosen, and says why.
    await devPage.goto(`/dev/ideas/${draft.id}`);
    await devPage.getByRole("link", { name: "Pitch to companies" }).first().click(); // the page offers it twice (the primary and the section link)
    await expect(devPage).toHaveURL(new RegExp(`/dev/ideas/${draft.id}/pitch\\?org=${orgId}$`), SERVER_STEP);
    // The picker is a plain GET form (no data-hydrated): its checkboxes are enabled once it is live, as pitch.spec waits.
    const chosen = devPage.getByRole("checkbox", { name: scene.org }); // the accessible name starts with the organisation
    await expect(chosen).toBeEnabled(SERVER_STEP);
    await expect(chosen).toBeChecked();
    await expect(devPage.locator("[data-preselected]")).toHaveText(
      `${scene.org} is already chosen: your idea answers its Brief. Untick it if you would rather not pitch to them.`,
    );
    await checkScreen(devPage, { strict: true });

    // --- The reviewer closes it; it leaves Discover -------------------------------------------------------------------
    await page.goto(`/org/problems/${briefId}`);
    await expect(page.locator("[data-state-note='published']")).toBeVisible(SERVER_STEP);
    await checkScreen(page, { strict: true });
    // "Close this Brief" is a lone button, not a form with data-hydrated: press it until its dialog opens (a press
    // before hydration does nothing).
    const sheet = page.locator("dialog[open]");
    await expect(async () => {
      await page.getByRole("button", { name: "Close this Brief" }).click();
      await expect(sheet).toBeVisible({ timeout: 1_000 });
    }).toPass(SERVER_STEP);
    await expect(sheet).toContainText("It leaves Discover");
    await sheet.getByRole("button", { name: "Close the Brief" }).click();
    await expect(page.locator("[data-state-note='closed']")).toBeVisible(SERVER_STEP);
    await expect(page.locator("[data-state-focus]")).toBeFocused(); // Close's button is gone
    await expect(page.getByRole("button", { name: "Close this Brief" })).toHaveCount(0);

    await devPage.goto("/dev/discover?view=briefs");
    await expect(devPage.locator(`[data-brief="${briefId}"]`)).toHaveCount(0);
    // Its problem page stays readable (revision 0006), for the proposals that answer it.
    await devPage.goto(`/problems/${briefId}`);
    await expect(devPage.getByRole("heading", { level: 1 })).toHaveText(title, SERVER_STEP);
    await expect(devPage.locator("[data-timer]")).toHaveCount(0); // closed: ProblemStart's words, no countdown
    await devContext.close();
  });
});
