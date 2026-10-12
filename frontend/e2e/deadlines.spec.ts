import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff, signInThroughScreens } from "./support/moderation-scene";
import { checkScreen } from "./support/screen";
import { demoTotpSecret } from "./support/totp";
import { OWNER_DATABASE_URL, pitchFromDeveloper, post, signUpOrg } from "./support/tracker-scene";

// P27 track A (REQ-ENG-13; D-61, D-70), acceptance row 1: every deadline a person carries on Engagements › Calendar,
// in their own calendar app one by one (.ics, Google Calendar) and as a private feed.
//
// The developer here has two engagements from one idea pitched to two new organisations: one SUBMITTED (the
// organisation's review is due) and one INFO_REQUESTED (the developer's answer is due), so the calendar shows a stage
// deadline and an answer-by date, the next one with the live clock. The demo seed has no developer who pitched to a
// Brief with a closing day; Brief deadlines are covered by the unit tests and by the organisation's calendar below,
// which compares every item the API lists for a demo organisation (stages, Briefs, events) with the screen.
//
// Needs E2E_DATABASE_OWNER_URL and an API with FEATURE_DEALS_ENABLED=true, like tracker.spec.ts.

const SECRET_QUESTION = "Which co-ops ran the pilot? (feed-must-not-carry-this)";
const STEP = { timeout: 20_000 };

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
});

interface Item {
  key: string;
  kind: string;
  title: string;
  due_at: string;
  due_on: string;
  engagement_id: string | null;
}

async function deadlines(
  request: APIRequestContext,
  path = "/api/me/deadlines",
): Promise<{ items: Item[]; now: string }> {
  const response = await request.get(path);
  expect(response.ok(), `${path}: ${response.status()}`).toBeTruthy();
  return response.json();
}

/** "20261016T205959Z", as an .ics DTSTART writes an instant in UTC. */
function icsStamp(iso: string): string {
  return new Date(iso)
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}/, "");
}

async function lockVersion(request: APIRequestContext, id: string): Promise<number> {
  return ((await (await request.get(`/api/engagements/${id}`)).json()) as { lock_version: number }).lock_version;
}

async function hydrated(page: Page) {
  await page.waitForFunction(() => document.readyState === "complete");
}

test("a developer's deadlines: the month, the list with the live clock, each in a calendar, and the private feed", async ({
  page,
  browser,
  playwright,
}, info) => {
  test.setTimeout(180_000);
  const contextA = await browser.newContext({ ...info.project.use });
  const contextB = await browser.newContext({ ...info.project.use });
  try {
    const orgA = await signUpOrg((await contextA.newPage()).request);
    const pageB = await contextB.newPage();
    const orgB = await signUpOrg(pageB.request);
    const dev = await pitchFromDeveloper(page.request, orgA.orgId);
    // The same idea pitched to a second organisation, which asks a question: the developer's answer is due.
    const mine = (await (await page.request.get("/api/me/engagements")).json()) as {
      items: Array<{ id: string; proposal_id: string; org_id: string }>;
    };
    const proposalId = mine.items.find((item) => item.id === dev.engagementId)!.proposal_id;
    await post(page.request, `/api/me/proposals/${proposalId}/tags`, { org_ids: [orgB.orgId] }, 201);
    const second = (await (await page.request.get("/api/me/engagements")).json()) as typeof mine;
    const asked = second.items.find((item) => item.proposal_id === proposalId && item.org_id === orgB.orgId)!.id;
    await post(pageB.request, `/api/engagements/${asked}/start-review`, {
      lock_version: await lockVersion(pageB.request, asked),
    });
    await post(pageB.request, `/api/engagements/${asked}/request-info`, {
      lock_version: await lockVersion(pageB.request, asked),
      question: SECRET_QUESTION,
    });

    const { items } = await deadlines(page.request);
    const stage = items.find((item) => item.engagement_id === dev.engagementId && item.kind === "stage");
    const answer = items.find((item) => item.engagement_id === asked && item.kind === "answer");
    expect(stage, "the review's deadline").toBeTruthy();
    expect(answer, "the answer-by date").toBeTruthy();

    // The month of each: the deadline on its Nairobi day, as a chip of its kind.
    for (const item of [stage!, answer!]) {
      await page.goto(`/dev/engagements?view=calendar&month=${item.due_on.slice(0, 7)}`);
      await expect(page.locator(`td[data-day="${item.due_on}"] [data-chip-deadline="${item.kind}"]`)).not.toHaveCount(
        0,
      );
      await expect(page.locator(`td[data-day="${item.due_on}"] a`).first()).toHaveAttribute(
        "aria-label",
        /\d+ deadlines?$/,
      );
    }

    // The list: both in the next 30 days, the first with the live clock and only it; each with its calendar links.
    await page.goto("/dev/engagements?view=calendar");
    const tabs = page.getByRole("navigation", { name: "Engagement views" });
    await expect(tabs.getByRole("link")).toHaveText(["List", "Calendar"]);
    await expect(tabs.getByRole("link", { name: "Calendar" })).toHaveAttribute("aria-current", "page");
    const next = page.locator("[data-deadlines-group='next']");
    for (const item of [stage!, answer!]) await expect(next.locator(`[data-deadline="${item.key}"]`)).toBeVisible();
    await expect(next.locator("[data-clock]")).toHaveCount(1);
    await expect(next.locator("[data-deadline]").first().locator("[data-clock] time")).toHaveAttribute(
      "datetime",
      /^P\d+DT\d+H\d+M$/,
    );
    await expect(next.locator(`[data-deadline="${answer!.key}"] [data-chip="turn"]`)).toHaveText("Your turn");
    await checkScreen(page, { strict: true });

    // Each .ics opens at the deadline's instant (UTC, the same moment as Nairobi's end of the due day).
    for (const item of [stage!, answer!]) {
      const [kind, id] = [item.kind, item.key.slice(item.key.indexOf(":") + 1)];
      const link = next.locator(`[data-deadline="${item.key}"] a[data-ics]`);
      await expect(link).toHaveAttribute("href", `/api/me/deadlines/${kind}/${id}/calendar.ics`);
      const ics = await page.request.get(`/api/me/deadlines/${kind}/${id}/calendar.ics`);
      expect(ics.ok()).toBeTruthy();
      expect(ics.headers()["content-type"]).toContain("text/calendar");
      expect(await ics.text()).toContain(`DTSTART:${icsStamp(item.due_at)}`);
      const google = new URL(
        (await next.locator(`[data-deadline="${item.key}"] a[data-google]`).getAttribute("href"))!,
      );
      expect(google.searchParams.get("dates")?.split("/")[0]).toBe(icsStamp(item.due_at));
    }

    // The organisation that reviews sees its own stage deadline on its calendar.
    const orgPage = contextA.pages()[0];
    await orgPage.goto("/org/engagements?view=calendar");
    await expect(orgPage.locator(`[data-deadline$="${dev.engagementId}"]`).first()).toBeVisible();
    await expect(orgPage.getByRole("navigation", { name: "Engagement views" }).getByRole("link")).toHaveText([
      "List",
      "Calendar",
      "Board",
    ]);

    // The private feed: made in Settings, shown once; it answers without a session, carries every deadline and no
    // note; a new link makes the old one 404, and so does removing it.
    await page.goto("/settings/notifications");
    await hydrated(page);
    const card = page.locator("[data-calendar-feed-card]");
    await expect(card.locator("[data-feed-private]")).toContainText("This link is private");
    await card.getByRole("button", { name: "Create a feed link" }).click();
    const field = card.getByRole("textbox", { name: "Feed link" });
    await expect(field).toHaveValue(/\/api\/calendar\/.+\.ics$/, STEP);
    const first = await field.inputValue();
    await checkScreen(page, { strict: true });
    const anonymous = await playwright.request.newContext();
    try {
      const feed = await anonymous.get(first);
      expect(feed.status()).toBe(200);
      expect(feed.headers()["set-cookie"]).toBeUndefined();
      const text = await feed.text();
      const listed = (await deadlines(page.request)).items;
      expect(text.match(/BEGIN:VEVENT/g)?.length).toBe(listed.length);
      for (const item of [stage!, answer!]) expect(text).toContain(`DTSTART:${icsStamp(item.due_at)}`);
      expect(text).not.toContain("feed-must-not-carry-this");

      await card.getByRole("button", { name: "Make a new link" }).click();
      await card.getByRole("button", { name: "Replace the link" }).click();
      await expect(field).not.toHaveValue(first, STEP);
      const second = await field.inputValue();
      expect((await anonymous.get(first)).status()).toBe(404);
      expect((await anonymous.get(second)).status()).toBe(200);

      await card.getByRole("button", { name: "Remove the feed" }).click();
      await card.getByRole("button", { name: "Remove the link" }).click();
      await expect(card.getByRole("status")).toHaveText("The feed is removed. Its link no longer works.", STEP);
      expect((await anonymous.get(second)).status()).toBe(404);
      await checkScreen(page, { strict: true });
    } finally {
      await anonymous.dispose();
    }
  } finally {
    await contextA.close();
    await contextB.close();
  }
});

const DEMO_ORG: Record<string, { email: string; name: string }> = {
  "mobile-360": { email: "reviewer@sacco-b.example", name: "Samuel Mutua" },
  desktop: { email: "reviewer@telco-a.example", name: "Rita Njeri" },
};

test("an organisation's calendar shows every deadline the API lists for it: stages, Briefs and events", async ({
  page,
}, info) => {
  test.setTimeout(120_000);
  const who = DEMO_ORG[info.project.name] ?? DEMO_ORG.desktop;
  await signInThroughScreens(page, new DemoStaff(who.email, who.name, demoTotpSecret(who.email)), DEMO_PASSWORD);
  await expect(page).toHaveURL(/\/org$/, STEP);
  const me = (await (await page.request.get("/api/auth/me")).json()) as { memberships: Array<{ org_id: string }> };
  const orgId = me.memberships[0].org_id;
  await page.goto("/org/engagements?view=calendar");
  const listed = await deadlines(page.request, `/api/orgs/${orgId}/deadlines`);
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date(listed.now));
  const end = new Date(Date.parse(`${today}T00:00:00Z`) + 30 * 86_400_000).toISOString().slice(0, 10);
  const shown = listed.items.filter((item) => item.due_on <= end);
  // The month's heading and its links either side, whether anything is due or not: an empty month is never a dead
  // end (the one sentence replaces the grid and the lists only).
  await expect(page.locator("h2#month-title")).toBeVisible();
  for (const side of ["previous", "next"]) {
    await expect(page.locator(`[data-month-link="${side}"]`)).toHaveAttribute(
      "href",
      /[?&]view=calendar&month=\d{4}-\d{2}/,
    );
  }
  if (shown.length === 0) {
    await expect(page.locator("[data-deadlines='empty']")).toBeVisible();
  } else {
    for (const item of shown) {
      await expect(page.locator(`[data-deadline="${item.key}"]`).first(), item.key).toBeAttached();
      const ics = page.locator(`[data-deadline="${item.key}"] a[data-ics]`).first();
      await expect(ics).toHaveAttribute("href", new RegExp(`^/api/orgs/${orgId}/deadlines/${item.kind}/`));
    }
  }
  await checkScreen(page, { strict: true });
});
