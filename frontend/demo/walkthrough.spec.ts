/**
 * The recorded walkthrough of the demo story (P16-W; REQ-FND-02, REQ-UX-01..04): one person at a time signs in
 * through the real login and two-step screens and walks the seeded story at a watchable pace, while Playwright
 * records a 1280 x 720 video of the desktop part and saves the screenshots the README links to.
 *
 * RUN IT ON A FRESH DEMO: it changes the demo's data (Amina upgrades to Pro, a draft idea is started and checked,
 * Telco A accepts an Evaluation NDA, posts a Problem Brief, starts a review and asks a question, a moderation case
 * and the Brief are decided, Brian answers and pauses his engagement and starts a proposal from the Brief, the clock
 * moves a day). Reset between runs.
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
 *
 * As a CI check (P16-E3, pr.yml's demo-story job, on the dev compose stack with the demo seed, not `make demo`):
 * walkthrough.config.ts turns the video off and sends the screenshots to test-results/walkthrough/screenshots/
 * (WALKTHROUGH_SHOTS_DIR). The job sets WALKTHROUGH_RUN_DEMO_CMDS=1 and WALKTHROUGH_COMPOSE to the docker compose
 * arguments of its stack (`--env-file infra/.env -f infra/docker-compose.dev.yml`, from the repository folder): the
 * time step then runs the two commands demo.py runs, in the same containers of that stack (`docker compose <args>
 * exec -T api python -m bridge.demo clock --days 1`, `… exec -T worker python -m bridge.reminders run --now`).
 * Every assertion is the same in CI; under the egress lock the certificate reads "Timestamp pending", which the
 * /verify step accepts in either mode (as e2e/verify.spec.ts does).
 */
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Browser, type BrowserContext, type Locator, type Page } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff, signInThroughScreens } from "../e2e/support/moderation-scene";
import { demoTotpSecret } from "../e2e/support/totp";
import { ownerSql } from "../e2e/support/tracker-scene";

const REPO = join(__dirname, "..", "..");
// The config sets it: docs/demo/screenshots/ (committed) locally, test-results/walkthrough/screenshots/ in CI.
const SHOTS = process.env.WALKTHROUGH_SHOTS_DIR ?? join(REPO, "docs", "demo", "screenshots");
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const MAILPIT = (process.env.E2E_MAILPIT_URL ?? "http://localhost:8025").replace(/\/$/, "");
const PAUSE_MS = Number(process.env.WALKTHROUGH_PAUSE_MS ?? 1200);
const RUN_DEMO_CMDS = process.env.WALKTHROUGH_RUN_DEMO_CMDS === "1";
/** docker compose arguments naming the stack when it is not `make demo`'s (CI's dev stack); empty: demo.py. */
const COMPOSE_ARGS = (process.env.WALKTHROUGH_COMPOSE ?? "").split(/\s+/).filter(Boolean);
const SLOW = { timeout: 60_000 };

const DESKTOP = { width: 1440, height: 900 };
const PHONE = { width: 375, height: 812 };

// The seeded story (backend/src/bridge/seed/demo/data.py, queues.py).
const IDEA = "Repayment nudges for SACCO members";
const SACCO_B = "SACCO B (fixture)";
const BRIAN_IDEA = "Cashless market-fee collection for counties";
const TELCO_A = "Telco A (fixture)";
// Telco A's Problem Brief (REQ-DIR-05), posted in the story and approved by the moderator.
const BRIEF_TITLE = "Tower sites go dark when the diesel runs out";
const QUESTION = "Which counties ran the pilot, and for how long?";

/** A demo login: the public demo password and a TOTP key derived from the address (dev and test only). */
function demoLogin(email: string, name: string): DemoStaff {
  return new DemoStaff(email, name, demoTotpSecret(email));
}

const AMINA = demoLogin("amina@developers.example", "Amina Wanjiru");
const BRIAN = demoLogin("brian@developers.example", "Brian Otieno");
const TELCO_REVIEWER = demoLogin("reviewer@telco-a.example", "Telco A reviewer");
const TELCO_OWNER = demoLogin("owner@telco-a.example", "Telco A owner");
const STAFF_ADMIN = demoLogin("admin@staff.example", "Staff Admin (demo)");
const STAFF_MODERATOR = demoLogin("moderator@staff.example", "Staff Moderator (demo)");

/** A short pause, so the video can be followed. */
async function pause(page: Page, times = 1) {
  await page.waitForTimeout(PAUSE_MS * times);
}

/** A viewport-only JPEG into docs/demo/screenshots/ (the README links these names; in CI a scratch folder). */
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

/** The in-container command demo.py runs for each of its time commands (infra/demo/demo.py cmd_clock, cmd_reminders). */
const IN_CONTAINER: Record<string, (args: string[]) => string[]> = {
  clock: (args) => ["api", "python", "-m", "bridge.demo", "clock", ...args],
  reminders: () => ["worker", "python", "-m", "bridge.reminders", "run", "--now"],
};

/**
 * One of the demo launcher's commands (the same as make demo-clock / make demo-reminders), from the repository; with
 * WALKTHROUGH_COMPOSE, the same command in the same container of that compose stack (CI's dev stack).
 */
function demoCommand(args: string[]): void {
  const checkout = process.env.WALKTHROUGH_DEMO_REPO ?? REPO;
  const options = { cwd: checkout, stdio: "inherit", timeout: 180_000 } as const;
  if (COMPOSE_ARGS.length) {
    const [name, ...rest] = args;
    const command = ["compose", ...COMPOSE_ARGS, "exec", "-T", ...IN_CONTAINER[name](rest)];
    console.log(`walkthrough: docker ${command.join(" ")}`);
    execFileSync("docker", command, options);
    return;
  }
  const python = process.env.DEMO_PY ?? (process.platform === "win32" ? "python" : "python3");
  console.log(`walkthrough: ${python} infra/demo/demo.py ${args.join(" ")}`);
  execFileSync(python, ["infra/demo/demo.py", ...args], options);
}

/** How many developer nudges have reached `to` (Mailpit's API). */
async function nudgesTo(page: Page, to: string): Promise<number> {
  const response = await page.request.get(`${MAILPIT}/api/v1/messages?limit=500`);
  expect(response.ok(), `Mailpit at ${MAILPIT}`).toBeTruthy();
  const { messages = [] } = (await response.json()) as {
    messages?: Array<{ Subject?: string; To?: Array<{ Address: string }> }>;
  };
  return messages.filter(
    (m) => /^Your day on Wazo/.test(m.Subject ?? "") && m.To?.some((r) => r.Address.toLowerCase() === to),
  ).length;
}

/** A calendar day `days` from now in Nairobi ("2026-10-31"), as the date inputs take it. */
function nairobiDay(days: number): string {
  const at = new Date(Date.now() + days * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi", year: "numeric", month: "2-digit", day: "2-digit" }).format(at);
}

/** Opens one of the tracker's side-state sheets (REQ-ENG-10) by its button and waits for it. */
async function openSheet(page: Page, name: string): Promise<Locator> {
  await page.locator("[data-actions]").getByRole("button", { name, exact: true }).click();
  const sheet = page.locator("dialog[open][data-side-sheet]");
  await expect(sheet).toBeVisible(SLOW);
  await expect(sheet.getByRole("heading", { level: 2 })).toHaveText(name);
  await pause(page);
  return sheet;
}

/** Sends a sheet and waits for the tracker to say it is up to date (the sheet closes). */
async function sendSheet(page: Page, submit: string) {
  await page.locator("dialog[open][data-side-sheet]").getByRole("button", { name: submit, exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Done. The tracker is up to date." })).toBeVisible(SLOW);
  await expect(page.locator("dialog[open]")).toHaveCount(0);
}

async function phoneContext(browser: Browser): Promise<BrowserContext> {
  return browser.newContext({ baseURL: BASE_URL, viewport: PHONE, isMobile: true, hasTouch: true, deviceScaleFactor: 1 });
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
  let saccoTracker = "";

  await test.step("Developer: Amina's first login, the tour, then Home, Discover and My ideas", async () => {
    await signIn(page, AMINA, /\/dev$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Welcome, Amina Wanjiru");
    // The first-login tour (D-52): three steps, never a modal; a fresh browser has not seen it.
    const tour = page.getByRole("dialog", { name: "This is your home" });
    await expect(tour).toBeVisible();
    await pause(page);
    await shot(page, "00-first-login-tour-1440");
    await tour.getByRole("button", { name: "Next" }).click();
    await pause(page);
    await page.getByRole("dialog").getByRole("button", { name: "Next" }).click();
    await pause(page);
    await page.getByRole("dialog").getByRole("button", { name: "Done" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await pause(page, 0.5);
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
    await nav(page, "Lists").getByRole("link", { name: "Gap" }).click();
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

    // The teaser checks (REQ-PROP-04, REQ-REPO-01): overlap with other published ideas, in words, never a score; and
    // what the teaser gives away. Without an AI provider the second is the quick check, labelled "Demo fallback".
    const checks = page.getByRole("region", { name: "Teaser checks" });
    await show(page, checks);
    await checks.getByRole("button", { name: "Check overlap" }).click();
    await expect(page.locator("[data-check='overlap']")).toHaveText(/^No (overlap|other published ideas)/, SLOW);
    await pause(page, 1.5);
    await checks.getByRole("button", { name: "Check what it gives away" }).click();
    await expect(page.locator("[data-check='disclosure']")).toContainText(/\S/, SLOW);
    await show(page, checks, 1.5);
    await shot(page, "05b-editor-checks-1440");
  });

  await test.step("Developer: the SACCO B tracker", async () => {
    await toTop(page);
    await nav(page, "Developer").getByRole("link", { name: "Engagements" }).click();
    await expect(page).toHaveURL(/\/dev\/engagements$/, SLOW);
    await pause(page);
    await page.getByRole("region", { name: IDEA }).getByRole("link", { name: SACCO_B }).click();
    await expect(page).toHaveURL(/\/dev\/engagements\/[0-9a-f-]{36}$/, SLOW);
    saccoTracker = new URL(page.url()).pathname;
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

  await test.step("Organisation: Telco A's reviewer opens Brian's proposal under the Evaluation NDA", async () => {
    await signIn(page, TELCO_REVIEWER, /\/org(\/inbox)?$/);
    await nav(page, "Organisation").getByRole("link", { name: "Inbox" }).click();
    await expect(page).toHaveURL(/\/org\/inbox$/, SLOW);
    await pause(page);
    await page.getByRole("main").getByRole("link", { name: BRIAN_IDEA }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(BRIAN_IDEA, SLOW);
    await pause(page);
    const full = page.getByRole("region", { name: "Full proposal" });
    await expect(page.locator("[data-primary]")).toHaveText("Accept and view");
    await show(page, full);
    await shot(page, "08-org-inbox-nda-1440");
    await page.getByRole("button", { name: "Accept and view" }).click();
    await expect(page).toHaveURL(/\?view=full$/, SLOW);
    const frame = page.frameLocator("[data-tier2-frame]");
    await expect(frame.getByRole("heading", { level: 1 })).toHaveText(BRIAN_IDEA, SLOW);
    await show(page, page.locator("[data-tier2-frame]"), 2);
    await shot(page, "09-org-full-proposal-1440");

    // Problems (REQ-DIR-05): the reviewer posts a Problem Brief; staff read it before developers see it.
    await toTop(page);
    await nav(page, "Organisation").getByRole("link", { name: "Problems" }).click();
    await expect(page).toHaveURL(/\/org\/problems$/, SLOW);
    await expect(page.locator("[data-primary]")).toHaveText("Post a Brief");
    await pause(page);
    await page.locator("[data-primary]").click();
    await expect(page).toHaveURL(/\/org\/problems\/new$/, SLOW);
    await page.locator('main [data-hydrated="true"]').first().waitFor(SLOW);
    await page.getByLabel("Title").fill(BRIEF_TITLE);
    await page
      .getByLabel("Problem statement")
      .fill(
        "Off-grid tower sites run on diesel generators that are refilled on a fixed schedule. When a delivery is late the" +
          " site goes dark for hours and nobody knows until subscribers complain. We want to know before the tank is empty.",
      );
    await page.getByLabel("Who is affected (optional)").fill("Subscribers served by off-grid tower sites");
    await page.getByLabel("Niche").selectOption({ label: "Networks & Telecommunications" });
    await page.getByLabel("County").selectOption("KE-30");
    await page.getByRole("group", { name: "Budget band" }).getByRole("radio").first().check();
    await page.getByLabel(/Proposals wanted by/).fill(nairobiDay(30));
    await pause(page, 1.5);
    await page.getByRole("button", { name: "Post the Brief" }).click();
    await expect(page).toHaveURL(/\/org\/problems(\?posted=1)?$/, SLOW); // the note takes focus, then the flag leaves the URL
    await expect(page.locator("[data-brief]").first()).toContainText(BRIEF_TITLE);
    await expect(page.locator("[data-brief]").first().locator("[data-chip]")).toHaveText("In review");
    await pause(page);
    await shot(page, "09b-org-brief-posted-1440");
    await signOut(page);
  });

  await test.step("Organisation: Telco A's owner, the scout's match, its settings and the first step", async () => {
    await signIn(page, TELCO_OWNER, /\/org(\/inbox)?$/);
    await nav(page, "Organisation").getByRole("link", { name: "Inbox" }).click();
    await expect(page).toHaveURL(/\/org\/inbox$/, SLOW);
    await nav(page, "Inbox sections").getByRole("link", { name: "Scout matches" }).click();
    await expect(page).toHaveURL(/\/org\/inbox\?tab=matches$/, SLOW);
    const matches = page.getByRole("list", { name: /^Scout matches for / });
    await expect(matches.locator("article").first()).toContainText("Why this matches");
    await pause(page);
    await shot(page, "10-org-scout-matches-1440");
    await matches.locator("article").first().getByRole("heading").getByRole("link").click();
    await expect(page.getByRole("region", { name: "Why this matches" })).toBeVisible(SLOW);
    await pause(page, 2);
    await page.getByRole("link", { name: "Back to scout matches" }).click();
    await expect(page).toHaveURL(/\/org\/inbox\?tab=matches$/, SLOW);
    await page.getByRole("link", { name: /^Change the scout/ }).first().click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Change your Scout Agent", SLOW);
    await page.locator("form[data-scout-form][data-hydrated='true']").waitFor(SLOW);
    await pause(page);
    const preview = page.getByRole("button", { name: "Preview matches" });
    await show(page, preview);
    await preview.click(); // Preview only: the scout is not saved.
    const previewed = page.getByRole("region", { name: "Preview", exact: true });
    await expect(previewed.getByRole("list", { name: "Preview of matching proposals" })).toBeVisible(SLOW);
    await show(page, previewed, 2);

    await toTop(page);
    await nav(page, "Organisation").getByRole("link", { name: "Engagements" }).click();
    await expect(page).toHaveURL(/\/org\/engagements$/, SLOW);
    await pause(page);
    await page.getByRole("region", { name: "Needs us" }).getByRole("link", { name: BRIAN_IDEA }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(BRIAN_IDEA, SLOW);
    await expect(page.locator("[data-whose-turn]")).toContainText("Awaiting: you");
    await expect(page.locator("[data-primary]")).toHaveText("Start the review");
    await pause(page, 1.5);
    await page.locator("[data-actions]").getByRole("button", { name: "Start the review", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Done. The tracker is up to date." })).toBeVisible(SLOW);
    await expect(page.getByRole("list", { name: "Stages" })).toContainText("Now: Under review");
    await pause(page);
    await shot(page, "11-org-tracker-step-1440");

    // A question for Brian (REQ-ENG-10): the review waits for his answer, and the clock on it is his.
    const ask = await openSheet(page, "Request information");
    await ask.getByLabel("Your question").fill(QUESTION);
    await pause(page);
    await sendSheet(page, "Send the question");
    await expect(page.locator("[data-whose-turn]")).toContainText("Answer the question");
    await expect(page.locator("[data-whose-turn] [data-side='info']")).toContainText(QUESTION);
    await pause(page);
    await shot(page, "11b-org-tracker-question-1440");
    await signOut(page);
  });

  await test.step("Staff: Research and Claims (admin)", async () => {
    await signIn(page, STAFF_ADMIN, /\/admin\/research$/);
    await page.locator('form[data-hydrated="true"]').first().waitFor(SLOW);
    await page.getByLabel("Niche").selectOption({ label: "Health" });
    await pause(page);
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status").filter({ hasText: "The Health run has finished." })).toBeVisible({
      timeout: 90_000,
    });
    const waiting = page.getByRole("region", { name: "Waiting for review" });
    // With the fake LLM a run drafts no card (the demo fallback); with a provider, a card waits for review.
    const card = waiting.locator("[data-candidate]").first();
    if (await card.count()) {
      await card.getByRole("link").first().click();
      await expect(page.getByRole("heading", { name: "Named-organisation checklist" })).toBeVisible(SLOW);
      await page.getByLabel("I have worked through the checklist above for this card.").check();
      await pause(page);
      await page.getByRole("button", { name: "Approve and publish" }).click();
      await expect(page.locator('[data-decision="approve"]')).toBeVisible(SLOW);
      await pause(page);
      await nav(page, "Staff console").getByRole("link", { name: "Research" }).click();
    } else {
      console.log("walkthrough: the run drafted no card (demo fallback, no LLM provider): nothing to approve");
    }
    await show(page, page.getByRole("region", { name: "Recent runs" }));
    await toTop(page);
    await shot(page, "12-admin-research-1440");

    await nav(page, "Staff console").getByRole("link", { name: "Claims" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Claims" })).toBeVisible(SLOW);
    await pause(page);
    await page.locator("[data-claim]").first().getByRole("link").first().click();
    await expect(page.locator("[data-read-only]")).toBeVisible(SLOW);
    await pause(page, 2);
    await signOut(page);
  });

  await test.step("Staff: the moderator decides the oldest case", async () => {
    await signIn(page, STAFF_MODERATOR, /\/admin\/moderation$/);
    await expect(page.locator("[data-primary]")).toHaveText("Review the oldest case");
    await pause(page);
    await page.locator("[data-primary]").click();
    await expect(page).toHaveURL(/\/admin\/moderation\/cases\/[0-9a-f-]{36}$/, SLOW);
    await expect(page.locator("[data-primary]")).toHaveText("Approve");
    await page.locator('main [data-hydrated="true"]').first().waitFor(SLOW);
    await pause(page);
    await shot(page, "13-admin-moderation-1440");
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: /^Approved\./ })).toBeVisible(SLOW);
    await pause(page, 1.5);

    // Telco A's Brief waits in the same queue, hidden until approved; approving publishes it to developers.
    await nav(page, "Staff console").getByRole("link", { name: "Moderation" }).click();
    await expect(page).toHaveURL(/\/admin\/moderation$/, SLOW);
    const briefRow = page.locator("[data-case]").filter({ hasText: BRIEF_TITLE });
    await expect(briefRow).toContainText(`Brief by ${TELCO_A}`);
    await show(page, briefRow);
    await briefRow.getByRole("link", { name: BRIEF_TITLE }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(BRIEF_TITLE, SLOW);
    await page.locator('main [data-hydrated="true"]').first().waitFor(SLOW);
    await pause(page);
    await shot(page, "13b-admin-moderation-brief-1440");
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "Approved. The Brief is published to developers." }),
    ).toBeVisible(SLOW);
    await pause(page, 1.5);
    await signOut(page);
  });

  await test.step("Developer: Brian's bell, his answer, a pause, and Telco A's Brief on Discover", async () => {
    await signIn(page, BRIAN, /\/dev$/);
    // The bell (REQ-NOT-03): Telco A started the review and asked a question; both landed here.
    const bell = page.getByRole("banner").locator("[data-notification-bell]");
    await expect(bell.locator("[data-unread-badge]")).toHaveText(/^[1-9]\d*$/, SLOW);
    await pause(page);
    await bell.click();
    await expect(page).toHaveURL(/\/notifications$/, SLOW);
    const asked = page.locator("[data-notification]").filter({ hasText: `${TELCO_A} asked you a question` });
    await expect(asked.first()).toBeVisible(SLOW);
    await pause(page);
    await shot(page, "14b-dev-notifications-1440");
    await asked.first().getByRole("link").click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(BRIAN_IDEA, SLOW);
    await expect(page.locator("[data-whose-turn]")).toContainText("Awaiting: you");
    await expect(page.locator("[data-primary]")).toHaveText("Answer the question");
    await pause(page);
    const reply = await openSheet(page, "Answer the question");
    await expect(reply.locator("[data-question]")).toHaveText(QUESTION);
    await reply.getByLabel("Your answer").fill("Kisumu and Nakuru, for six weeks each, with the county revenue offices.");
    await pause(page);
    await sendSheet(page, "Send the answer");
    await expect(page.locator("[data-whose-turn]")).toContainText(`Awaiting: ${TELCO_A}`);
    await expect(page.getByRole("list", { name: "Stages" })).toContainText("Now: Under review");
    await pause(page);
    // A hold (REQ-ENG-10): either party may pause before the agreement; the deadline waits with it.
    const hold = await openSheet(page, "Pause this engagement");
    await hold.getByLabel("Reason").fill("Travelling for the county budget hearings");
    await hold.getByLabel("Resumes on").fill(nairobiDay(7));
    await expect(hold.locator("[data-resumes]")).toContainText("It resumes by itself on");
    await pause(page);
    await sendSheet(page, "Pause until then");
    await expect(page.locator("[data-whose-turn]")).toContainText("This engagement is on hold.");
    await pause(page);
    await shot(page, "14c-dev-tracker-on-hold-1440");
    await toTop(page);
    await nav(page, "Engagement sections").getByRole("link", { name: "History" }).click();
    await expect(page.locator("[data-event='pause'] [data-note='hold']")).toContainText("Travelling", SLOW);
    await pause(page, 2);

    // Discover › Briefs (REQ-DIR-05): Telco A's Brief, with its budget band and deadline, and a proposal from it.
    await toTop(page);
    await nav(page, "Developer").getByRole("link", { name: "Discover" }).click();
    await expect(page).toHaveURL(/\/dev\/discover$/, SLOW);
    await nav(page, "Lists").getByRole("link", { name: "Briefs" }).click();
    await expect(page).toHaveURL(/\/dev\/discover\?view=briefs$/, SLOW);
    const brief = page.locator("[data-brief]").filter({ hasText: BRIEF_TITLE });
    await expect(brief).toContainText(`Posted by ${TELCO_A}`, SLOW);
    await show(page, brief);
    await shot(page, "14d-discover-briefs-1440");
    await brief.getByRole("link", { name: "Start a proposal from this Brief" }).click();
    await expect(page).toHaveURL(/\/dev\/ideas\/[0-9a-f-]{36}\/edit/, SLOW);
    await expect(page.getByRole("main")).toContainText(BRIEF_TITLE);
    await pause(page, 2);
    await signOut(page);
  });

  await test.step("Time and email: a day later, the reminders in Mailpit", async () => {
    if (RUN_DEMO_CMDS) {
      const before = await nudgesTo(page, AMINA.email);
      demoCommand(["clock", "--days", "1"]);
      demoCommand(["reminders"]);
      await expect.poll(() => nudgesTo(page, AMINA.email), SLOW).toBeGreaterThan(before);
    } else {
      console.log(
        "walkthrough: WALKTHROUGH_RUN_DEMO_CMDS is not 1, so the clock and reminders commands were skipped;" +
          " Mailpit shows the reminders the demo sent on its first day",
      );
    }
    await page.goto(MAILPIT);
    const nudge = page.getByText(/Your day on Wazo/).first();
    await expect(nudge).toBeVisible(SLOW);
    await expect(page.getByText(/Telco A \(fixture\): (weekly )?progress digest/).first()).toBeVisible();
    await pause(page);
    await shot(page, "14-mailpit-reminders-1440");
    await nudge.click();
    await pause(page, 2.5);
    await page.goBack();
    await page.getByText(/Telco A \(fixture\): (weekly )?progress digest/).first().click();
    await pause(page, 2.5);
  });

  await test.step("Phone width: Amina's Home, tracker and the Briefs, Telco A's Inbox (375 x 812)", async () => {
    const amina = await phoneContext(browser);
    try {
      const phone = await amina.newPage();
      await signIn(phone, AMINA, /\/dev$/);
      await shot(phone, "15-dev-home-375");
      await phone.goto(saccoTracker);
      await expect(phone.locator("[data-whose-turn]")).toContainText("Awaiting: you");
      await shot(phone, "16-dev-tracker-375");
      await phone.goto("/dev/discover?view=briefs");
      await expect(phone.locator("[data-brief]").filter({ hasText: BRIEF_TITLE })).toBeVisible(SLOW);
      await shot(phone, "18-discover-briefs-375");
    } finally {
      await amina.close();
    }
    const telco = await phoneContext(browser);
    try {
      const phone = await telco.newPage();
      await signIn(phone, TELCO_OWNER, /\/org(\/inbox)?$/);
      await phone.goto("/org/inbox");
      await expect(phone.getByRole("main").getByRole("link", { name: BRIAN_IDEA })).toBeVisible(SLOW);
      await shot(phone, "17-org-inbox-375");
    } finally {
      await telco.close();
    }
  });
});
