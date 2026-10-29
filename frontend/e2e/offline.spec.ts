import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type BrowserContext, type Page, type TestInfo } from "@playwright/test";

import { pathOf, waitForSignInLink } from "./support/mailpit";
import { checkScreen } from "./support/screen";
import {
  OWNER_DATABASE_URL,
  ownerSql,
  PASSWORD,
  pitchFromDeveloper,
  post,
  signUp,
  signUpOrg,
  tag,
} from "./support/tracker-scene";

// P27 track F (REQ-UX-08; D-69; acceptance row 6): the trackers a person opened stay readable offline, read-only under
// an "as of" banner; nothing else is ever served from the worker's cache (an unvisited tracker, the messages page and
// the inbox give /offline); sign-out and another person's sign-in on the same browser delete the cache; the banner and
// /offline pass axe with no violation of any impact. The data-saver switch sets its cookie and the next page carries
// no photograph.
//
// Needs E2E_DATABASE_OWNER_URL (the tracker scene's test-only verification levels) and an API with
// FEATURE_DEALS_ENABLED=true. The worker runs on a production build only (`next build`, or the compose stack's web).
// E2E_SHOTS_DIR saves screenshots of the banner and /offline at 375 px (mobile project) and 1440 px (desktop).

const SERVER_STEP = { timeout: 20_000 };
const OFFLINE_TITLE = "You're offline";

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
  await page.screenshot({ path: join(dir, `${name}-${width}.png`), fullPage: true });
  await page.setViewportSize(size);
}

/** The names of this browser's offline caches of people (sw.js: trackers-<hash>). */
async function peopleCaches(page: Page): Promise<string[]> {
  return page.evaluate(async () => (await caches.keys()).filter((name) => name.startsWith("trackers-")));
}

/** The worker controls the page and has been told whose cache it is. */
async function workerReady(page: Page): Promise<string> {
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller)), SERVER_STEP).toBe(true);
  await expect.poll(() => peopleCaches(page), SERVER_STEP).toHaveLength(1);
  return (await peopleCaches(page))[0];
}

/** Whether the person's cache holds `path` (as the worker stores it: the full address). */
async function kept(page: Page, path: string): Promise<boolean> {
  return page.evaluate(
    async (url) => Boolean(await caches.match(url, { ignoreVary: true })),
    new URL(path, page.url()).href,
  );
}

async function expectOfflinePage(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1, name: OFFLINE_TITLE })).toBeVisible();
  await expect(page.locator("[data-offline-page]")).toHaveCount(1);
  // The address stays the one asked for: the worker answered it, nothing redirected.
  expect(new URL(page.url()).pathname).toBe(new URL(path, page.url()).pathname);
}

/**
 * The connection drops: `setOffline`, and every request aborted as a dropped connection would be, the worker's own
 * included (Playwright routes a Chromium service worker's requests through the context). `setOffline` alone was seen
 * to leave the worker's fetches online after a reload under emulation, which let a page load reach the server.
 */
async function goOffline(context: BrowserContext) {
  await context.setOffline(true);
  await context.route("**/*", (route) => route.abort("internetdisconnected"));
}

async function goOnline(context: BrowserContext) {
  await context.unroute("**/*");
  await context.setOffline(false);
}

/**
 * A Problem Brief of `orgId` that anyone may read (GET /api/public/problems/<id> answers 200): posted through the API
 * by the signed-in member, then published as staff approval does (app_moderate_problem: the problem published and
 * clear, the Brief published), written as the database owner, for this test organisation only.
 */
async function publicBrief(request: APIRequestContext, orgId: string): Promise<string> {
  const niches = (await (await request.get("/api/directory/niches")).json()) as Array<{ id: string }>;
  const brief = await post<{ id: string }>(
    request,
    `/api/orgs/${orgId}/briefs`,
    {
      title: `Generators at tower sites run dry ${tag()}`,
      statement: "Field teams learn that a generator tank is empty only after the site stops serving calls.",
      niche_id: niches[0].id,
      county_code: "KE-30",
    },
    201,
  );
  const id = brief.id; // a Brief's id is its problem's
  expect(id, "the Brief's problem").toMatch(/^[0-9a-f-]{36}$/);
  ownerSql(
    "UPDATE problems SET moderation_state = 'clear', status = 'published', published_at = now(), updated_at = now()" +
      " WHERE id = CAST(:'id' AS uuid) AND org_id = CAST(:'org' AS uuid) AND source = 'org_brief';" +
      " UPDATE problem_briefs SET status = 'published', updated_at = now()" +
      " WHERE problem_id = CAST(:'id' AS uuid) AND status = 'draft';",
    { id, org: orgId },
  );
  await expect.poll(async () => (await request.get(`/api/public/problems/${id}`)).status(), SERVER_STEP).toBe(200);
  return id;
}

async function signOutFromMenu(page: Page) {
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/, SERVER_STEP);
}

test("a tracker opened online reads offline, read-only under the banner; nothing else comes from the cache; sign-out deletes it", async ({
  page,
  browser,
  context,
}, info) => {
  const orgContext = await browser.newContext({ ...info.project.use });
  const org = await signUpOrg(orgContext.request);
  const dev = await pitchFromDeveloper(page.request, org.orgId);
  const tracker = `/dev/engagements/${dev.engagementId}`;
  const messages = `${tracker}/messages`;

  await page.goto("/dev");
  await workerReady(page);
  // Opened online: the tracker (a page load through the worker) and its messages page (never kept).
  await page.goto(messages);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goto(tracker);
  await expect(page.getByRole("heading", { level: 1, name: dev.title })).toBeVisible();
  await expect.poll(() => kept(page, tracker), SERVER_STEP).toBe(true);
  expect(await kept(page, messages)).toBe(false);
  // Online, the banner is there but hidden, and every control works.
  await expect(page.locator("[data-offline-banner]")).toBeHidden();

  await goOffline(context);
  await page.reload();
  // The worker's copy, under the banner, "as of" its time in Nairobi.
  await expect(page.getByRole("heading", { level: 1, name: dev.title })).toBeVisible();
  const banner = page.locator("[data-offline-banner]");
  await expect(banner).toBeVisible();
  await expect(banner).toHaveAttribute("role", "status");
  // The page is the worker's copy, said as such: its deadline clocks (drawn at the copy's instant) are hidden (P27).
  await expect(page.locator("html")).toHaveAttribute("data-offline", "cached");
  for (const clock of await page.locator("[data-clock]").all()) await expect(clock).toBeHidden();
  await expect(banner).toHaveText(
    new RegExp(
      `^You're offline\\. This is ${dev.title} as of \\d{1,2} \\w{3} \\d{4}, \\d{2}:\\d{2} EAT\\. Actions are available once you're back online\\.$`,
    ),
  );
  // Read-only: no control in the page can be used.
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          [...document.querySelectorAll<HTMLButtonElement>("#main :is(button, input, select, textarea)")].filter(
            (c) => !c.matches(":disabled"),
          ).length,
      ),
    )
    .toBe(0);
  expect(await page.locator("#main :is(button, input, select, textarea)").count()).toBeGreaterThan(0);
  const axe = await new AxeBuilder({ page })
    .include("[data-offline-banner]")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  expect(axe.violations, JSON.stringify(axe.violations.map((v) => v.id))).toEqual([]);
  await checkScreen(page);
  await shot(page, info, "offline-banner");

  // Never served from the cache: a tracker not opened, the messages page (opened online above), anything else.
  await expectOfflinePage(page, `/dev/engagements/${randomUUID()}`);
  await expectOfflinePage(page, messages);
  // One action, Try again, at this address; the developer's list was never opened, so no line promises it.
  await expect(page.getByRole("link", { name: "Try again" })).toHaveAttribute("href", new RegExp(`${messages}$`));
  await expect(page.locator("[data-offline-kept]")).toBeHidden();
  await checkScreen(page, { strict: true });
  await shot(page, info, "offline-page");
  await expectOfflinePage(page, "/dev/ideas");

  // Sign-out deletes the cache: offline, the tracker is /offline too.
  await goOnline(context);
  await page.goto(tracker);
  await signOutFromMenu(page);
  expect(await peopleCaches(page)).toEqual([]);
  await goOffline(context);
  await expectOfflinePage(page, tracker);
  await goOnline(context);
  await orgContext.close();
});

test("the organisation's inbox is never served from the cache; its tracker is", async ({ page, context }) => {
  const org = await signUpOrg(page.request);
  const query = `?org=${org.orgId}`;
  await page.goto(`/org${query}`);
  await workerReady(page);
  await page.goto(`/org/inbox${query}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goto(`/org/engagements${query}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect.poll(() => kept(page, `/org/engagements${query}`), SERVER_STEP).toBe(true);
  expect(await kept(page, `/org/inbox${query}`)).toBe(false);

  await goOffline(context);
  await expectOfflinePage(page, `/org/inbox${query}`);
  // The organisation's list is kept on this device: the line says so, and leads there.
  await expect(page.locator("[data-offline-kept]")).toBeVisible();
  await expect(page.getByRole("link", { name: "Engagements", exact: true }).last()).toHaveAttribute(
    "href",
    `/org/engagements${query}`,
  );
  await checkScreen(page, { strict: true });
  await page.goto(`/org/engagements${query}`);
  await expect(page.locator("[data-offline-banner]")).toBeVisible();
  await goOnline(context);
});

test("another person's sign-in on the same browser deletes the first person's cache", async ({ page, context }) => {
  const org = await signUpOrg(page.request); // a separate organisation for the pitch; then the developer signs in
  const dev = await pitchFromDeveloper(page.request, org.orgId);
  const tracker = `/dev/engagements/${dev.engagementId}`;
  await page.goto(tracker);
  const developers = await workerReady(page);
  await page.goto(tracker);
  await expect.poll(() => kept(page, tracker), SERVER_STEP).toBe(true);

  // The organisation member signs in in the same browser (their session replaces the developer's).
  const member = await signUpOrg(page.request);
  await page.goto(`/org?org=${member.orgId}`);
  await expect.poll(() => peopleCaches(page), SERVER_STEP).not.toContain(developers);
  expect(await peopleCaches(page)).toHaveLength(1);
  await goOffline(context);
  await expectOfflinePage(page, tracker);
  await goOnline(context);
});

test("the data-saver switch sets its cookie, and the next pages carry no photograph", async ({ page, context }) => {
  const org = await signUpOrg(page.request);
  await pitchFromDeveloper(page.request, org.orgId);
  await page.goto("/dev");
  await expect(page.locator("[data-greeting]")).not.toHaveAttribute("data-greeting", "plain"); // the photograph, before

  // Its one place is Settings › Notifications › Data, for a developer as for an organisation member (P27 UX):
  // Profile does not repeat it.
  await page.goto("/settings/profile");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("switch", { name: "Data saver" })).toHaveCount(0);
  await page.goto("/settings/notifications");
  const toggle = page.locator("[data-data-saver-card]").getByRole("switch", { name: "Data saver" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  const cookie = (await context.cookies()).find((c) => c.name === "data-saver");
  expect(cookie?.value).toBe("1");
  expect(cookie?.httpOnly).toBe(false);
  expect(cookie?.sameSite).toBe("Lax");
  expect(cookie!.expires - Date.now() / 1000).toBeGreaterThan(364 * 24 * 60 * 60);

  for (const path of ["/dev", "/dev/discover"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("[data-niche-band]:not([data-niche-band='lattice'])"), path).toHaveCount(0);
    await expect(page.locator("img[src*='/photos/'], source[srcset*='/photos/']"), path).toHaveCount(0);
  }
  await page.goto("/dev");
  await expect(page.locator("[data-greeting]")).toHaveAttribute("data-greeting", "plain");

  await page.goto("/settings/notifications");
  await page.locator("[data-data-saver-card]").getByRole("switch", { name: "Data saver" }).click();
  await expect.poll(async () => (await context.cookies()).some((c) => c.name === "data-saver")).toBe(false);
});

test("an organisation member's data-saver switch is under Settings › Notifications › Data", async ({
  page,
  context,
  browser,
}, info) => {
  const org = await signUpOrg(page.request);
  // A pitch puts a proposal card, with its niche's photograph band, on the organisation's Home.
  const devContext = await browser.newContext({ ...info.project.use });
  await pitchFromDeveloper(devContext.request, org.orgId);
  await devContext.close();
  const home = `/org?org=${org.orgId}`;
  await page.goto(home);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const bands = await page.locator("[data-niche-band]").count();
  expect(await page.locator("[data-niche-band]:not([data-niche-band='lattice'])").count()).toBeGreaterThan(0);

  await page.goto("/settings/notifications");
  const data = page.locator("[data-data-saver-card]");
  await expect(data.getByRole("heading", { name: "Data" })).toBeVisible();
  const toggle = data.getByRole("switch", { name: "Data saver" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  expect((await context.cookies()).find((c) => c.name === "data-saver")?.value).toBe("1");

  // The next page carries no photograph: the org Home's bands are the lattice.
  await page.goto(home);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("[data-niche-band]")).toHaveCount(bands);
  await expect(page.locator("[data-niche-band]:not([data-niche-band='lattice'])")).toHaveCount(0);
  await expect(page.locator("img[src*='/photos/'], source[srcset*='/photos/']")).toHaveCount(0);
});

test("a sign-in reached inside the app deletes the previous person's cache before it returns anywhere", async ({
  page,
  browser,
  context,
}, info) => {
  // The next person: a developer with a password (no second factor), signed up in a browser of their own.
  const other = await browser.newContext({ ...info.project.use });
  const email = `next-${tag()}@example.com`;
  await signUp(other.request, { email, display_name: "Wanjiku Kamau", side: "developer" });
  await other.close();

  // A public problem to start from, whatever the stack holds: the organisation posts a Brief, published as staff
  // approval publishes it (briefs.spec.ts walks the approval itself through the moderation queue).
  const org = await signUpOrg(page.request);
  const problem = await publicBrief(page.request, org.orgId);

  // The first person keeps a tracker; then their session lapses (no sign-out, the cache stays).
  const dev = await pitchFromDeveloper(page.request, org.orgId);
  const tracker = `/dev/engagements/${dev.engagementId}`;
  await page.goto(tracker);
  await workerReady(page);
  await page.goto(tracker);
  await expect.poll(() => kept(page, tracker), SERVER_STEP).toBe(true);
  await context.clearCookies();

  // A public problem, then its "Log in" link: a client navigation to /login?next=/problems/<id>, which the worker
  // never sees; /problems/<id> carries no offline part either.
  await page.goto(`/explore/problems/${problem}`);
  await page.locator("a[href^='/login?next=']").click();
  await expect(page).toHaveURL(/\/login\?next=/);
  expect(await peopleCaches(page)).toHaveLength(1);
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/problems/${problem}$`), SERVER_STEP);
  expect(await peopleCaches(page)).toEqual([]);
  await goOffline(context);
  await expectOfflinePage(page, tracker);
  await goOnline(context);
});

test("a magic link that signs the next person in without a password deletes the previous person's cache", async ({
  page,
  browser,
  context,
}, info) => {
  // The first person keeps a tracker; then their session lapses (no sign-out, the cache stays).
  const org = await signUpOrg(page.request);
  const dev = await pitchFromDeveloper(page.request, org.orgId);
  const tracker = `/dev/engagements/${dev.engagementId}`;
  await page.goto(tracker);
  await workerReady(page);
  await page.goto(tracker);
  await expect.poll(() => kept(page, tracker), SERVER_STEP).toBe(true);
  await context.clearCookies();

  // The next person signs up in another browser; their emailed link is opened in this one, where the password chosen
  // there is not kept: the link signs them in with none (LinkSignIn's no-password way on, on /auth/link, a page with
  // no offline part and not one the worker clears on).
  const other = await browser.newContext({ ...info.project.use });
  const email = `link-${tag()}@example.com`;
  const csrf = ((await (await other.request.get("/api/auth/csrf")).json()) as { csrf_token: string }).csrf_token;
  const signup = await other.request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": csrf },
    data: { email, password: PASSWORD, display_name: "Otieno Ouma", side: "developer", accept_terms: true },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  const link = await waitForSignInLink(other.request, email);
  await other.close();
  expect(await peopleCaches(page)).toHaveLength(1);
  await page.goto(pathOf(link));
  await expect(page.getByRole("heading", { name: "You are signed in" })).toBeVisible(SERVER_STEP);
  expect(await peopleCaches(page)).toEqual([]);
});
