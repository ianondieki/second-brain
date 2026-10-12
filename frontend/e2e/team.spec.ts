import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { checkScreen } from "./support/screen";
import { codeOf, SACCO_B_OWNER, send, signInMember, TELCO_A, TELCO_A_MEMBERS, type Member } from "./support/team-scene";
import { OWNER_DATABASE_URL, pitchFromDeveloper } from "./support/tracker-scene";

// P27 track C (REQ-ENG-15; D-68; acceptance row 3): Telco A's reviewer assigns a new engagement to the signatory, who
// is told (N30) and finds it under "Assigned to me"; the reviewer's recommendation, with its note, shows to another
// member in the sheet and in the header's tally; the developer's tracker, list and API carry no `team` and no
// recommendation text; a finance member cannot assign or recommend (403); a member of another organisation gets 404.
// The Team sheet passes axe with no violation of any impact, at 360 px and on the desktop.
//
// Needs the demo seed (Telco A's members), E2E_DATABASE_OWNER_URL (the new developer's verification levels) and an
// API with FEATURE_DEALS_ENABLED=true. E2E_SHOTS_DIR saves the sheet at 375 px (mobile project) and 1440 px.

const SERVER_STEP = { timeout: 20_000 };
const NOTE = "Ask how the chillers are powered at night.";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
});

async function shot(page: Page, info: TestInfo, name: string) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: join(dir, `${name}-${info.project.name.startsWith("mobile") ? 375 : 1440}.png`) });
}

const tracker = (member: Member, id: string) => member.page.goto(`/org/engagements/${id}`);

test("a reviewer assigns and recommends; the signatory is told and sees it; the developer sees none of it", async ({
  page,
  browser,
}, info) => {
  test.setTimeout(240_000);
  // The reviewer's scripts are read below (which chunk holds the Team sheet): no service worker in between.
  const reviewer = await signInMember(browser, info, TELCO_A_MEMBERS.reviewer, TELCO_A, { serviceWorkers: "block" });
  const signatory = await signInMember(browser, info, TELCO_A_MEMBERS.signatory);
  const finance = await signInMember(browser, info, TELCO_A_MEMBERS.finance);
  const other = await signInMember(browser, info, SACCO_B_OWNER, "SACCO B (fixture)");
  try {
    const dev = await pitchFromDeveloper(page.request, reviewer.orgId);
    const id = dev.engagementId;
    const base = `/api/orgs/${reviewer.orgId}/engagements/${id}`;

    // Every script the reviewer's page fetches, with its text: the Team sheet's chunk is the one that draws
    // [data-team-sheet] (no other chunk carries that attribute).
    const scripts: Array<{ url: string; text: Promise<string> }> = [];
    reviewer.page.on("response", (response) => {
      if (response.request().resourceType() === "script") {
        scripts.push({ url: response.url(), text: response.text().catch(() => "") });
      }
    });
    const teamChunk = async () => {
      for (const script of scripts) if ((await script.text).includes("data-team-sheet")) return script.url;
      return null;
    };

    // --- The reviewer's tracker: the team line under the banner, nobody assigned yet --------------------------------
    await tracker(reviewer, id);
    const line = reviewer.page.locator("[data-team-panel]");
    await expect(line).toContainText("Not assigned yet");
    await expect(line).toContainText("No recommendations yet");
    // The sheet's code is not on the page until the opener is reached (a lazy chunk): absent once the page has
    // settled, fetched when the pointer reaches "Assign".
    await reviewer.page.waitForLoadState("networkidle");
    expect(scripts.length).toBeGreaterThan(0);
    expect(await teamChunk()).toBeNull();
    await line.getByRole("button", { name: "Assign" }).hover();
    await expect.poll(teamChunk, SERVER_STEP).not.toBeNull();
    await line.getByRole("button", { name: "Assign" }).click();
    const sheet = reviewer.page.getByRole("dialog", { name: "Team on this engagement" });
    await expect(sheet.getByRole("radio", { name: /Peter Kamau/ })).toBeVisible(SERVER_STEP);
    await expect(sheet).toContainText("Only your organisation sees this. The developer never does.");
    await checkScreen(reviewer.page, { strict: true });
    await shot(reviewer.page, info, "team-sheet");

    // Assign to the signatory.
    await sheet.getByRole("radio", { name: /Peter Kamau/ }).check();
    await sheet.getByRole("button", { name: "Assign" }).click();
    await expect(sheet.getByRole("status")).toHaveText("Assigned to Peter Kamau.", SERVER_STEP);

    // Recommend: discuss, with a note.
    await sheet.locator("label[data-stance='discuss']").click();
    await expect(sheet.getByRole("radio", { name: "Discuss" })).toBeChecked();
    await sheet.getByLabel("Note (optional)").fill(NOTE);
    await sheet.getByRole("button", { name: "Save recommendation" }).click();
    await expect(sheet.getByText("Your recommendation is saved.")).toBeVisible(SERVER_STEP);
    await expect(sheet.locator("[data-team-recommendations]")).toContainText(NOTE);
    await checkScreen(reviewer.page, { strict: true });
    await sheet.getByRole("button", { name: "Close" }).click();
    await expect(sheet).toBeHidden();
    // Focus returns to the opener; the refreshed line says the change.
    await expect(line.getByRole("button", { name: "Change" })).toBeFocused(SERVER_STEP);
    await expect(line).toContainText("Assigned to Peter Kamau", SERVER_STEP);
    await expect(line.locator("[data-tally]")).toContainText("Recommended: pursue 0 · pass 0 · discuss 1");

    // --- The signatory: told (N30, in-app), and the engagement under "Assigned to me" -------------------------------
    const notices = (await (await signatory.request.get("/api/me/notifications")).json()) as {
      items: Array<{ kind: string; link: string | null }>;
    };
    expect(notices.items.some((n) => n.kind === "engagement.n30" && (n.link ?? "").includes(id))).toBe(true);
    await signatory.page.goto("/org/engagements?assignee=me");
    const filter = signatory.page.getByRole("navigation", { name: "Whose engagements" });
    await expect(filter.getByRole("link", { name: "Assigned to me" })).toHaveAttribute("aria-current", "page");
    const card = signatory.page.locator(`[data-engagement="${id}"]`);
    await expect(card).toBeVisible();
    await expect(card.locator("[data-assignee-line]")).toHaveText("Assigned to you");
    expect(await card.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
    await checkScreen(signatory.page, { strict: true });
    // The reviewer's own "Assigned to me" does not hold it.
    await reviewer.page.goto("/org/engagements?assignee=me");
    await expect(reviewer.page.locator(`[data-engagement="${id}"]`)).toHaveCount(0);
    // The Inbox's "Assigned to me" holds it for the signatory, with the line.
    await signatory.page.goto("/org/inbox?assignee=me");
    await expect(
      signatory.page.locator(`[data-proposal]`).filter({ hasText: dev.title }).locator("[data-assignee-line]"),
    ).toHaveText("Assigned to you");

    // --- Another member reads the recommendation and its note ----------------------------------------------------------
    await tracker(signatory, id);
    const signatoryLine = signatory.page.locator("[data-team-panel]");
    await expect(signatoryLine).toContainText("Assigned to you");
    await signatoryLine.getByRole("button", { name: "See recommendations" }).click();
    const theirs = signatory.page.getByRole("dialog", { name: "Team on this engagement" });
    await expect(theirs.locator("[data-recommendation='discuss']")).toContainText("Rita Njeri");
    await expect(theirs.locator("[data-recommendation='discuss']")).toContainText(NOTE);
    await theirs.getByRole("button", { name: "Close" }).click();

    // --- A finance member cannot assign or recommend; another organisation's member gets 404 --------------------------
    const assignByFinance = await send(finance.request, "put", `${base}/assignee`, { user_id: finance.userId });
    expect(assignByFinance.status()).toBe(403);
    expect(await codeOf(assignByFinance)).toBe("role_not_allowed");
    const recommendByFinance = await send(finance.request, "put", `${base}/recommendation`, {
      stance: "pass",
      note: null,
    });
    expect(recommendByFinance.status()).toBe(403);
    await tracker(finance, id);
    await expect(finance.page.locator("[data-team-panel]")).toContainText("Assigned to Peter Kamau");
    await expect(finance.page.locator("[data-team-panel]").getByRole("button", { name: "Change" })).toHaveCount(0);
    const fromOther = await other.request.get(`/api/orgs/${other.orgId}/engagements/${id}/team`);
    expect(fromOther.status()).toBe(404);

    // --- The developer: no team key, no recommendation text, anywhere ---------------------------------------------------
    const detail = await page.request.get(`/api/engagements/${id}`);
    const detailBody = (await detail.json()) as Record<string, unknown>;
    expect(detailBody.my_party).toBe("developer");
    expect("team" in detailBody).toBe(false);
    expect(JSON.stringify(detailBody)).not.toContain(NOTE);
    const list = (await (await page.request.get("/api/me/engagements")).json()) as {
      items: Array<Record<string, unknown>>;
    };
    const row = list.items.find((item) => item.id === id)!;
    expect("team" in row).toBe(false);
    await page.goto(`/dev/engagements/${id}`);
    await expect(page.locator("[data-turn-card]")).toBeVisible();
    await expect(page.locator("[data-team-panel]")).toHaveCount(0);
    expect(await page.content()).not.toContain(NOTE);
    expect(await page.content()).not.toContain("Recommended:");
    await page.goto("/dev/engagements");
    expect(await page.content()).not.toContain("Assigned to");
  } finally {
    await Promise.all([reviewer, signatory, finance, other].map((m) => m.close()));
  }
});

test("the assignee's refusals are said by code in the sheet", async ({ page, browser }, info) => {
  test.setTimeout(120_000);
  const owner = await signInMember(browser, info, TELCO_A_MEMBERS.owner);
  try {
    const dev = await pitchFromDeveloper(page.request, owner.orgId);
    await tracker(owner, dev.engagementId);
    const line = owner.page.locator("[data-team-panel]");
    await line.getByRole("button", { name: "Assign" }).click();
    const sheet = owner.page.getByRole("dialog", { name: "Team on this engagement" });
    // Nobody is assigned: "Nobody" again is no change (409 unchanged).
    await expect(sheet.getByRole("radio", { name: "Nobody" })).toBeChecked(SERVER_STEP);
    await sheet.getByRole("button", { name: "Assign" }).click();
    await expect(sheet.getByRole("alert")).toHaveText("It is already assigned that way.", SERVER_STEP);
    await checkScreen(owner.page, { strict: true });
  } finally {
    await owner.close();
  }
});
