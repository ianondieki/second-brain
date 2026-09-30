/**
 * The recorded walkthrough of the demo story (P16-W; REQ-FND-02, REQ-UX-01..04): one person at a time signs in
 * through the real login and two-step screens and walks the seeded story at a watchable pace, while Playwright
 * records a 1280 x 720 video of the desktop part and saves the screenshots the README links to.
 *
 * RUN IT ON A FRESH DEMO: it changes the demo's data (Amina upgrades to Pro, a draft idea is started, Telco A accepts
 * an Evaluation NDA and starts a review, a moderation case is decided, the clock moves a day). Reset between runs.
 *
 *   make demo-reset
 *   make demo-walkthrough              (runs `python infra/demo/demo.py e2e-env` first; DEMO_PY=python3 on Linux/macOS)
 *
 * Without make (Windows PowerShell, or any shell), from the repository folder:
 *
 *   python infra/demo/demo.py reset --yes
 *   python infra/demo/demo.py e2e-env
 *   cd frontend && npx playwright test -c demo/walkthrough.config.ts
 *
 * The config reads frontend/.env.e2e (E2E_BASE_URL, E2E_MAILPIT_URL, E2E_DATABASE_OWNER_URL). The time step moves the
 * demo clock one day and sends the reminders (`demo.py clock --days 1`, `demo.py reminders`) only when
 * WALKTHROUGH_RUN_DEMO_CMDS=1 (make demo-walkthrough sets it; PowerShell: `$env:WALKTHROUGH_RUN_DEMO_CMDS = "1"`);
 * otherwise it logs a note and Mailpit shows the reminders the seed day sent. WALKTHROUGH_PAUSE_MS sets the pause
 * between steps (default 1200). WALKTHROUGH_DEMO_REPO names the checkout that started the demo (its infra/demo/.env), when
 * it is not this one (a second worktree). Output: docs/demo/video/ (gitignored) and docs/demo/screenshots/ (committed).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff, signInThroughScreens } from "../e2e/support/moderation-scene";
import { demoTotpSecret } from "../e2e/support/totp";
import { ownerSql } from "../e2e/support/tracker-scene";

const REPO = join(__dirname, "..", "..");
const SHOTS = join(REPO, "docs", "demo", "screenshots");
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const PAUSE_MS = Number(process.env.WALKTHROUGH_PAUSE_MS ?? 1200);
const SLOW = { timeout: 60_000 };

const DESKTOP = { width: 1440, height: 900 };

// The seeded story (backend/src/bridge/seed/demo/data.py, queues.py).
const IDEA = "Repayment nudges for SACCO members";
const SACCO_B = "SACCO B (fixture)";
const BRIAN_IDEA = "Cashless market-fee collection for counties";

/** A demo login: the public demo password and a TOTP key derived from the address (dev and test only). */
function demoLogin(email: string, name: string): DemoStaff {
  return new DemoStaff(email, name, demoTotpSecret(email));
}

const AMINA = demoLogin("amina@developers.example", "Amina Wanjiru");

/** A short pause, so the video can be followed. */
async function pause(page: Page, times = 1) {
  await page.waitForTimeout(PAUSE_MS * times);
}

/** A viewport-only JPEG into docs/demo/screenshots/ (the README links these names). */
async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await expect(page).toHaveTitle(/\S/);
  await page.screenshot({ path: join(SHOTS, `${name}.jpg`), type: "jpeg", quality: 80, scale: "css" });
}

/** Scrolls smoothly (for the video) to `top` px, and waits until the page is there (or jumps there after 5 s). */
async function scrollTo(page: Page, top: number) {
  const target = await page.evaluate((y) => {
    const end = Math.min(y, document.documentElement.scrollHeight - window.innerHeight);
    window.scrollTo({ top: end, behavior: "smooth" });
    return Math.max(0, end);
  }, top);
  await page
    .waitForFunction((y) => Math.abs(window.scrollY - y) < 2, target, { timeout: 5_000 })
    .catch(() => page.evaluate((y) => window.scrollTo({ top: y, behavior: "instant" }), target));
}

/** Brings a part of the page to the top of the viewport, a little below the edge, and lets it settle. */
async function show(page: Page, target: Locator, times = 1) {
  const box = await target.first().evaluate((node) => node.getBoundingClientRect().top + window.scrollY);
  await scrollTo(page, Math.max(0, box - 32));
  await pause(page, times);
}

async function toTop(page: Page) {
  await scrollTo(page, 0);
  await pause(page, 0.5);
}

/** Signs in through the login and two-step screens and waits for the person's home. */
async function signIn(page: Page, who: DemoStaff, home: RegExp) {
  await signInThroughScreens(page, who, DEMO_PASSWORD);
  await expect(page).toHaveURL(home, SLOW);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await pause(page);
}

/** Signs out from the account menu (back on the login page). */
async function signOut(page: Page) {
  await toTop(page);
  await page.getByRole("button", { name: "Account" }).click();
  await pause(page, 0.5);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login(\?.*)?$/, SLOW);
  await pause(page, 0.5);
}

function nav(page: Page, name: string): Locator {
  return page.getByRole("navigation", { name });
}

test.beforeAll(() => {
  // The story needs the demo seed as `make demo-reset` leaves it (the owner reads it; nothing is written here).
  expect(process.env.E2E_DATABASE_OWNER_URL, "run python infra/demo/demo.py e2e-env first").toBeTruthy();
  const state = ownerSql(
    "SELECT e.state FROM engagements e JOIN proposals p ON p.id = e.proposal_id JOIN organizations o ON o.id = e.org_id" +
      " WHERE p.title = :'title' AND o.legal_name = 'Telco A (fixture)';",
    { title: BRIAN_IDEA },
  );
  expect(state, "Brian's pitch to Telco A is still Submitted: run make demo-reset before the walkthrough").toBe("SUBMITTED");
});

test("the demo story, from a fresh make demo-reset", async ({ page, browser }) => {
  let certId = "";

  await test.step("Developer: Amina's Home, Discover and My ideas", async () => {
    await signIn(page, AMINA, /\/dev$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Welcome, Amina Wanjiru");
    const needsYou = page.getByRole("region", { name: "Needs you" });
    await expect(needsYou).toContainText(IDEA);
    await expect(needsYou).toContainText("Your turn");
    const recommended = page.getByRole("region", { name: "Recommended for you" });
    await expect(recommended.locator("article").first()).toBeVisible();
    await shot(page, "01-dev-home-1440");
    await show(page, recommended);
    await recommended.getByText("Why this, and why not").first().click();
    await pause(page, 1.5);

    await nav(page, "Developer").getByRole("link", { name: "Discover" }).click();
    await expect(page).toHaveURL(/\/dev\/discover$/, SLOW);
    const trending = page.getByRole("region", { name: "Trending problems" });
    await expect(trending.locator("article").first()).toBeVisible();
    await pause(page);
    await shot(page, "02-discover-trending-1440");
    await trending.getByText("More about this problem").first().click();
    await pause(page, 1.5);
    await nav(page, "Lists").getByRole("link", { name: "Projects" }).click();
    await expect(page.getByRole("region", { name: "Trending projects" }).locator("article").first()).toBeVisible(SLOW);
    await pause(page, 1.5);
    await nav(page, "Lists").getByRole("link", { name: "Opportunity gap" }).click();
    await expect(page.getByRole("region", { name: "Opportunity gap" }).locator("article").first()).toBeVisible(SLOW);
    await pause(page, 1.5);

    await nav(page, "Developer").getByRole("link", { name: "My ideas" }).click();
    await expect(page).toHaveURL(/\/dev\/ideas$/, SLOW);
    await pause(page);
  });

  await test.step("Developer: the idea's certificate and who has seen it", async () => {
    await page.getByRole("main").getByRole("link", { name: IDEA, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(IDEA, SLOW);
    await pause(page);
    const seen = page.getByRole("region", { name: "Who has seen this" });
    await expect(seen).toContainText(SACCO_B);
    await show(page, seen, 1.5);
    const certificate = page.getByRole("region", { name: "Certificate" });
    const verifyLink = certificate.getByRole("link", { name: "Check it on the verify page" });
    certId = ((await verifyLink.getAttribute("href")) ?? "").replace(/^\/verify\//, "");
    expect(certId, "the idea's certificate id").toMatch(/^[0-9A-Z]{8,24}$/);
    await show(page, certificate);
    await shot(page, "03-idea-certificate-1440");
  });

  await test.step("Public: the certificate on /verify, signed out", async () => {
    const context = await browser.newContext({ baseURL: BASE_URL, viewport: DESKTOP });
    try {
      const visitor = await context.newPage();
      await visitor.goto("/verify");
      await visitor.locator('form[data-hydrated="true"]').first().waitFor(SLOW);
      await visitor.getByLabel("Certificate ID").fill(certId);
      await visitor.getByRole("button", { name: "Check certificate" }).click();
      await expect(visitor).toHaveURL(new RegExp(`/verify/${certId}$`), SLOW);
      await expect(visitor.getByRole("heading", { level: 1 })).toHaveText(`Certificate ${certId}`);
      await expect(visitor.getByTestId("verify-status")).toHaveText(/^(Timestamped|Timestamp pending)$/);
      await expect(visitor.getByText(IDEA)).toHaveCount(0); // no title or name on the public record
      await shot(visitor, "04-verify-public-1440");
    } finally {
      await context.close();
    }
  });

  await test.step("Developer: a new proposal and the submission assistant (not published)", async () => {
    await toTop(page);
    await nav(page, "Developer").getByRole("link", { name: "Home" }).click();
    await expect(page).toHaveURL(/\/dev$/, SLOW);
    await pause(page, 0.5);
    await page.locator("[data-primary]").click(); // + New proposal
    await expect(page).toHaveURL(/\/dev\/ideas\/new$/, SLOW);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("New idea");
    await page.getByLabel("Title", { exact: true }).fill("Harvest-day payouts for dairy co-op farmers");
    await expect(page).toHaveURL(/\/dev\/ideas\/[0-9a-f-]{36}\/edit/, SLOW); // the draft is saved as you type
    await page
      .getByLabel("Summary")
      .fill("Farmers see what the co-op owes them for each delivery and get paid by M-Pesa on the agreed day.");
    await expect(page.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible(SLOW);
    await pause(page);
    const assistant = page.getByRole("region", { name: "Writing assistant" });
    await show(page, assistant);
    await assistant.getByRole("button", { name: "Suggest a clearer teaser" }).click();
    const consent = page.getByRole("dialog", { name: "Turn on the writing assistant?" });
    await expect(consent).toBeVisible(SLOW);
    await pause(page, 1.5);
    await consent.getByRole("button", { name: "Turn on and ask" }).click();
    const panel = page.locator("#assistant-panel");
    // Without an LLM provider the answer is the labelled demo fallback; with one, a labelled suggestion.
    await expect(panel.locator("[data-chip]").first()).toBeVisible(SLOW);
    await show(page, panel, 1.5);
    await shot(page, "05-editor-assistant-1440");
  });

  await test.step("Developer: the SACCO B tracker", async () => {
    await toTop(page);
    await nav(page, "Developer").getByRole("link", { name: "Engagements" }).click();
    await expect(page).toHaveURL(/\/dev\/engagements$/, SLOW);
    await pause(page);
    await page.getByRole("region", { name: IDEA }).getByRole("link", { name: SACCO_B }).click();
    await expect(page).toHaveURL(/\/dev\/engagements\/[0-9a-f-]{36}$/, SLOW);
    await expect(page.locator("[data-whose-turn]")).toContainText("Awaiting: you");
    await expect(page.getByRole("list", { name: "Stages" }).locator("[aria-current='step']")).toContainText("Agreement");
    await pause(page);
    await shot(page, "06-dev-tracker-1440");
    await show(page, page.getByRole("region", { name: "Agreement" }), 2);
    await show(page, page.getByRole("region", { name: "Signatures" }));
    await toTop(page);
    await nav(page, "Engagement sections").getByRole("link", { name: "History" }).click();
    await expect(page).toHaveURL(/\?tab=history$/, SLOW);
    await expect(page.locator("[data-event]").first()).toBeVisible();
    await pause(page, 2);
  });

  await test.step("Developer: Plan & billing, the simulated M-Pesa upgrade", async () => {
    await toTop(page);
    await page.getByRole("button", { name: "Account" }).click();
    await pause(page, 0.5);
    await page.getByRole("link", { name: "Plan & billing" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Plan & billing" })).toBeVisible(SLOW);
    // Amina has three published ideas (one held for review), the Free plan's cap: a fourth needs Pro.
    await expect(page.getByText("You are on the Free plan.")).toBeVisible();
    await expect(page.locator("[data-plan='dev_free']")).toContainText("3 published ideas at a time");
    await pause(page, 1.5);
    await page.locator("[data-primary]").click(); // Upgrade to Pro (monthly)
    await expect(page.getByRole("heading", { level: 1, name: "Upgrade to Pro (monthly)" })).toBeVisible(SLOW);
    await expect(page.getByRole("radio", { name: "The payment is confirmed" })).toBeChecked();
    await pause(page, 1.5);
    await page.getByRole("button", { name: "Start the simulated payment" }).click();
    await expect(page.getByRole("heading", { name: "Payment confirmed" })).toBeVisible(SLOW);
    await expect(page.getByText("You are now on Pro (monthly).")).toBeVisible();
    await pause(page);
    await shot(page, "07-billing-checkout-1440");
    await signOut(page);
  });

});
