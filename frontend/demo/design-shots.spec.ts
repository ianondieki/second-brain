/**
 * Screenshots of the real screens on the demo stack, light and dark, 1440 and 375 px, each with a strict axe pass
 * (every impact), the one-primary-action rule and the no-sideways-scroll rule (e2e/support/screen.ts), for the P18
 * quality loop. One sign-in per demo person; the session is reused across the shots. Writes
 * docs/demo/screenshots/p18/<name>-<theme>-<width>.jpg and test-results/design-shots/axe.json.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff } from "../e2e/support/moderation-scene";
import { settled } from "../e2e/support/screen";
import { demoTotpSecret, totp } from "../e2e/support/totp";

const REPO = join(__dirname, "..", "..");
const OUT = process.env.SHOTS_DIR ?? join(REPO, "docs", "demo", "screenshots", "p18");
const REPORT = join(__dirname, "..", "test-results", "design-shots", "axe.json");
const THEMES = (process.env.SHOT_THEMES ?? "light,dark").split(",") as Array<"light" | "dark">;
const WIDTHS = (process.env.SHOT_WIDTHS ?? "1440,375").split(",").map(Number);
const FILTER = process.env.SHOT_FILTER ? new RegExp(process.env.SHOT_FILTER) : null;

type Who = "none" | "pendingMfa" | "dev" | "devBrian" | "org" | "orgOwner" | "staff" | "moderator";
interface Shot {
  name: string;
  path: string;
  who: Who;
  /** Steps after the page loaded (open a tab, a dialog, type into a field); `false` skips the shot (its state cannot be reached on this stack). */
  prepare?: (page: Page) => Promise<void | false>;
  /** Selectors axe leaves out (a sandboxed frame it cannot run inside). */
  exclude?: string[];
  /** Let the first-login tour show (every other shot remembers it as done). */
  tour?: boolean;
  /** The viewport only, not the whole page: a modal dialog's backdrop covers the viewport. */
  viewportOnly?: boolean;
  /** A frame on the page whose own document is shot too (`<name>-frame-…`): the marked full proposal. */
  frame?: string;
}

const PEOPLE: Record<Exclude<Who, "none" | "pendingMfa">, { email: string; name: string }> = {
  dev: { email: "amina@developers.example", name: "Amina Wanjiru" },
  devBrian: { email: "brian@developers.example", name: "Brian Otieno" },
  org: { email: "reviewer@telco-a.example", name: "Telco A reviewer" },
  orgOwner: { email: "owner@telco-a.example", name: "Telco A owner" },
  staff: { email: "admin@staff.example", name: "Staff Admin (demo)" },
  moderator: { email: "moderator@staff.example", name: "Staff Moderator (demo)" },
};

/** Types a teaser and opens the writing assistant; it either asks for consent (a dialog) or answers. */
async function askAssistant(page: Page) {
  await page.getByLabel("Title", { exact: true }).fill("Shared solar chillers for dairy co-ops");
  await page.getByLabel("Summary").fill("Shared solar chillers booked by SMS, paid per litre, built with two Kiambu co-ops.");
  await page.getByRole("button", { name: "Suggest a clearer teaser" }).click();
  await Promise.race([
    page.getByRole("dialog").waitFor({ timeout: 60_000 }),
    page.locator("#assistant-panel").getByRole("button", { name: "Ask again" }).waitFor({ timeout: 60_000 }),
  ]);
}

const SHOTS: Shot[] = [
  { name: "landing", path: "/", who: "none" },
  { name: "home", path: "/dev", who: "dev" },
  { name: "tour", path: "/dev", who: "dev", tour: true, prepare: async (page) => {
      await page.getByRole("dialog").waitFor();
    } },
  { name: "tracker", path: "/dev/engagements", who: "dev", prepare: async (page) => {
      await page.locator("main").getByRole("heading", { level: 3 }).first().getByRole("link").click();
      await page.locator("[data-whose-turn]").waitFor();
    } },
  { name: "certificate", path: "/dev/ideas", who: "dev", prepare: async (page) => {
      await page.locator("main article").filter({ hasText: "Published" }).first().getByRole("link").first().click();
      await page.locator("[data-certificate]").waitFor();
    } },
  { name: "ideas", path: "/dev/ideas", who: "dev" },
  // "Who has seen this" with a view in it: Brian's proposal, opened by Telco A's reviewer.
  { name: "idea-views", path: "/dev/ideas", who: "devBrian", prepare: async (page) => {
      await page.locator("main article").filter({ hasText: "Cashless market-fee" }).first().getByRole("link").first().click();
      await page.locator("[data-view]").first().waitFor();
    } },
  { name: "org-home", path: "/org", who: "org" },
  { name: "org-inbox", path: "/org/inbox", who: "org" },
  { name: "org-matches", path: "/org/inbox?tab=matches", who: "org" },
  { name: "org-match", path: "/org/inbox?tab=matches", who: "org", prepare: async (page) => {
      await page.locator("[data-match]").first().getByRole("link").first().click();
      await page.waitForURL(/\/matches\//);
      await page.locator("[data-interest]").waitFor();
    } },
  { name: "org-scout", path: "/org/inbox/scouts/new", who: "orgOwner", prepare: async (page) => {
      await page.locator("form[data-scout-form][data-hydrated='true']").waitFor();
    } },
  { name: "discover", path: "/dev/discover", who: "dev" },
  { name: "discover-projects", path: "/dev/discover?view=projects", who: "dev" },
  { name: "discover-gap", path: "/dev/discover?view=gap", who: "dev" },
  { name: "discover-niches", path: "/dev/discover/niches", who: "dev" },
  { name: "problem", path: "/dev/discover", who: "dev", prepare: async (page) => {
      await page.locator("article[data-problem]").first().getByRole("heading", { level: 3 }).getByRole("link").click();
      await page.waitForURL(/\/problems\//);
      await page.getByRole("heading", { level: 1 }).waitFor();
    } },
  // A proposal from the Inbox: the teaser with the NDA step (or the accepted state), then the marked full proposal.
  { name: "org-proposal", path: "/org/inbox", who: "org", prepare: async (page) => {
      await page.locator("main article").first().getByRole("link").first().click();
      await page.locator("[data-tier2-state]").waitFor();
    } },
  // The NDA step as the owner (who has not accepted it for this proposal yet).
  { name: "org-nda", path: "/org/inbox", who: "orgOwner", prepare: async (page) => {
      await page.locator("main article").first().getByRole("link").first().click();
      await page.locator("[data-tier2-state]").waitFor();
    } },
  { name: "org-proposal-full", path: "/org/inbox", who: "org", prepare: async (page) => {
      await page.locator("main article").first().getByRole("link").first().click();
      await page.locator("[data-tier2-state]").waitFor();
      const accept = page.getByRole("button", { name: "Accept and view" });
      if (await accept.isVisible()) await accept.click();
      else await page.getByRole("link", { name: "View full proposal" }).click();
      await page.locator("[data-tier2-frame]").waitFor();
      await page.frameLocator("[data-tier2-frame]").locator(".mark").waitFor();
    }, frame: "[data-tier2-frame]" },
  { name: "editor-1", path: "/dev/ideas/new", who: "dev", prepare: async (page) => {
      await page.locator('form[data-hydrated="true"], [data-hydrated="true"]').first().waitFor().catch(() => undefined);
      await page.getByLabel("Title", { exact: true }).waitFor();
    } },
  { name: "editor-2", path: "/dev/ideas/new", who: "dev", prepare: async (page) => {
      await page.getByLabel("Title", { exact: true }).waitFor();
      await page.getByRole("button", { name: "Continue" }).click();
      await page.locator("ol [aria-current='step']").filter({ hasText: "Full details" }).waitFor();
    } },
  { name: "editor-3", path: "/dev/ideas/new", who: "dev", prepare: async (page) => {
      await page.getByLabel("Title", { exact: true }).waitFor();
      await page.getByRole("button", { name: "Continue" }).click();
      await page.locator("ol [aria-current='step']").filter({ hasText: "Full details" }).waitFor();
      await page.getByRole("button", { name: "Continue" }).click();
      await page.locator("ol [aria-current='step']").filter({ hasText: "Review and publish" }).waitFor();
    } },
  // The writing assistant's consent dialog (the API's wording, verbatim), then its answer on the demo stack.
  { name: "editor-consent", path: "/dev/ideas/new", who: "dev", viewportOnly: true, prepare: async (page) => {
      await askAssistant(page);
      if (!(await page.getByRole("dialog").isVisible())) {
        // Consent lasts the sign-in: turn the assistant off, then asking again shows the dialog.
        await page.getByRole("button", { name: "Turn off the assistant for this sign-in" }).click();
        await page.getByText("The writing assistant is off for this sign-in.").waitFor();
        await page.locator("#assistant-panel").getByRole("button", { name: "Turn on and ask" }).click();
        await page.getByRole("dialog").waitFor();
      }
    } },
  { name: "editor-assistant", path: "/dev/ideas/new", who: "dev", prepare: async (page) => {
      await askAssistant(page);
      if (await page.getByRole("dialog").isVisible()) await page.getByRole("dialog").getByRole("button", { name: "Turn on and ask" }).click();
      await page.locator("#assistant-panel").getByRole("button", { name: "Ask again" }).waitFor({ timeout: 60_000 });
    } },
  // The public trust page: the lookup, a timestamped record (reached from the owner's certificate), a miss, and a
  // file check that matches nothing.
  { name: "verify", path: "/verify", who: "none" },
  { name: "verify-record", path: "/dev/ideas", who: "dev", prepare: async (page) => {
      await page.locator("main article").filter({ hasText: "Published" }).first().getByRole("link").first().click();
      await page.locator("[data-certificate]").waitFor();
      await page.getByRole("link", { name: "Check it on the verify page" }).click();
      await page.locator('[data-testid="verify-status"]').waitFor();
    } },
  { name: "verify-notfound", path: "/verify/NOSUCHCERT01", who: "none" },
  { name: "verify-file", path: "/verify", who: "none", prepare: async (page) => {
      await page.locator('form[data-hydrated="true"]').first().waitFor();
      await page.getByLabel("Manifest file").setInputFiles({ name: "manifest.json", mimeType: "application/json", buffer: Buffer.from('{"not":"a registered manifest"}') });
      await page.getByRole("button", { name: "Check file" }).click();
      await page.locator('[data-testid="file-result"]').waitFor();
    } },
  { name: "billing", path: "/billing", who: "dev" },
  { name: "billing-org", path: "/billing", who: "orgOwner" },
  { name: "checkout", path: "/billing/upgrade?plan=dev_pro_yearly", who: "dev", prepare: async (page) => {
      await page.getByRole("button", { name: "Start the simulated payment" }).waitFor();
    } },
  // Waiting for the (cancelled) simulated payment: Amina's plan stays Free.
  { name: "checkout-waiting", path: "/billing/upgrade?plan=dev_pro_yearly", who: "dev", prepare: async (page) => {
      await page.getByRole("radio", { name: "The payment is cancelled" }).check();
      await page.getByRole("button", { name: "Start the simulated payment" }).click();
      await page.getByRole("heading", { name: "Waiting for the simulated payment" }).waitFor();
    } },
  // Payment confirmed, as Brian (whose plan may change): the other Pro plan when one is already his.
  { name: "checkout-success", path: "/billing/upgrade?plan=dev_pro_monthly", who: "devBrian", prepare: async (page) => {
      if (await page.locator("[data-empty-state]").isVisible()) await page.goto("/billing/upgrade?plan=dev_pro_yearly");
      await page.getByRole("button", { name: "Start the simulated payment" }).click();
      await page.getByRole("heading", { name: "Payment confirmed" }).waitFor({ timeout: 90_000 });
    } },
  { name: "admin", path: "/admin", who: "staff" },
  { name: "admin-research", path: "/admin/research", who: "staff" },
  // A card waiting for review; with none in the queue, a run (the fake agent) brings some.
  { name: "admin-research-candidate", path: "/admin/research", who: "staff", prepare: async (page) => {
      const link = page.locator('main a[href*="/admin/research/candidates/"]').first();
      if (!(await link.isVisible())) {
        // The page is rendered on the server: start a run, then reload until the drafted card is listed.
        await page.getByRole("button", { name: "Start run" }).click();
        await page.waitForTimeout(3_000);
        for (let round = 0; round < 12 && !(await link.isVisible()); round++) {
          await page.waitForTimeout(4_000);
          await page.reload({ waitUntil: "networkidle" });
        }
        if (!(await link.isVisible())) return false; // every saved excerpt is already a card: nothing to review
      }
      await link.click();
      await page.waitForURL(/\/admin\/research\/candidates\//);
    } },
  { name: "admin-moderation", path: "/admin/moderation", who: "moderator" },
  { name: "admin-moderation-case", path: "/admin/moderation", who: "moderator", prepare: async (page) => {
      await page.locator('main a[href*="/admin/moderation/cases/"]').first().click();
      await page.waitForURL(/\/admin\/moderation\/cases\//);
    } },
  { name: "admin-claims", path: "/admin/claims", who: "staff" },
  { name: "admin-claim", path: "/admin/claims", who: "staff", prepare: async (page) => {
      await page.locator('main a[href*="/admin/claims/"]').first().click();
      await page.waitForURL(/\/admin\/claims\/[^/]+$/);
    } },
  { name: "settings-security", path: "/settings/security", who: "dev", prepare: async (page) => {
      await page.locator('[data-hydrated="true"]').first().waitFor().catch(() => undefined);
    } },
  { name: "settings-notifications", path: "/settings/notifications", who: "dev", prepare: async (page) => {
      await page.locator('[data-hydrated="true"]').first().waitFor().catch(() => undefined);
    } },
  { name: "help", path: "/help", who: "dev" },
  { name: "help-public", path: "/help", who: "none" },
  { name: "terms", path: "/legal/terms", who: "none" },
  { name: "companies", path: "/dev/companies", who: "dev" },
  { name: "company", path: "/dev/companies", who: "dev", prepare: async (page) => {
      await page.locator('main a[href*="/dev/companies/"]').first().click();
      await page.waitForURL(/\/dev\/companies\/[^/?]+/);
    } },
  { name: "dev-engagements", path: "/dev/engagements", who: "dev" },
  { name: "org-engagements", path: "/org/engagements", who: "org" },
  { name: "login", path: "/login", who: "none" },
  { name: "login-error", path: "/login", who: "none", prepare: async (page) => {
      await page.locator('form[data-hydrated="true"]').first().waitFor();
      await page.getByLabel("Email address").fill("nobody-p18@example.com");
      await page.getByLabel("Password", { exact: true }).fill("not the right password");
      await page.getByRole("button", { name: "Log in", exact: true }).click();
      await page.locator("main").getByRole("alert").waitFor();
    } },
  { name: "signup", path: "/signup", who: "none" },
  { name: "signup-org", path: "/signup", who: "none", prepare: async (page) => {
      await page.locator('form[data-hydrated="true"]').first().waitFor();
      await page.getByRole("radio", { name: /^For an organisation/ }).check();
    } },
  { name: "check-email", path: "/signup/check-email?for=login", who: "none" },
  { name: "link-failed", path: "/auth/link#token=not-a-token", who: "none", prepare: async (page) => {
      await page.getByRole("heading", { name: "This link no longer works" }).waitFor();
    } },
  // The second factor: a session that owes it (one password sign-in, reused for every variant: the API throttles logins).
  { name: "two-step", path: "/auth/mfa", who: "pendingMfa", prepare: async (page) => {
      await page.locator('form[data-hydrated="true"]').first().waitFor();
    } },
  { name: "two-step-recovery", path: "/auth/mfa", who: "pendingMfa", prepare: async (page) => {
      await page.locator('form[data-hydrated="true"]').first().waitFor();
      await page.getByRole("button", { name: "Use a recovery code" }).click();
    } },
];

function wanted(shot: Shot) {
  return !FILTER || FILTER.test(shot.name);
}

/** Signs a demo person in through the real screens; a code already used in this window waits for the next one. */
async function signIn(browser: Browser, who: Exclude<Who, "none">): Promise<string> {
  const login = who === "pendingMfa" ? PEOPLE.dev : PEOPLE[who];
  const person = new DemoStaff(login.email, login.name, demoTotpSecret(login.email));
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const page = await context.newPage();
  await page.goto("/login");
  await page.locator('form[data-hydrated="true"]').first().waitFor();
  await page.getByLabel("Email address").fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/mfa$/);
  for (let attempt = 0; attempt < 3 && who !== "pendingMfa"; attempt++) {
    await page.locator('form[data-hydrated="true"]').first().waitFor();
    await page.getByLabel("6-digit code").fill(totp(person.secret, { offset: attempt }));
    await page.getByRole("button", { name: "Continue" }).click();
    const left = await Promise.race([
      page.waitForURL((url) => !url.pathname.startsWith("/auth/mfa")).then(() => true),
      page.locator("main").getByRole("alert").waitFor().then(() => false),
    ]);
    if (left) break;
    if (attempt === 2) throw new Error(`two-step sign-in failed for ${person.email}`);
    // The code's window was already used (a previous run): wait for the next one.
    await page.waitForTimeout(31_000);
  }
  const file = join(__dirname, "..", "test-results", "design-shots", `state-${who}.json`);
  mkdirSync(join(__dirname, "..", "test-results", "design-shots"), { recursive: true });
  await context.storageState({ path: file });
  await context.close();
  return file;
}

test("design screenshots with a strict axe pass", async ({ browser }) => {
  mkdirSync(OUT, { recursive: true });
  const states = new Map<Who, string>();
  const report: Array<{ shot: string; theme: string; width: number; violations: unknown[]; primaries: number; overflow: number }> = [];
  for (const shot of SHOTS.filter(wanted)) {
    for (const theme of THEMES) {
      for (const width of WIDTHS) {
        let state: string | undefined;
        if (shot.who !== "none") {
          if (!states.has(shot.who)) states.set(shot.who, await signIn(browser, shot.who));
          state = states.get(shot.who);
        }
        const context: BrowserContext = await browser.newContext({
          baseURL: test.info().project.use.baseURL,
          viewport: { width, height: width < 600 ? 812 : 900 },
          isMobile: width < 600,
          hasTouch: width < 600,
          colorScheme: theme,
          storageState: state,
        });
        await context.addInitScript(
          ({ choice, tour }) => {
            window.localStorage.setItem("wazo-theme", choice);
            if (tour) window.localStorage.removeItem("wazo-tour:v1");
            else window.localStorage.setItem("wazo-tour:v1", "done");
          },
          { choice: theme, tour: shot.tour === true },
        );
        const page = await context.newPage();
        await page.goto(shot.path, { waitUntil: "networkidle" });
        if (shot.prepare && (await shot.prepare(page)) === false) {
          console.log(`${shot.name} ${theme} ${width}: skipped (state not reachable on this stack)`);
          await context.close();
          continue;
        }
        await settled(page);
        await page.evaluate(() => document.fonts.ready);
        // The fixed phone tab bar sits at the page's end in a full-page shot.
        await page.addStyleTag({ content: "@media (width < 64rem){[data-tab-bar]{position:absolute!important}} body{position:relative} nextjs-portal{display:none!important}" });
        await page.waitForTimeout(300);
        const file = join(OUT, `${shot.name}-${theme}-${width}.jpg`);
        await page.screenshot({ path: file, fullPage: shot.viewportOnly !== true, type: "jpeg", quality: 78 });
        if (shot.frame) {
          // A full-page shot leaves a frame's document blank; its own shot shows the page inside it.
          await page.locator(shot.frame).scrollIntoViewIfNeeded();
          await page.locator(shot.frame).screenshot({ path: join(OUT, `${shot.name}-frame-${theme}-${width}.jpg`), type: "jpeg", quality: 78 });
        }
        let axe = new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]);
        for (const selector of shot.exclude ?? []) axe = axe.exclude(selector);
        const results = await axe.analyze();
        const violations = results.violations.map((v) => ({ id: v.id, impact: v.impact, help: v.help, targets: v.nodes.slice(0, 5).map((n) => n.target) }));
        const primaries = await page.locator("[data-primary]").count();
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        report.push({ shot: shot.name, theme, width, violations, primaries, overflow });
        console.log(`${shot.name} ${theme} ${width}: axe ${violations.length}, primaries ${primaries}, overflow ${overflow}`);
        expect.soft(violations, `${shot.name} ${theme} ${width} axe`).toEqual([]);
        expect.soft(primaries, `${shot.name} ${theme} ${width} primaries`).toBeLessThanOrEqual(1);
        expect.soft(overflow, `${shot.name} ${theme} ${width} overflow`).toBeLessThanOrEqual(0);
        await context.close();
      }
    }
  }
  mkdirSync(join(REPORT, ".."), { recursive: true });
  writeFileSync(REPORT, JSON.stringify(report, null, 2));
});
