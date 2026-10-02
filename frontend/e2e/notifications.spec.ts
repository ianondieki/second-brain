import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import { loginReturningTo } from "./support/login";
import { checkScreen, expectEmptyState } from "./support/screen";
import { OWNER_DATABASE_URL, pitchFromDeveloper, post, signUpOrg } from "./support/tracker-scene";

// P19-C (REQ-NOT-03, the in-app channel; docs/spec/07 item 1, the bell): the card's story against the compose stack.
// Amina (a developer) pitches to an organisation; the organisation starts the review and approves to proceed, and
// the tracker's notices (bridge/engagements/notify.py, written by the worker) land in her bell. She opens the bell:
// both rows, the newer first; opening one marks it read and lands on the tracker; "Mark all as read" empties the
// badge. The demo seed writes no in-app rows, so the story makes its own through the API (as tracker.spec.ts does).
// axe (strict), at most one primary action (here none) and no horizontal scroll on each screen, in both projects.
//
// Needs E2E_DATABASE_OWNER_URL (tracker-scene: D1/D2, E2, signatory), an API with FEATURE_DEALS_ENABLED=true and
// FEATURE_TIER2_ENABLED=true, and the worker running. E2E_SHOTS_DIR saves screenshots at 375 px and 1440 px under
// the committed names (docs/demo/screenshots/p19/).

const SERVER_STEP = { timeout: 20_000 };
const WORKER = { timeout: 60_000, intervals: [500, 1_000, 2_000] };

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
});

/** Saved under the name the committed shot has in docs/demo/screenshots/p19/ (the light theme, the default). */
async function shot(page: Page, info: TestInfo, name: "notifications-light" | "notifications-empty-light") {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const size = page.viewportSize()!;
  const width = info.project.name.startsWith("mobile") ? 375 : 1440;
  await page.setViewportSize({ width, height: size.height });
  await page.screenshot({ path: join(dir, `${name}-${width}.jpg`), fullPage: true, type: "jpeg", quality: 70, scale: "css" });
  await page.setViewportSize(size);
}

async function unreadCount(request: APIRequestContext): Promise<number> {
  const response = await request.get("/api/me/notifications/unread-count");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { count: number }).count;
}

/** The organisation's step on the engagement, on the lock version it last read. */
async function orgCommand(request: APIRequestContext, engagementId: string, command: string, body: Record<string, unknown> = {}) {
  const detail = (await (await request.get(`/api/engagements/${engagementId}`)).json()) as { lock_version: number };
  await post(request, `/api/engagements/${engagementId}/${command}`, { lock_version: detail.lock_version, ...body });
}

function bell(page: Page) {
  return page.getByRole("banner").locator("[data-notification-bell]");
}

test("a signed-out visit to the notifications goes to the login page", async ({ page }) => {
  await page.goto("/notifications");
  await expect(page).toHaveURL(loginReturningTo("/notifications"));
});

test("a new account's bell has no count and its page is one sentence and one action", async ({ browser }, info) => {
  const context = await browser.newContext({ ...info.project.use });
  const page = await context.newPage();
  try {
    await signUpOrg(page.request);
    await page.goto("/org");
    await expect(bell(page)).toHaveAccessibleName("Notifications");
    await expect(bell(page).locator("[data-unread-badge]")).toHaveCount(0);
    await bell(page).click();
    await expect(page).toHaveURL(/\/notifications$/, SERVER_STEP);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Notifications");
    // The organisation's own navigation stays (PortalNavFor).
    await expect(page.getByRole("navigation", { name: "Organisation" })).toBeVisible();
    await expectEmptyState(page, "Nothing yet: new proposals, scout matches and engagement updates for your organisation will land here.", "Go to your home page");
    await checkScreen(page, { strict: true });
    await shot(page, info, "notifications-empty-light");
  } finally {
    await context.close();
  }
});

test("Amina's bell: the review and the approval, opened and marked read", async ({ page, browser }, info) => {
  test.setTimeout(240_000);
  const orgContext = await browser.newContext({ ...info.project.use });
  const orgPage = await orgContext.newPage();
  try {
    const org = await signUpOrg(orgPage.request);
    const amina = await pitchFromDeveloper(page.request, org.orgId);
    const tracker = `/dev/engagements/${amina.engagementId}`;
    // Publishing and pitching already left Amina a notice or two: count from there.
    const before = await unreadCount(page.request);

    // The organisation starts the review, then approves to proceed (non-binding), naming its contact.
    await orgCommand(orgPage.request, amina.engagementId, "start-review");
    await expect.poll(() => unreadCount(page.request), WORKER).toBe(before + 1);
    const me = (await (await orgPage.request.get("/api/auth/me")).json()) as { user: { id: string } };
    const contactBy = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
    await orgCommand(orgPage.request, amina.engagementId, "approve", {
      contact_user_id: me.user.id,
      contact_channel: "email",
      contact_by: contactBy,
    });
    await expect.poll(() => unreadCount(page.request), WORKER).toBe(before + 2);

    // The bell says it on any page, in words and on the badge.
    await page.goto("/dev");
    await expect(bell(page)).toHaveAccessibleName(`Notifications, ${before + 2} unread`);
    await expect(bell(page).locator("[data-unread-badge]")).toHaveText(String(before + 2));
    await bell(page).click();
    await expect(page).toHaveURL(/\/notifications$/, SERVER_STEP);
    await expect(page.getByRole("navigation", { name: "Developer" })).toBeVisible();

    // The two new rows under Today, the newer (the approval) first, each unread; the earlier notices follow them.
    const today = page.getByRole("region", { name: "Today" });
    const rows = today.locator("[data-notification]");
    await expect(rows).toHaveCount(before + 2);
    await expect(rows.nth(0)).toContainText(`${org.orgName} approved "${amina.title}" to proceed`);
    await expect(rows.nth(1)).toContainText(`${org.orgName} started reviewing "${amina.title}"`);
    await expect(rows.nth(0)).toHaveAttribute("data-unread", "true");
    await expect(rows.nth(1)).toHaveAttribute("data-unread", "true");
    await expect(rows.nth(0).locator("time:visible")).toHaveText(/^\d{2}:\d{2} EAT$/);
    await expect(page.locator("[data-primary]")).toHaveCount(0);
    await checkScreen(page, { strict: true });
    await shot(page, info, "notifications-light");

    // Opening the approval marks it read and lands on the tracker; the bell there counts one.
    await rows.nth(0).getByRole("link").click();
    await expect(page).toHaveURL(new RegExp(`${tracker}$`), SERVER_STEP);
    await expect(bell(page)).toHaveAccessibleName(`Notifications, ${before + 1} unread`);

    await bell(page).click();
    await expect(page).toHaveURL(/\/notifications$/, SERVER_STEP);
    await expect(rows.nth(0)).toHaveAttribute("data-unread", "false");
    await expect(rows.nth(1)).toHaveAttribute("data-unread", "true");

    // Mark all as read: the badge empties and the action closes.
    const markAll = page.getByRole("button", { name: "Mark all as read" });
    await markAll.click();
    await expect(page.getByRole("status").filter({ hasText: "All your notifications are marked as read." })).toBeVisible(SERVER_STEP);
    await expect(bell(page)).toHaveAccessibleName("Notifications", SERVER_STEP);
    await expect(bell(page).locator("[data-unread-badge]")).toHaveCount(0);
    await expect(markAll).toBeDisabled();
    await expect(rows.nth(1)).toHaveAttribute("data-unread", "false");
    expect(await unreadCount(page.request)).toBe(0);
    await checkScreen(page, { strict: true });
  } finally {
    await orgContext.close();
  }
});
