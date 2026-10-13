import { expect, test, type APIRequestContext } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff, signInThroughScreens } from "./support/moderation-scene";
import { checkScreen } from "./support/screen";
import { demoTotpSecret } from "./support/totp";
import { OWNER_DATABASE_URL, pitchFromDeveloper, post, signUpOrg } from "./support/tracker-scene";

// P27 track B (REQ-ENG-14), acceptance row 2: the organisation's Board. A demo organisation's seeded engagements in
// the right columns with their counts, the funnel's figures the API's, at most two chips a card (never the stage),
// the board server-rendered, scrolling sideways inside itself on a phone with no page overflow, and the list,
// calendar and board one TabNav. "Assigned to me" keeps only the person's cards.
//
// The stalled mark needs an engagement with no event for six business days: the demo seed has none, so that test
// makes one and moves the shared test clock (E2E_TEST_CLOCK=1, run alone, as tracker-branches.spec.ts's).

const STEP = { timeout: 20_000 };

const DEMO_ORG: Record<string, { email: string; name: string }> = {
  "mobile-360": { email: "reviewer@sacco-b.example", name: "Samuel Mutua" },
  desktop: { email: "reviewer@telco-a.example", name: "Rita Njeri" },
};

interface Pipeline {
  columns: Array<{
    group: string;
    count: number;
    items: Array<{ id: string; stalled: boolean; team: { assignee: { user_id: string } | null } | null }>;
  }>;
  funnel: { entered: Record<string, number> };
}

async function pipelineOf(request: APIRequestContext, orgId: string): Promise<Pipeline> {
  const response = await request.get(`/api/orgs/${orgId}/pipeline`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test("a demo organisation's board: columns and counts, the funnel, compact cards, one TabNav, Assigned to me", async ({
  page,
}, info) => {
  test.setTimeout(120_000);
  const who = DEMO_ORG[info.project.name] ?? DEMO_ORG.desktop;
  await signInThroughScreens(page, new DemoStaff(who.email, who.name, demoTotpSecret(who.email)), DEMO_PASSWORD);
  await expect(page).toHaveURL(/\/org$/, STEP);
  const me = (await (await page.request.get("/api/auth/me")).json()) as {
    user: { id: string };
    memberships: Array<{ org_id: string }>;
  };
  const orgId = me.memberships[0].org_id;

  await page.goto("/org/engagements");
  await page.getByRole("navigation", { name: "Engagement views" }).getByRole("link", { name: "Board" }).click();
  await expect(page).toHaveURL(/view=board/, STEP);
  const tabs = page.getByRole("navigation", { name: "Engagement views" });
  await expect(tabs.getByRole("link")).toHaveText(["List", "Calendar", "Board"]);
  await expect(tabs.getByRole("link", { name: "Board" })).toHaveAttribute("aria-current", "page");

  const api = await pipelineOf(page.request, orgId);
  const total = api.columns.reduce((sum, column) => sum + column.items.length, 0);
  if (total === 0) {
    await expect(page.locator("[data-board='empty']")).toBeVisible();
    await checkScreen(page, { strict: true });
    return;
  }
  // The columns: the five groups in order, each with the API's cards and count.
  await expect(page.locator("[data-column]")).toHaveCount(5);
  for (const column of api.columns) {
    const shown = page.locator(`[data-column="${column.group}"]`);
    await expect(shown.locator("[data-count]")).toHaveAttribute("data-count", String(column.count));
    await expect(shown.locator("[data-engagement]")).toHaveCount(column.items.length);
    for (const item of column.items) await expect(shown.locator(`[data-engagement="${item.id}"]`)).toBeAttached();
  }
  // The funnel's figures are the API's.
  for (const [group, count] of Object.entries(api.funnel.entered)) {
    await expect(page.locator(`[data-funnel-group="${group}"] [data-entered]`)).toHaveText(String(count));
  }
  // At most two chips a card, Our turn and the stalled mark only (the column says the stage).
  for (const card of await page.locator("[data-column] [data-engagement]").all()) {
    const chips = await card
      .locator("[data-chip]")
      .evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-chip")));
    expect(chips.length).toBeLessThanOrEqual(2);
    for (const chip of chips) expect(["turn", "stalled"]).toContain(chip);
  }
  // Server-rendered: the board is in the HTML the server sent, before any script.
  const html = await (await page.request.get("/org/engagements?view=board")).text();
  expect(html).toContain("data-board-row");
  // On a phone the columns scroll inside their own row; the page never scrolls sideways.
  const row = page.locator("[data-board-row]");
  if (info.project.name === "mobile-360") {
    expect(await row.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true);
  }
  await checkScreen(page, { strict: true });

  // Assigned to me: only the person's cards (or one sentence and the way back).
  const filter = page.getByRole("navigation", { name: "Whose engagements" });
  if (api.columns.some((column) => column.items.some((item) => item.team))) {
    await filter.getByRole("link", { name: "Assigned to me" }).click();
    await expect(page).toHaveURL(/assignee=me/, STEP);
    const mine = api.columns
      .flatMap((column) => column.items)
      .filter((item) => item.team?.assignee?.user_id === me.user.id);
    if (mine.length === 0) {
      await expect(page.locator("[data-board='mine-empty']")).toBeVisible();
    } else {
      await expect(page.locator("[data-column] [data-engagement]")).toHaveCount(mine.length);
    }
    await expect(filter.getByRole("link", { name: "Assigned to me" })).toHaveAttribute("aria-current", "page");
    await checkScreen(page, { strict: true });
  } else {
    await expect(filter).toHaveCount(0);
  }
});

test.describe("on the test clock", () => {
  test.skip(!process.env.E2E_TEST_CLOCK, "moves the shared clock: run alone with E2E_TEST_CLOCK=1");
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
  });

  test("an engagement with no event for six business days is marked stalled on the board", async ({
    page,
    browser,
  }, info) => {
    test.setTimeout(150_000);
    const orgContext = await browser.newContext({ ...info.project.use });
    try {
      const orgPage = await orgContext.newPage();
      const org = await signUpOrg(orgPage.request);
      const dev = await pitchFromDeveloper(page.request, org.orgId);
      const lock = (
        (await (await orgPage.request.get(`/api/engagements/${dev.engagementId}`)).json()) as {
          lock_version: number;
        }
      ).lock_version;
      await post(orgPage.request, `/api/engagements/${dev.engagementId}/start-review`, { lock_version: lock });
      await orgPage.goto("/org/engagements?view=board");
      await expect(orgPage.locator(`[data-engagement="${dev.engagementId}"]`)).toBeVisible();
      await expect(orgPage.locator(`[data-engagement="${dev.engagementId}"] [data-chip="stalled"]`)).toHaveCount(0);
      // Nine calendar days on: at least six Kenyan business days, whatever the holidays in between.
      await post(orgPage.request, "/api/test-clock/advance", { days: 9 });
      const api = await pipelineOf(orgPage.request, org.orgId);
      const item = api.columns.flatMap((column) => column.items).find((i) => i.id === dev.engagementId);
      expect(item?.stalled, "the API's stalled flag").toBe(true);
      await orgPage.reload();
      const card = orgPage.locator(`[data-engagement="${dev.engagementId}"]`);
      await expect(card).toHaveAttribute("data-stalled", "");
      await expect(card.locator("[data-chip='stalled']")).toHaveText(/^No movement for \d+\+ business days$/);
      await checkScreen(orgPage, { strict: true });
    } finally {
      await orgContext.close();
    }
  });
});
