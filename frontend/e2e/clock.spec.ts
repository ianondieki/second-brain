import { expect, test, type Locator, type Page } from "@playwright/test";

import { checkScreen } from "./support/screen";
import { OWNER_DATABASE_URL, pitchFromDeveloper, post, signUpOrg } from "./support/tracker-scene";

// P27 (REQ-TRACK-03, REQ-UX-05): the deadline clocks are drawn on the server and kept by one page-level ticker (a data
// block the root layout's boot runs; components/ui/ClockTicker.tsx), not by a React island per clock. In a real
// browser, on the page's own clock (Playwright's, as tour.spec.ts installs it): a full load ticks on the first minute
// boundary, and so does a page reached by a navigation inside the app (where React never runs a <script> it renders,
// and a page's later part streams in after its clocks): the organisation's Engagements list, then the developer's
// Engagements list and Home's Needs-you hero.
//
// Needs E2E_DATABASE_OWNER_URL and an API with FEATURE_DEALS_ENABLED=true, like tracker.spec.ts.

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
});

/** The minutes a clock's <time> shows, from its ISO 8601 duration ("P6DT14H23M"). */
async function shownMinutes(clock: Locator): Promise<number> {
  const duration = (await clock.locator("time").getAttribute("datetime")) ?? "";
  const match = /^P(\d+)DT(\d+)H(\d+)M$/.exec(duration);
  expect(match, `a duration in "${duration}"`).not.toBeNull();
  return (Number(match![1]) * 24 + Number(match![2])) * 60 + Number(match![3]);
}

/**
 * The page's clock is held still, then run for a minute: every minute of what is left turns exactly once in it, so
 * each clock shows one minute less, its figures, its words and its <time>'s duration (the ticker's work: no React).
 */
async function expectTicks(page: Page, clocks: Locator[]) {
  for (const clock of clocks) await expect(clock.locator("time")).toHaveAttribute("datetime", /^P\d+DT\d+H\d+M$/);
  await page.clock.pauseAt((await page.evaluate(() => Date.now())) + 1_000);
  const before = await Promise.all(clocks.map(shownMinutes));
  const words = await Promise.all(clocks.map((clock) => clock.textContent()));
  await page.clock.runFor(60_000);
  for (const [index, clock] of clocks.entries()) {
    await expect.poll(() => shownMinutes(clock), { message: "a minute less" }).toBe(before[index] - 1);
    expect(await clock.textContent(), "the figures and the words moved with it").not.toBe(words[index]);
  }
  await page.clock.resume();
}

/** Follows a link of the portal's navigation inside the app (no new document: the page's own window stays). */
async function navigate(page: Page, nav: string, name: string, path: RegExp) {
  await page.evaluate(() => ((window as unknown as { __sameDocument?: boolean }).__sameDocument = true));
  await page.getByRole("navigation", { name: nav }).getByRole("link", { name, exact: true }).click();
  await expect(page).toHaveURL(path);
  expect(
    await page.evaluate(() => (window as unknown as { __sameDocument?: boolean }).__sameDocument),
    "a navigation inside the app",
  ).toBe(true);
}

test("the clocks tick on a full load and after navigations inside the app, on both sides", async ({
  page,
  browser,
}, info) => {
  test.setTimeout(150_000);
  const orgContext = await browser.newContext({ ...info.project.use });
  try {
    const orgPage = await orgContext.newPage();
    const org = await signUpOrg(orgPage.request);
    const dev = await pitchFromDeveloper(page.request, org.orgId);
    const id = dev.engagementId;
    const lockVersion = async () =>
      ((await (await orgPage.request.get(`/api/engagements/${id}`)).json()) as { lock_version: number }).lock_version;
    // The review started: the organisation's step, its clock on its cards.
    await post(orgPage.request, `/api/engagements/${id}/start-review`, { lock_version: await lockVersion() });

    // The organisation: a full load of its Engagements list ticks on the first minute boundary.
    await orgPage.clock.install();
    await orgPage.goto("/org/engagements");
    const orgCard = orgPage.locator(`main [data-engagement="${id}"] [data-clock]`);
    await expectTicks(orgPage, [orgCard]);
    // From the Inbox (no clock, no ticker) to the list inside the app: its data block runs, the card ticks.
    await orgPage.goto("/org/inbox");
    await navigate(orgPage, "Organisation", "Engagements", /\/org\/engagements(\?|$)/);
    await expectTicks(orgPage, [orgCard]);
    await checkScreen(orgPage, { strict: true });

    // A question for the developer: the answer-by date is now theirs, on their cards and Home's hero.
    await post(orgPage.request, `/api/engagements/${id}/request-info`, {
      lock_version: await lockVersion(),
      question: "Which co-ops ran the pilot?",
    });

    // The developer: from My ideas to Engagements, then to Home, all inside the app.
    await page.clock.install();
    await page.goto("/dev/ideas");
    await navigate(page, "Developer", "Engagements", /\/dev\/engagements$/);
    await expectTicks(page, [page.locator(`main [data-engagement="${id}"] [data-clock]`)]);
    await navigate(page, "Developer", "Home", /\/dev$/);
    // Home's hero is drawn before its streamed part, which carries the page's ticker.
    await expectTicks(page, [page.locator(`[data-home="needs-you"] [data-engagement="${id}"] [data-clock]`)]);
    await checkScreen(page, { strict: true });
  } finally {
    await orgContext.close();
  }
});
