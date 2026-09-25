import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { pathOf, waitForSignInLink } from "./support/mailpit";
import { totp } from "./support/totp";

// X1-1 (REQ-AUTH-01): signup, email link, password login and TOTP against the compose stack (`make dev`), in the
// mobile-360 and desktop projects of playwright.config.ts. Mail is read from Mailpit (E2E_MAILPIT_URL).

const PASSWORD = "jacaranda season in nairobi";
// Steps that wait on the API (argon2id hashing, email, session rotation) get more than the 5 s default: shared CI
// runners and Docker Desktop port forwarding both add seconds of latency at times.
const SERVER_STEP = { timeout: 20_000 };
const NEW_PASSWORD = "long rains over the rift valley";

// example.com is reserved for documentation (RFC 2606) and the stack sends to Mailpit only. Not .test: the API's
// email validation refuses special-use domains.
function uniqueEmail(label: string) {
  return `${label}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/**
 * The page-level rules every auth screen keeps: axe finds nothing serious or critical (AC-UX-4), at most one
 * primary action (AC-UX-2), and no horizontal scroll (AC-UX-1, checked at 360 px in the mobile project).
 */
async function checkScreen(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious, JSON.stringify(serious.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) })), null, 2))
    .toEqual([]);
  expect(await page.locator("[data-primary]").count()).toBeLessThanOrEqual(1);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "horizontal scroll").toBeLessThanOrEqual(0);
}

/** Forms stay inert until React hydrates (components/ui/Form.tsx); wait for that before typing and submitting. */
async function hydrated(page: Page) {
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
}

async function logIn(page: Page, email: string, password: string = PASSWORD) {
  await page.goto("/login");
  await hydrated(page);
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/, SERVER_STEP);
}

test("signed-out visits to signed-in pages go to the login page", async ({ page }) => {
  for (const path of ["/dev", "/org", "/settings/security", "/auth/mfa"]) {
    await page.goto(path);
    await expect(page, path).toHaveURL(/\/login$/);
  }
});

test("landing, login and an unusable link meet the page rules", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator("[data-primary]")).toHaveText("Create an account");
  await checkScreen(page);

  await page.goto("/login");
  await hydrated(page);
  await checkScreen(page);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page.getByText("Enter your email address.")).toBeVisible();
  await expect(page.getByLabel("Email address")).toBeFocused();

  await page.goto("/auth/link");
  await expect(page.getByRole("heading", { name: "This link no longer works" })).toBeVisible();
  await checkScreen(page);
});

test("before JavaScript runs, submitting the login form never puts credentials in the URL", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  await page.goto("/login");
  await expect(page.locator("form")).toHaveAttribute("method", "post");
  await expect(page.getByRole("button", { name: "Log in", exact: true })).toBeDisabled();
  await page.getByLabel("Email address").fill("someone@example.com");
  await page.getByLabel("Password", { exact: true }).fill("my secret passphrase here");
  await page.getByLabel("Password", { exact: true }).press("Enter"); // implicit submission
  await page.getByRole("button", { name: "Log in", exact: true }).click({ force: true });
  await page.waitForTimeout(500);
  const url = new URL(page.url());
  expect(url.search).not.toContain("password=");
  expect(url.search).not.toContain("email=");
  expect(url.pathname).toBe("/login");
  await context.close();
});

test("a wrong password is refused with a message by the form", async ({ page }) => {
  await page.goto("/login");
  await hydrated(page);
  await page.getByLabel("Email address").fill(uniqueEmail("nobody"));
  await page.getByLabel("Password", { exact: true }).fill("not the right password");
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  // Scoped to main: Next.js also renders a route announcer with role="alert".
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "That email and password do not match an account.",
    SERVER_STEP,
  );
});

test("a developer signs up, confirms by email link, logs in with a password and changes it", async ({
  page,
  request,
}) => {
  const email = uniqueEmail("dev");

  await page.goto("/");
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  await hydrated(page);
  await checkScreen(page);

  await page.getByRole("radio", { name: /^As a developer/ }).check();
  await page.getByLabel("Your name").fill("Wanjiru Kamau");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await expect(page.getByLabel("Organisation name")).toHaveCount(0);
  // The four optional consents carry the server's wording (GET /api/consents) and start unticked.
  const consents = page.getByRole("group", { name: /Optional/ }).getByRole("checkbox");
  await expect(consents).toHaveCount(4);
  for (const consent of await consents.all()) {
    await expect(consent).not.toBeChecked();
  }
  await page.getByRole("checkbox", { name: /I accept the terms of service/ }).check();
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/signup\/check-email$/, SERVER_STEP);
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await checkScreen(page);

  await page.goto(pathOf(await waitForSignInLink(request, email)));
  await expect(page).toHaveURL(/\/dev$/, SERVER_STEP);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Wanjiru Kamau");
  await expect(page.getByText("Two-step sign-in is off.")).toBeVisible();
  await checkScreen(page);

  await signOut(page);
  await logIn(page, email);
  await expect(page).toHaveURL(/\/dev$/, SERVER_STEP);

  await page.goto("/settings/security");
  await hydrated(page);
  const passwordSection = page.getByRole("region", { name: "Password" });
  await passwordSection.getByLabel("Current password", { exact: true }).fill(PASSWORD);
  await passwordSection.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await passwordSection.getByRole("button", { name: "Save password" }).click();
  await expect(passwordSection.getByRole("status")).toContainText("Password saved.", SERVER_STEP);
  await checkScreen(page);

  await signOut(page);
  await logIn(page, email, NEW_PASSWORD);
  await expect(page).toHaveURL(/\/dev$/, SERVER_STEP);
});

test("a link opened in another browser signs in without the password and offers to set one", async ({
  page,
  browser,
  request,
}) => {
  const email = uniqueEmail("elsewhere");
  await page.goto("/signup");
  await hydrated(page);
  await page.getByRole("radio", { name: /^As a developer/ }).check();
  await page.getByLabel("Your name").fill("Njeri Mwangi");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("checkbox", { name: /I accept the terms of service/ }).check();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/signup\/check-email$/, SERVER_STEP);

  // A second browser: the signup binding cookie is absent, so the API does not keep the password chosen above.
  const elsewhere = await browser.newContext();
  const other = await elsewhere.newPage();
  await other.goto(pathOf(await waitForSignInLink(request, email)));
  await expect(other.getByRole("heading", { name: "You are signed in" })).toBeVisible(SERVER_STEP);
  expect(new URL(other.url()).hash, "the #token fragment is scrubbed").toBe("");
  await expect(other.locator("[data-primary]")).toHaveText("Set a password");
  await expect(other.getByRole("link", { name: "Continue without a password" })).toHaveAttribute("href", "/dev");
  await checkScreen(other);

  await other.getByRole("link", { name: "Set a password" }).click();
  await expect(other).toHaveURL(/\/settings\/security#password$/);
  await hydrated(other);
  const passwordSection = other.getByRole("region", { name: "Password" });
  await passwordSection.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
  await passwordSection.getByRole("button", { name: "Save password" }).click();
  await expect(passwordSection.getByRole("status")).toContainText("Password saved.", SERVER_STEP);

  await signOut(other);
  await logIn(other, email, NEW_PASSWORD);
  await expect(other).toHaveURL(/\/dev$/, SERVER_STEP);
  await elsewhere.close();
});

test("an organisation owner turns on two-step sign-in and needs a code at the next login", async ({
  page,
  request,
}) => {
  const email = uniqueEmail("org");

  await page.goto("/signup");
  await hydrated(page);
  await page.getByRole("radio", { name: /^For an organisation/ }).check();
  await page.getByLabel("Your name").fill("Achieng Otieno");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Organisation name").fill("Lakeside Water Services");
  await page.getByLabel("Type of organisation").selectOption("county_govt");
  await page.getByRole("checkbox", { name: /I accept the terms of service/ }).check();
  await checkScreen(page);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/signup\/check-email$/, SERVER_STEP);

  await page.goto(pathOf(await waitForSignInLink(request, email)));
  await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
  const turnOn = page.getByRole("link", { name: "Turn on two-step sign-in" });
  await expect(turnOn).toHaveAttribute("data-primary", "");
  await checkScreen(page);

  await turnOn.click();
  await expect(page).toHaveURL(/\/settings\/security$/);
  await hydrated(page);
  await expect(page.getByRole("list", { name: "Setup steps" }).locator("[aria-current=step]")).toHaveCount(1);
  await checkScreen(page);

  // Enrolment asks for the current password first.
  const twoStep = page.getByRole("region", { name: "Two-step sign-in" });
  await twoStep.getByRole("button", { name: "Turn on two-step sign-in" }).click();
  await expect(twoStep.getByText("Enter your current password to make this change.")).toBeVisible(SERVER_STEP);
  await twoStep.getByLabel("Current password", { exact: true }).fill(PASSWORD);
  await twoStep.getByRole("button", { name: "Turn on two-step sign-in" }).click();
  await expect(page.getByTestId("totp-key")).toBeVisible(SERVER_STEP);
  const key = (await page.getByTestId("totp-key").innerText()).replace(/\s+/g, "");
  expect(key).toMatch(/^[A-Z2-7]{16,}$/);
  await expect(page.getByRole("img", { name: /QR code/ })).toBeVisible();
  await checkScreen(page);

  await page.getByLabel("Code from your app").fill(totp(key));
  await page.getByRole("button", { name: "Confirm code" }).click();
  await expect(page.getByTestId("recovery-codes").getByRole("listitem")).toHaveCount(10, SERVER_STEP);
  await checkScreen(page);

  await page.getByRole("button", { name: "I have saved my codes" }).click();
  await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
  await expect(page.getByText("Two-step sign-in is on.")).toBeVisible();

  await signOut(page);
  await logIn(page, email);
  await expect(page).toHaveURL(/\/auth\/mfa$/, SERVER_STEP);
  await hydrated(page);
  await checkScreen(page);

  // The enrolment code's window cannot be replayed, so use the next 30-second window (the server allows +1).
  await page.getByLabel("6-digit code").fill(totp(key, { offset: 1 }));
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
  await expect(page.getByText("Two-step sign-in is on.")).toBeVisible();
});
