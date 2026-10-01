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

type Who = "none" | "pendingMfa" | "dev" | "org" | "orgOwner" | "staff" | "moderator";
interface Shot {
  name: string;
  path: string;
  who: Who;
  /** Steps after the page loaded (open a tab, a dialog, type into a field). */
  prepare?: (page: Page) => Promise<void>;
  /** Selectors axe leaves out (a sandboxed frame it cannot run inside). */
  exclude?: string[];
  /** Let the first-login tour show (every other shot remembers it as done). */
  tour?: boolean;
}

const PEOPLE: Record<Exclude<Who, "none" | "pendingMfa">, { email: string; name: string }> = {
  dev: { email: "amina@developers.example", name: "Amina Wanjiru" },
  org: { email: "reviewer@telco-a.example", name: "Telco A reviewer" },
  orgOwner: { email: "owner@telco-a.example", name: "Telco A owner" },
  staff: { email: "admin@staff.example", name: "Staff Admin (demo)" },
  moderator: { email: "moderator@staff.example", name: "Staff Moderator (demo)" },
};

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
        if (shot.prepare) await shot.prepare(page);
        await settled(page);
        await page.evaluate(() => document.fonts.ready);
        // The fixed phone tab bar sits at the page's end in a full-page shot.
        await page.addStyleTag({ content: "@media (width < 64rem){[data-tab-bar]{position:absolute!important}} body{position:relative} nextjs-portal{display:none!important}" });
        await page.waitForTimeout(300);
        const file = join(OUT, `${shot.name}-${theme}-${width}.jpg`);
        await page.screenshot({ path: file, fullPage: true, type: "jpeg", quality: 78 });
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
