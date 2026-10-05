import { expect, test, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { pathOf, waitForMessage } from "./support/mailpit";
import { apiPost, e2OrgMember, OWNER_DATABASE_URL, publishIdea, runTag } from "./support/pitch-scene";
import { checkScreen } from "./support/screen";
import { logInWithPassword, PASSWORD, twoStepDeveloper } from "./support/two-step-account";
import { makeD1 } from "./support/verification";
import { loginReturningTo } from "./support/login";

// P16 (REQ-CON-01, REQ-NOT-03, REQ-UX-01): the two pages every email footer links to, "Manage notifications"
// (/settings/notifications) and "Help" (/help), opened from an email and from the avatar menu; a consent saved on the
// version shown, and the fixed refusal when the wording changed (a real 409 from the API); sign-out from the menu. axe,
// at most one primary action and no horizontal scroll on every screen (AC-UX-1, AC-UX-2, AC-UX-4), in both projects
// (360 px and 1440 px; the 375 px run is the screenshots' viewport).

const SERVER_STEP = { timeout: 20_000 };
const REMINDERS = "Send me reminders about my proposals and engagements by email.";
const MARKETING = "Send me occasional product news by email. You can stop at any time.";
const WHATSAPP = "Send me reminders on WhatsApp (available later).";
// P21 (REQ-PERS-03, D-57 (7)): developers only, off by default.
const DIGEST = "Send me a daily email with how many new problems or Briefs match my saved searches.";
// P21 (REQ-ENG-11, N18, D-57 (2)): a message on an engagement by email, on by default (mutable).
const MESSAGES = /new message on an engagement/i;

async function openMenuItem(page: Page, name: string) {
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("link", { name, exact: true }).click();
}

/** The page's client part has hydrated (its checkboxes answer clicks). */
async function choicesReady(page: Page) {
  await expect(page.getByRole("checkbox", { name: REMINDERS })).toBeEnabled(SERVER_STEP);
  await page.waitForLoadState("networkidle");
}

/** The settings pages share one h1 ("Settings") with the tabs under it; the page's subject heads its card (D-52). */
async function expectNotificationSettings(page: Page) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings");
  await expect(page.getByRole("heading", { level: 2, name: "Notifications" })).toBeVisible();
}

async function expectHelp(page: Page, { signedIn = false } = {}) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Help");
  // Signed in to a portal, a fifth section offers the first-login tour again (D-52); a visitor gets the four.
  await expect(page.getByRole("heading", { level: 2 })).toHaveText([
    "How pitching works",
    "What stays confidential",
    "Reminders",
    "Contact support",
    ...(signedIn ? ["The tour"] : []),
  ]);
  await expect(page.locator("[data-support-placeholder]")).toHaveText("Support contact to be set.");
  await expect(page.locator("[data-primary]")).toHaveCount(0);
}

test("a visitor can read help, and the notification settings ask them to log in", async ({ page }) => {
  await page.goto("/help");
  await expectHelp(page);
  await expect(page.getByRole("link", { name: "Log in" })).toHaveAttribute("href", "/login");
  await expect(page.getByRole("button", { name: "Account" })).toHaveCount(0);
  await checkScreen(page, { strict: true });

  await page.locator("[data-help-section='reminders']").getByRole("link", { name: "Notifications" }).click();
  await expect(page).toHaveURL(loginReturningTo("/settings/notifications"), SERVER_STEP);
});

// P16-A open item 2 (P16-C1): a signed-out reader opening "Manage notifications" from an email signs in, through the
// second factor, and lands back on the settings, not on their home.
test("a signed-out reader signs in, both steps, and lands back on the notification settings", async ({ page }) => {
  const person = await twoStepDeveloper(page, "Wairimu Kamau");
  await page.goto("/settings/notifications");
  await expect(page).toHaveURL(loginReturningTo("/settings/notifications"), SERVER_STEP);
  await checkScreen(page, { strict: true });
  await logInWithPassword(page, person, PASSWORD);
  await expect(page).toHaveURL(/\/auth\/mfa\?next=%2Fsettings%2Fnotifications$/, SERVER_STEP);
  await checkScreen(page, { strict: true });
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
  await page.getByLabel("6-digit code").fill(await person.code());
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/notifications$/, SERVER_STEP);
  await expectNotificationSettings(page);
});

test.describe("a signed-in developer", () => {
  test.beforeEach(async ({ page }) => {
    await signUpDeveloper(page, "Wanjiru Mwangi");
  });

  test("opens both pages from the account menu, saves a choice and signs out", async ({ page }) => {
    await openMenuItem(page, "Notification settings");
    await expect(page).toHaveURL(/\/settings\/notifications$/, SERVER_STEP);
    await expectNotificationSettings(page);
    await choicesReady(page);
    const email = page.getByRole("group", { name: "Email" });
    await expect(email.getByRole("checkbox")).toHaveCount(4);
    await expect(email.getByRole("checkbox", { name: REMINDERS })).not.toBeChecked();
    await expect(email.getByRole("checkbox", { name: MARKETING })).not.toBeChecked();
    await expect(email.getByRole("checkbox", { name: DIGEST })).not.toBeChecked();
    await expect(email.getByRole("checkbox", { name: MESSAGES })).toBeChecked();
    const whatsapp = page.getByRole("checkbox", { name: WHATSAPP });
    await expect(whatsapp).toBeDisabled();
    await expect(page.getByText("WhatsApp messages are not available yet, so this cannot be turned on.")).toBeVisible();
    await expect(page.locator("[data-primary]")).toHaveText("Save choices");
    await checkScreen(page, { strict: true });

    // Turn email reminders on: the API records it, and a reload shows it.
    await page.getByRole("checkbox", { name: REMINDERS }).check();
    await page.locator("[data-primary]").click();
    await expect(page.getByRole("status").filter({ hasText: "Your choices are saved." })).toBeVisible(SERVER_STEP);
    await checkScreen(page, { strict: true });
    const recorded = (await (await page.request.get("/api/me/consents")).json()) as Array<{
      purpose: string;
      granted: boolean;
    }>;
    expect(recorded.find((c) => c.purpose === "reminders")?.granted).toBe(true);
    expect(recorded.find((c) => c.purpose === "marketing")?.granted).toBe(false);
    await page.reload();
    await choicesReady(page);
    await expect(page.getByRole("checkbox", { name: REMINDERS })).toBeChecked();

    await openMenuItem(page, "Help");
    await expect(page).toHaveURL(/\/help$/, SERVER_STEP);
    await expectHelp(page, { signedIn: true });
    await expect(page.getByRole("button", { name: "Account" })).toBeVisible();
    await checkScreen(page, { strict: true });

    await page.getByRole("button", { name: "Account" }).click();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/, SERVER_STEP);
    await page.goto("/settings/notifications");
    await expect(page).toHaveURL(loginReturningTo("/settings/notifications"), SERVER_STEP);
  });

  test("gets one fixed sentence when the wording changed while the page was open (409)", async ({ page }) => {
    await page.goto("/settings/notifications");
    await choicesReady(page);
    // The page sent the version it showed; here that version is stale, as if consents.yaml changed meanwhile, so the
    // API itself answers 409 consent_text_changed.
    await page.route("**/api/me/consents", async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      const body = JSON.parse(route.request().postData() ?? "{}") as Record<string, { version: string }>;
      for (const decision of Object.values(body)) decision.version = "2000-01-01.1";
      const answer = await route.fetch({ postData: JSON.stringify(body) });
      expect(answer.status()).toBe(409);
      await route.fulfill({ response: answer });
    });
    await page.getByRole("checkbox", { name: MARKETING }).check();
    await page.locator("[data-primary]").click();
    // Next.js's route announcer is also role="alert": the refusal is the one holding a sentence.
    const alert = page.getByRole("alert").filter({ has: page.locator("[data-refusal]") });
    await expect(alert).toBeFocused(SERVER_STEP);
    await expect(alert.locator("[data-refusal='changed']")).toHaveText(
      "The wording of these choices changed after you opened this page, so nothing was saved.",
    );
    await expect(alert.getByRole("link")).toHaveCount(1);
    await expect(page.getByText("The consent wording has changed")).toHaveCount(0); // never the API's own message
    await checkScreen(page, { strict: true });

    await page.unroute("**/api/me/consents");
    await alert.getByRole("link", { name: "Reload the page" }).click();
    await choicesReady(page);
    await expect(page.locator("[data-refusal]")).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: MARKETING })).not.toBeChecked(); // nothing was recorded
  });
});

test.describe("from an email", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL makes the developer D1 and the organisation E2").toBeTruthy();
  });
  test.setTimeout(150_000);

  test("EM1's footer opens the notification settings and help", async ({ page, browser, baseURL }) => {
    const email = await signUpDeveloper(page, "Kamau Njoroge");
    makeD1(email);
    const idea = await publishIdea(page.request, `Maji safi ${runTag()}`);
    const buyer = await e2OrgMember(browser, baseURL!);
    try {
      await apiPost(page.request, `/api/me/proposals/${idea.id}/tags`, { org_ids: [buyer.orgId] }, 201);
      const em1 = await waitForMessage(page.request, email, /^Your proposal ".*" is registered/);
      const settings = /Manage notifications: (\S+)/.exec(em1.text)?.[1];
      const help = /Help: (\S+)/.exec(em1.text)?.[1];
      expect(settings, em1.text).toMatch(/\/settings\/notifications$/);
      expect(help, em1.text).toMatch(/\/help$/);
      expect(em1.html).toContain(`href="${settings}"`);
      expect(em1.html).toContain(`href="${help}"`);

      await page.goto(pathOf(settings!));
      await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings", SERVER_STEP);
      await expectNotificationSettings(page);
      await choicesReady(page);
      await checkScreen(page, { strict: true });

      await page.goto(pathOf(help!));
      await expectHelp(page, { signedIn: true });
      await expect(page.getByRole("button", { name: "Account" })).toBeVisible();
      await checkScreen(page, { strict: true });
    } finally {
      await buyer.close();
    }
  });
});
