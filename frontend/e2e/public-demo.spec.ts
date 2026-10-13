import { expect, test, type Page } from "@playwright/test";

import { checkScreen } from "./support/screen";

// AT-PD-6 (REQ-FND-04; docs/platform/tasks/P28.md, track PD): the public demo as a visitor sees it. /login offers the
// API's personas (seven in the public seed), one press signs in and lands on that persona's Home, a banner on every
// page says the data is fictional and resets nightly and can be dismissed for the session, the locked controls say so,
// and nothing is indexed. Strict axe on /login and /org at both projects (360 px and 1440 px).
//
// Only against a stack started with PUBLIC_DEMO=true (web and API): the normal suite's stack runs without the mode, so
// this file is skipped unless E2E_PUBLIC_DEMO=1. Nothing here reads /api/openapi.json (404 in the public demo).

const PERSONAS = [
  "Amina Wanjiru",
  "Brian Otieno",
  "Grace Mwangi",
  "Peter Kamau",
  "Rita Njeri",
  "Hassan Abdi",
  "Staff Moderator (demo)",
];
const BANNER =
  "Public demo: every name and organisation here is fictional, and the data resets every night at 03:00 EAT. Please don't enter real personal information.";
// Under a setting whose state still holds (the persona's two-step sign-in is on), the line says changing it is off.
const CHANGE_LOCKED = "Changing this is switched off in the public demo.";

test.skip(process.env.E2E_PUBLIC_DEMO !== "1", "needs a stack started with PUBLIC_DEMO=true: set E2E_PUBLIC_DEMO=1");

const personas = (page: Page) => page.getByRole("list", { name: "People you can sign in as" });

/** Signs in as a persona from /login's picker and waits for that persona's Home. */
async function signInAs(page: Page, name: string, home: RegExp) {
  await page.goto("/login");
  await personas(page).getByRole("button", { name: `Continue as ${name}` }).click();
  await expect(page).toHaveURL(home);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
}

test("/login offers the seven personas; pressing Grace lands on /org; strict axe on both", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1, name: "Try the demo as…" })).toBeVisible();
  const rows = personas(page).getByRole("listitem");
  await expect(rows).toHaveCount(7);
  await expect(personas(page).getByRole("heading", { level: 2 })).toHaveText(PERSONAS);
  for (const name of PERSONAS) {
    await expect(personas(page).getByRole("button", { name: `Continue as ${name}` })).toBeVisible();
  }
  // Personas only: password sign-in, the emailed link and sign-up are switched off in the demo.
  await expect(page.locator("main form")).toHaveCount(0);
  await expect(page.getByLabel("Email address")).toHaveCount(0);
  await expect(page.locator('a[href="/signup"]')).toHaveCount(0);
  await checkScreen(page, { strict: true });

  await personas(page).getByRole("button", { name: "Continue as Grace Mwangi" }).click();
  await expect(page).toHaveURL(/\/org(\?.*)?$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByRole("region", { name: "Public demo notice" })).toBeVisible();
  await checkScreen(page, { strict: true });
});

test("the banner is on every page, never over the content, and stays dismissed for the session", async ({ page, browser }) => {
  for (const path of ["/", "/login", "/explore", "/help"]) {
    await page.goto(path);
    const banner = page.getByRole("region", { name: "Public demo notice" });
    await expect(banner, path).toBeVisible();
    await expect(banner.locator("p"), path).toHaveText(BANNER);
    // In the flow at the very top: the top bar starts where the banner ends (nothing covers it or is covered).
    const strip = (await banner.boundingBox())!;
    const bar = (await page.locator("[data-top-bar]").first().boundingBox())!;
    expect(strip.y, path).toBe(0);
    expect(bar.y, path).toBeGreaterThanOrEqual(strip.y + strip.height - 0.5);
  }

  const banner = page.getByRole("region", { name: "Public demo notice" });
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await banner.getByRole("button", { name: "Hide the demo notice" }).click();
  await expect(banner).toBeHidden();
  await expect(page.locator("#main")).toBeFocused();
  // Focus moves without scrolling: at 360 px #main starts below the top bar, and a plain focus() scrolled the bar out
  // of view (ux review of P28-PD, MAJOR 2). The page stays at the top with the bar in view, in every project.
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect((await page.locator("[data-top-bar]").first().boundingBox())!.y).toBe(0);
  await page.reload();
  await expect(banner).toBeHidden();
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Public demo notice" })).toBeHidden();

  // A new browser session sees it again.
  const fresh = await browser.newContext();
  try {
    const other = await fresh.newPage();
    await other.goto("/");
    await expect(other.getByRole("region", { name: "Public demo notice" })).toBeVisible();
  } finally {
    await fresh.close();
  }
});

test("Settings › Security says changing each is off, in place of two-step sign-in and the password", async ({ page }) => {
  await signInAs(page, "Grace Mwangi", /\/org(\?.*)?$/);
  await page.goto("/settings/security");
  const locked = page.locator("[data-security-locked]");
  await expect(locked.getByRole("heading", { name: "Two-step sign-in" })).toBeVisible();
  await expect(locked.getByRole("heading", { name: "Password" })).toBeVisible();
  await expect(locked.locator("[data-demo-locked]")).toHaveText([CHANGE_LOCKED, CHANGE_LOCKED]);
  await expect(page.locator("main form")).toHaveCount(0);
  await checkScreen(page, { strict: true });
});

test("the user menu's sign-out reads \"Switch persona\" and returns to the picker", async ({ page }) => {
  await signInAs(page, "Amina Wanjiru", /\/dev(\?.*)?$/);
  await page.goto("/settings/security");
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("button", { name: "Switch persona" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(personas(page).getByRole("listitem")).toHaveCount(7);
});

test("nothing is indexed: robots.txt disallows every path and pages carry X-Robots-Tag", async ({ request }) => {
  const robots = await request.get("/robots.txt");
  expect(robots.status()).toBe(200);
  expect(await robots.text()).toBe("User-agent: *\nDisallow: /\n");
  for (const path of ["/", "/login", "/explore"]) {
    const response = await request.get(path);
    expect(response.headers()["x-robots-tag"], path).toBe("noindex, nofollow");
  }
});
