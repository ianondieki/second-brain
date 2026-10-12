import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type BrowserContext, type Page, type TestInfo } from "@playwright/test";

import { checkScreen } from "./support/screen";
import { OWNER_DATABASE_URL, pitchFromDeveloper, signUpOrg } from "./support/tracker-scene";

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
  await expect(page.getByRole("link", { name: "Go to Engagements" })).toHaveAttribute("href", "/dev/engagements");
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
  await expect(page.getByRole("link", { name: "Go to Engagements" })).toHaveAttribute(
    "href",
    `/org/engagements${query}`,
  );
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

  await page.goto("/settings/profile");
  const toggle = page.getByRole("switch", { name: "Data saver" });
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

  await page.goto("/settings/profile");
  await page.getByRole("switch", { name: "Data saver" }).click();
  await expect.poll(async () => (await context.cookies()).some((c) => c.name === "data-saver")).toBe(false);
});
