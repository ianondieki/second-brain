import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { appToday, plusDays } from "./support/clock";
import { checkWidths, shot } from "./support/discover-scene";
import { signUpOrgMember, verifyOrg } from "./support/org-scene";
import { newStaffAdmin, OWNER_DATABASE_URL } from "./support/research-scene";
import { PASSWORD, type Person } from "./support/tracker-scene";

// REQ-DEV-02 (D-60, D-61; docs/platform/tasks/P22.md B7) against the demo stack, in both projects: an E2
// organisation's member posts an event from Events, a staff admin publishes it from /admin/events, and a new developer
// in that county finds it on Home's This week and on /dev/week, opens it, downloads its .ics, asks to be reminded (the
// line says what will come) and declines; the trend of the day opens from Home; an organisation member's Home has no
// strip and /dev/week sends them home as every developer route does. Strict axe, one primary action and no sideways
// scroll on every state, at 360 and 375 px (mobile-360) and 1440 px (desktop). E2E_SHOTS_DIR saves screenshots.
//
// Each project posts in its own county, so the two runs never crowd each other's strip; the event is cancelled at
// the end, so reruns leave nothing on the developers' Home.

const SERVER_STEP = { timeout: 20_000 };
const COUNTY: Record<string, { code: string; name: string }> = {
  "mobile-360": { code: "KE-12", name: "Kericho" },
  desktop: { code: "KE-13", name: "Kiambu" },
};
const REMINDER_LINES = [
  "An email the day before and a notice here on the morning.",
  "A notice here on the morning. Email reminders are off in Settings.",
  "A notice here on the morning. Verify your email for the email reminder.",
];

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function hydrated(page: Page) {
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
}

/** The staff admin signs in through the screens (password, then a fresh code). */
async function signIn(page: Page, person: Person) {
  await page.goto("/login");
  await hydrated(page);
  await page.getByLabel("Email address").fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/mfa$/, SERVER_STEP);
  await hydrated(page);
  await page.getByLabel("6-digit code").fill(await person.code());
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/admin\//, SERVER_STEP);
}

async function newPage(browser: Browser, baseURL: string | undefined, width: number) {
  const context = await browser.newContext({ baseURL, viewport: { width, height: 800 } });
  return context.newPage();
}

test.describe("This week", () => {
  test.setTimeout(240_000);

  test("an organisation posts an event, staff publish it, a developer near it is reminded", async ({ page, browser, baseURL }, info) => {
    test.skip(!OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL makes the organisation E2 and the staff admin");
    const width = page.viewportSize()!.width;
    const county = COUNTY[info.project.name] ?? COUNTY.desktop;
    const title = `Mobile money clinic ${Date.now().toString(36)}`;

    // The organisation's member (E2, an editor) posts from Events.
    const orgPage = await newPage(browser, baseURL, width);
    const member = await signUpOrgMember(orgPage.request, "Events");
    verifyOrg(member, "e2");
    const day = plusDays(await appToday(orgPage.request), 1);
    let eventId = "";
    try {
      await orgPage.goto("/org/events");
      await expect(orgPage.getByRole("navigation", { name: "Organisation" }).getByRole("link", { name: "Events" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      await expect(orgPage.locator("[data-empty=events]")).toBeVisible();
      await checkWidths(orgPage, info);
      await orgPage.locator("[data-primary]").click();
      await expect(orgPage).toHaveURL(/\/org\/events\/new$/, SERVER_STEP);
      await hydrated(orgPage);
      await orgPage.getByLabel("Title", { exact: true }).fill(title);
      await orgPage.getByLabel("Description", { exact: true }).fill("Short talks on payment APIs.\n\nBring a laptop.");
      const dates = orgPage.getByLabel("Date", { exact: true });
      const times = orgPage.getByLabel("Time", { exact: true });
      await dates.nth(0).fill(day);
      await times.nth(0).fill("09:00");
      await dates.nth(1).fill(day);
      await times.nth(1).fill("11:00");
      // The switch swaps the venue and county for the join address, and back.
      const online = orgPage.getByRole("switch", { name: "Online event" });
      await online.click();
      await expect(orgPage.getByLabel("Join address")).toBeVisible();
      await expect(orgPage.getByLabel("Venue")).toHaveCount(0);
      await online.click();
      await orgPage.getByLabel("Venue").fill("Innovation hub, town centre");
      await orgPage.getByLabel("County").selectOption(county.code);
      await checkWidths(orgPage, info);
      await shot(orgPage, info, "events-org-form");
      await orgPage.getByRole("button", { name: "Post for review" }).click();
      await expect(orgPage).toHaveURL(/\/org\/events\/[0-9a-f-]{36}$/, SERVER_STEP);
      eventId = /\/org\/events\/([0-9a-f-]{36})$/.exec(orgPage.url())![1];
      const heading = orgPage.getByRole("heading", { name: title, level: 1 });
      await expect(heading).toBeFocused(SERVER_STEP);
      await expect(orgPage.locator("[data-state-note=draft]")).toBeVisible();
      await checkWidths(orgPage, info);
      await shot(orgPage, info, "events-org-event");

      // A staff admin publishes it from the queue.
      const admin = await newStaffAdmin(browser, baseURL!);
      const staffPage = await newPage(browser, baseURL, width);
      try {
        await signIn(staffPage, admin);
        await staffPage.goto("/admin/events");
        const row = staffPage.locator(`[data-admin-event="${eventId}"]`);
        await expect(row).toContainText(member.orgName);
        await checkWidths(staffPage, info);
        await shot(staffPage, info, "events-admin-queue");
        await row.getByRole("link", { name: title }).click();
        await expect(staffPage.getByRole("heading", { name: title, level: 1 })).toBeVisible(SERVER_STEP);
        await checkWidths(staffPage, info);
        await staffPage.getByRole("button", { name: "Publish" }).click();
        const dialog = staffPage.getByRole("dialog", { name: "Publish this event?" });
        await expect(dialog).toBeVisible();
        await checkWidths(staffPage, info);
        await dialog.getByRole("button", { name: "Publish" }).click();
        await expect(staffPage.locator("[data-state-note=published]")).toBeVisible(SERVER_STEP);
        await checkWidths(staffPage, info);
      } finally {
        await staffPage.context().close();
      }

      // A new developer in that county finds it on Home and on This week.
      await signUpDeveloper(page, "Kendi Mutua");
      const patched = await page.request.patch("/api/me/profile", {
        headers: { "X-CSRF-Token": await csrf(page.request) },
        data: { county_code: county.code },
      });
      expect(patched.status(), await patched.text()).toBe(200);
      await page.goto("/dev");
      const strip = page.locator("[data-home=week]");
      await expect(strip.getByRole("heading", { name: "This week", level: 2 })).toBeVisible();
      const row = strip.locator(`[data-week-event="${eventId}"]`);
      await expect(row).toContainText(county.name);
      await expect(row).toContainText(`By ${member.orgName}`);
      await expect(row).toContainText(/ · 09:00/);
      await expect(page.locator("[data-primary]")).toHaveCount(1);
      await checkWidths(page, info);
      await shot(page, info, "events-home");

      await strip.getByRole("link", { name: "See the week" }).click();
      await expect(page).toHaveURL(/\/dev\/week$/, SERVER_STEP);
      await expect(page.getByRole("heading", { name: "This week", level: 1 })).toBeVisible();
      await expect(page.locator(`[data-week-event="${eventId}"]`)).toBeVisible();
      await checkWidths(page, info);
      await shot(page, info, "events-week");

      // The event's page: when, where, the calendar and Remind me.
      await page.locator(`[data-week-event="${eventId}"]`).getByRole("link", { name: title }).click();
      await expect(page).toHaveURL(new RegExp(`/dev/events/${eventId}$`), SERVER_STEP);
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
      await expect(page.locator("[data-event-when]")).toContainText("09:00 to 11:00");
      await expect(page.locator("[data-description] p")).toHaveCount(2);
      await checkWidths(page, info);
      await shot(page, info, "events-event");

      const ics = page.locator("[data-ics]");
      await expect(ics).toHaveAttribute("download", "");
      const file = await page.request.get((await ics.getAttribute("href"))!);
      expect(file.status()).toBe(200);
      expect(file.headers()["content-type"]).toMatch(/^text\/calendar/);
      expect(await file.text()).toMatch(/^BEGIN:VCALENDAR/);
      const google = page.locator("[data-google]");
      await expect(google).toHaveAttribute("target", "_blank");
      await expect(google).toHaveAttribute("rel", "noopener noreferrer");
      await expect(google).toHaveAttribute("href", /^https:\/\/calendar\.google\.com\//);

      const line = page.locator("[data-reminder-line]");
      await page.getByRole("button", { name: "Remind me" }).click();
      await expect(page.getByRole("button", { name: "Don't remind me" })).toBeVisible(SERVER_STEP);
      await expect(line).toBeFocused();
      const said = ((await line.textContent()) ?? "").replace(/^Reminder set\.\s*/, "");
      expect(REMINDER_LINES).toContain(said);
      await expect(page.locator("[data-primary]")).toHaveCount(0);
      await checkWidths(page, info);
      await shot(page, info, "events-reminded");
      // The server holds it: after a reload the page offers to decline, and Home's row is marked.
      await page.reload();
      await expect(page.getByRole("button", { name: "Don't remind me" })).toBeVisible(SERVER_STEP);
      await page.goto("/dev");
      await expect(strip.locator(`[data-week-event="${eventId}"] [data-reminder-set]`)).toHaveText("Reminder set");
      await page.goto(`/dev/events/${eventId}`);
      await page.getByRole("button", { name: "Don't remind me" }).click();
      await expect(line).toHaveText("Reminder removed. Nothing will be sent.", SERVER_STEP);
      await expect(page.getByRole("button", { name: "Remind me" })).toBeVisible();
      await checkWidths(page, info);
      // Declined, it stays declined after a reload, and Home's row is no longer marked.
      await page.reload();
      await expect(page.getByRole("button", { name: "Remind me" })).toBeVisible(SERVER_STEP);
      await page.goto("/dev");
      await expect(strip.locator(`[data-week-event="${eventId}"]`)).toBeVisible();
      await expect(strip.locator(`[data-week-event="${eventId}"] [data-reminder-set]`)).toHaveCount(0);

      // The trend of the day opens from Home (the demo seed publishes two hand-written cards).
      await page.goto("/dev");
      const trend = strip.locator("[data-week-trend]");
      await expect(trend).toHaveCount(1);
      const name = ((await trend.getByRole("link").textContent()) ?? "").trim();
      await trend.getByRole("link").click();
      await expect(page).toHaveURL(/\/dev\/trends\/[0-9a-f-]{36}$/, SERVER_STEP);
      await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();
      await expect(page.locator("[data-label]")).toContainText(/^Trend · /);
      await expect(page.locator("[data-source]").first()).toBeVisible();
      await checkWidths(page, info);
      await shot(page, info, "events-trend");
    } finally {
      if (eventId) {
        await orgPage.request.post(`/api/orgs/${member.orgId}/events/${eventId}/cancel`, {
          headers: { "X-CSRF-Token": await csrf(orgPage.request) },
        });
      }
      await orgPage.context().close();
    }
  });

  test("an organisation member has no This week and is sent home from it", async ({ page }, info) => {
    test.skip(!OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL is needed for the organisation's scene");
    await signUpOrgMember(page.request, "Viewer");
    // Developer Home (and so its strip) is not theirs: /dev sends them to their own home.
    await page.goto("/dev");
    await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
    await page.goto("/dev/week");
    await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
    expect((await page.request.get("/api/me/week")).status()).toBe(404);
    await checkWidths(page, info);
  });
});
