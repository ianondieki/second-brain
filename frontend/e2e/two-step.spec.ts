import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import { waitForSignInLink } from "./support/mailpit";
import { checkScreen } from "./support/screen";
import { OWNER_DATABASE_URL, PASSWORD, Person } from "./support/tracker-scene";

// REQ-AUTH-01 follow-ups 7 and 8, frontend halves, against the compose stack in the mobile-360 and desktop projects:
// "Cancel setup" clears the pending key at the server (DELETE /api/auth/totp/enrol) and acts on its answer, and
// "Get new recovery codes" replaces the codes a lost setup answer never showed (step-up, password, codes shown once;
// the old codes stop working, a new one signs in). Each screen keeps the page rules (axe, one primary action, no
// horizontal scroll).
//
// Needs E2E_DATABASE_OWNER_URL: the test reads the pending key's column after Cancel and ages the second factor to
// reach the step-up; test accounts (@example.com) only. E2E_SHOTS_DIR saves screenshots at 375 px (mobile project)
// and 1440 px (desktop) for the task card.

const SERVER_STEP = { timeout: 20_000 };
const MAILPIT = (process.env.E2E_MAILPIT_URL ?? "http://localhost:8025").replace(/\/$/, "");

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL reads the pending key and ages the second factor").toBeTruthy();
});

/** One row as the database owner; the address travels as a psql variable, never spliced into the SQL. */
function ownerValue(sql: string, email: string): string {
  if (!/^[a-z0-9.+-]+@([a-z0-9-]+\.)*example\.com$/.test(email)) throw new Error("test accounts only");
  const result = spawnSync("psql", [OWNER_DATABASE_URL!, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-v", `email=${email}`], {
    input: sql,
    encoding: "utf-8",
    timeout: 15_000,
  });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
  return result.stdout.trim();
}

/**
 * The page rules at the project's width (360 px or 1440 px) and again at 375 px in the mobile project, then, with
 * E2E_SHOTS_DIR, a screenshot at 375 px (mobile) or 1440 px (desktop).
 */
async function checkAndShoot(page: Page, info: TestInfo, name: string) {
  await checkScreen(page);
  const size = page.viewportSize()!;
  const width = info.project.name.startsWith("mobile") ? 375 : 1440;
  await page.setViewportSize({ width, height: size.height });
  if (width !== size.width) await checkScreen(page);
  const dir = process.env.E2E_SHOTS_DIR;
  if (dir) {
    mkdirSync(dir, { recursive: true });
    const path = join(dir, `${name}-${width}.jpg`);
    await page.screenshot({ path, fullPage: true, type: "jpeg", quality: 70, scale: "css" });
  }
  await page.setViewportSize(size);
}

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

/** A new organisation owner (two-step sign-in required by the role), signed in on the page, two-step sign-in off. */
async function signUpOwner(page: Page): Promise<string> {
  const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const email = `owner-${id}@example.com`;
  const signup = await page.request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": await csrf(page.request) },
    data: {
      email,
      password: PASSWORD,
      display_name: "Achieng Otieno",
      side: "org",
      org: { legal_name: `Lakeside Water ${id}`, kind: "county_govt" },
      accept_terms: true,
    },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  const token = new URL(await waitForSignInLink(page.request, email)).hash.replace(/^#token=/, "");
  const consume = await page.request.post("/api/auth/magic-link/consume", {
    headers: { "X-CSRF-Token": await csrf(page.request) },
    data: { token },
  });
  expect(consume.status(), await consume.text()).toBeLessThan(300);
  return email;
}

/** Starts setup on /settings/security with the password and returns the key the page shows. */
async function startSetup(page: Page): Promise<string> {
  await page.goto("/settings/security");
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
  const twoStep = page.getByRole("region", { name: "Two-step sign-in" });
  await twoStep.getByLabel("Confirm with your current password", { exact: true }).fill(PASSWORD);
  await twoStep.getByRole("button", { name: "Turn on two-step sign-in" }).click();
  await expect(page.getByTestId("totp-key")).toBeVisible(SERVER_STEP);
  return (await page.getByTestId("totp-key").innerText()).replace(/\s+/g, "");
}

/** Whether the newest mail to `to` says `text` (Mailpit, the stack's test mailbox). */
async function mailSays(request: APIRequestContext, to: string, text: string): Promise<boolean> {
  const list = await request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}&limit=20`);
  if (!list.ok()) return false;
  const { messages = [] } = (await list.json()) as { messages?: Array<{ ID: string }> };
  for (const { ID } of messages) {
    const message = (await (await request.get(`${MAILPIT}/api/v1/message/${ID}`)).json()) as { Text?: string };
    if (message.Text?.includes(text)) return true;
  }
  return false;
}

test("Cancel setup clears the pending key: a code from it no longer turns two-step sign-in on", async ({
  page,
}, info) => {
  const email = await signUpOwner(page);
  const key = await startSetup(page);
  expect(ownerValue("SELECT totp_pending_enc IS NOT NULL FROM users WHERE email = :'email';", email)).toBe("t");

  await page.getByRole("button", { name: "Cancel setup" }).click();
  const cancelled = page.getByRole("status").filter({ hasText: "Setup cancelled." });
  await expect(cancelled).toBeFocused(SERVER_STEP);
  await expect(cancelled).toContainText("delete that entry");
  await expect(page.getByRole("button", { name: "Turn on two-step sign-in" })).toBeVisible();
  await checkAndShoot(page, info, "p17f-cancelled");

  // The server's key is gone, not left to expire: confirming with a code from it is refused.
  expect(ownerValue("SELECT totp_pending_enc IS NULL FROM users WHERE email = :'email';", email)).toBe("t");
  const person = new Person(email, "Achieng Otieno", key);
  const confirm = await page.request.post("/api/auth/totp/confirm", {
    headers: { "X-CSRF-Token": await csrf(page.request) },
    data: { code: await person.code() },
  });
  expect(confirm.status()).toBe(409);
  expect(((await confirm.json()) as { detail: { code: string } }).detail.code).toBe("no_pending_enrolment");
});

test("after a lost setup answer, Cancel shows 'on', and new recovery codes replace the unseen ones", async ({
  page,
}, info) => {
  test.setTimeout(120_000);
  const email = await signUpOwner(page);
  const key = await startSetup(page);
  const person = new Person(email, "Achieng Otieno", key);

  // The server commits the confirmation, but its answer (with the recovery codes) never reaches the page.
  let unseen: string[] = [];
  await page.route("**/api/auth/totp/confirm", async (route) => {
    const response = await route.fetch();
    unseen = ((await response.json()) as { recovery_codes: string[] }).recovery_codes;
    await route.abort("connectionreset");
  });
  await page.getByLabel("Code from your app").fill(await person.code());
  await page.getByRole("button", { name: "Confirm code" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "We could not reach the server." })).toBeVisible(SERVER_STEP);
  await page.unroute("**/api/auth/totp/confirm");
  expect(unseen).toHaveLength(10);

  // Cancel's DELETE answers 409 totp_already_enabled: the "on" screen, and no advice to delete the app entry.
  await page.getByRole("button", { name: "Cancel setup" }).click();
  await expect(page.getByText("Two-step sign-in is on.")).toBeVisible(SERVER_STEP);
  const notice = page.getByRole("alert").filter({ hasText: "Your recovery codes could not be shown." });
  await expect(notice).toBeFocused();
  await expect(notice).toContainText("Then get new recovery codes below.");
  await expect(page.getByText(/delete that entry/)).toHaveCount(0);
  const renew = page.getByRole("button", { name: "Get new recovery codes" });
  await expect(renew).toHaveAttribute("data-primary", "");
  await checkAndShoot(page, info, "p17f-codes-not-shown");

  // The second factor is 13 hours old: the API asks for a fresh code before it makes new codes.
  person.staleSecondFactor();
  await renew.click();
  const recovery = page.getByRole("region", { name: "Recovery codes" });
  await expect(recovery.getByText("Your old recovery codes stop working as soon as the new ones are made.")).toBeVisible();
  const password = recovery.getByLabel("Confirm with your current password", { exact: true });
  await expect(password).toBeFocused();
  await expect(page.getByRole("region", { name: "Password" })).toBeHidden(); // one task at a time
  await checkAndShoot(page, info, "p17f-renew-form");

  await password.fill(PASSWORD);
  await recovery.getByRole("button", { name: "Get new recovery codes" }).click();
  await expect(recovery.getByText("To get new codes, enter the current code from your authenticator app.")).toBeVisible(
    SERVER_STEP,
  );
  await checkAndShoot(page, info, "p17f-renew-step-up");
  await recovery.getByLabel("Code from your app").fill(await person.code());
  await recovery.getByRole("button", { name: "Confirm and get new codes" }).click();

  const ready = page.getByRole("status").filter({ hasText: "Your new recovery codes are ready." });
  await expect(ready).toBeFocused(SERVER_STEP);
  const codes = await page.getByTestId("recovery-codes").getByRole("listitem").allInnerTexts();
  expect(codes).toHaveLength(10);
  expect(codes.some((code) => unseen.includes(code))).toBe(false);
  await expect(page.getByText(/could not be shown/)).toHaveCount(0);
  await expect(page.locator("[data-primary]")).toHaveText("I have saved my codes");
  await checkAndShoot(page, info, "p17f-renew-codes");

  await page.getByRole("button", { name: "I have saved my codes" }).click();
  await expect(page.getByTestId("recovery-codes")).toHaveCount(0);
  await expect(renew).toBeFocused();
  await expect.poll(() => mailSays(page.request, email, "New recovery codes were created."), SERVER_STEP).toBe(true);

  // At the next sign-in, an old code is refused and a new one works.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/, SERVER_STEP);
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/mfa$/, SERVER_STEP);
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
  await page.getByRole("button", { name: "Use a recovery code" }).click();
  await page.getByLabel("Recovery code").fill(unseen[0]);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.locator("main").getByRole("alert")).toContainText("That code did not work.", SERVER_STEP);
  await page.getByLabel("Recovery code").fill(codes[0]);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
});
