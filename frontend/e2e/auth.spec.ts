import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { pathOf, waitForSignInLink } from "./support/mailpit";
import { totp } from "./support/totp";

// X1-1 (REQ-AUTH-01): signup, email link, password login and TOTP against the compose stack (`make dev`), in the
// mobile-360 and desktop projects of playwright.config.ts. Mail is read from Mailpit (E2E_MAILPIT_URL).

const PASSWORD = "jacaranda season in nairobi";

function uniqueEmail(label: string) {
  return `${label}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}@example.test`;
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

async function logIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
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
  await checkScreen(page);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page.getByText("Enter your email address.")).toBeVisible();
  await expect(page.getByLabel("Email address")).toBeFocused();

  await page.goto("/auth/link");
  await expect(page.getByRole("heading", { name: "This link no longer works" })).toBeVisible();
  await checkScreen(page);
});

test("a wrong password is refused with a message by the form", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email address").fill(uniqueEmail("nobody"));
  await page.getByLabel("Password", { exact: true }).fill("not the right password");
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  // Scoped to main: Next.js also renders a route announcer with role="alert".
  await expect(page.locator("main").getByRole("alert")).toContainText(
    "That email and password do not match an account.",
  );
});

test("a developer signs up, confirms by email link, signs out and logs in with a password", async ({
  page,
  request,
}) => {
  const email = uniqueEmail("dev");

  await page.goto("/");
  await page.getByRole("link", { name: "Create an account" }).click();
  await expect(page).toHaveURL(/\/signup$/);
  await checkScreen(page);

  await page.getByRole("radio", { name: /^As a developer/ }).check();
  await page.getByLabel("Your name").fill("Wanjiru Kamau");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await expect(page.getByLabel("Organisation name")).toHaveCount(0);
  for (const consent of await page.getByRole("group", { name: /Optional/ }).getByRole("checkbox").all()) {
    await expect(consent).not.toBeChecked();
  }
  await page.getByRole("checkbox", { name: /I accept the terms of service/ }).check();
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/signup\/check-email$/);
  await expect(page.getByRole("heading", { name: "Check your email" })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await checkScreen(page);

  await page.goto(pathOf(await waitForSignInLink(request, email)));
  await expect(page).toHaveURL(/\/dev$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Wanjiru Kamau");
  await expect(page.getByText("Two-step sign-in is off.")).toBeVisible();
  await checkScreen(page);

  await signOut(page);
  await logIn(page, email);
  await expect(page).toHaveURL(/\/dev$/);
});

test("an organisation owner turns on two-step sign-in and needs a code at the next login", async ({
  page,
  request,
}) => {
  const email = uniqueEmail("org");

  await page.goto("/signup");
  await page.getByRole("radio", { name: /^For an organisation/ }).check();
  await page.getByLabel("Your name").fill("Achieng Otieno");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Organisation name").fill("Lakeside Water Services");
  await page.getByLabel("Type of organisation").selectOption("county_govt");
  await page.getByRole("checkbox", { name: /I accept the terms of service/ }).check();
  await checkScreen(page);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/signup\/check-email$/);

  await page.goto(pathOf(await waitForSignInLink(request, email)));
  await expect(page).toHaveURL(/\/org$/);
  const turnOn = page.getByRole("link", { name: "Turn on two-step sign-in" });
  await expect(turnOn).toHaveAttribute("data-primary", "");
  await checkScreen(page);

  await turnOn.click();
  await expect(page).toHaveURL(/\/settings\/security$/);
  await expect(page.getByRole("list", { name: "Setup steps" }).locator("[aria-current=step]")).toHaveCount(1);
  await checkScreen(page);

  await page.getByRole("button", { name: "Turn on two-step sign-in" }).click();
  const key = (await page.getByTestId("totp-key").innerText()).replace(/\s+/g, "");
  expect(key).toMatch(/^[A-Z2-7]{16,}$/);
  await expect(page.getByRole("img", { name: /QR code/ })).toBeVisible();
  await checkScreen(page);

  await page.getByLabel("Code from your app").fill(totp(key));
  await page.getByRole("button", { name: "Confirm code" }).click();
  await expect(page.getByTestId("recovery-codes").getByRole("listitem")).toHaveCount(10);
  await checkScreen(page);

  await page.getByRole("button", { name: "I have saved my codes" }).click();
  await expect(page).toHaveURL(/\/org$/);
  await expect(page.getByText("Two-step sign-in is on.")).toBeVisible();

  await signOut(page);
  await logIn(page, email);
  await expect(page).toHaveURL(/\/auth\/mfa$/);
  await checkScreen(page);

  // The enrolment code's window cannot be replayed, so use the next 30-second window (the server allows +1).
  await page.getByLabel("6-digit code").fill(totp(key, { offset: 1 }));
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/org$/);
  await expect(page.getByText("Two-step sign-in is on.")).toBeVisible();
});
