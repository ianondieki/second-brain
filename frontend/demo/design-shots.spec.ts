/**
 * Screenshots of the real screens on the demo stack, light and dark, 1440 and 375 px, each with a strict axe pass
 * (every impact), the one-primary-action rule and the no-sideways-scroll rule (e2e/support/screen.ts), for the P18
 * and P19 quality loops. One sign-in per demo person; the session is reused across the shots. Writes
 * docs/demo/screenshots/<set>/<name>-<theme>-<width>.jpg (the set is p18 unless the shot names its own) and
 * test-results/design-shots/axe.json.
 *
 * The P19 shots make what the seed lacks and tidy up after themselves (SHOT_KEEP=1 keeps it, for the JS budget and
 * Lighthouse runs on the same pages): one Problem Brief from Telco A's reviewer, approved by the staff moderator and
 * closed at the end; one draft idea of Amina's for the teaser checks, deleted at the end; and two new test accounts
 * (an organisation and a developer who pitched to it, reviewed and approved to proceed) whose notifications the bell
 * and the Notifications page show. The test accounts need E2E_DATABASE_OWNER_URL (frontend/.env.e2e), as the e2e does.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff } from "../e2e/support/moderation-scene";
import { settled } from "../e2e/support/screen";
import { demoTotpSecret, totp } from "../e2e/support/totp";
import { pitchFromDeveloper, post, signUpOrg } from "../e2e/support/tracker-scene";

const REPO = join(__dirname, "..", "..");
const SHOTS_ROOT = join(REPO, "docs", "demo", "screenshots");
/** Where a shot goes: SHOTS_DIR for every shot, else its set's folder (p18 by default). */
const outDir = (set = "p18") => process.env.SHOTS_DIR ?? join(SHOTS_ROOT, set);
const KEEP = process.env.SHOT_KEEP === "1";
const REPORT = join(__dirname, "..", "test-results", "design-shots", "axe.json");
const THEMES = (process.env.SHOT_THEMES ?? "light,dark").split(",") as Array<"light" | "dark">;
const WIDTHS = (process.env.SHOT_WIDTHS ?? "1440,375").split(",").map(Number);
const FILTER = process.env.SHOT_FILTER ? new RegExp(process.env.SHOT_FILTER) : null;

type Demo = "dev" | "devBrian" | "org" | "orgOwner" | "orgSacco" | "staff" | "moderator";
/** A demo person, a session that owes its second factor, or one of the two new test accounts of the bell's scene. */
type Who = "none" | "pendingMfa" | Demo | "freshDev" | "freshOrg";
interface Shot {
  name: string;
  path: string;
  who: Who;
  /** The screenshots folder under docs/demo/screenshots/ (default p18). */
  set?: "p19";
  /** Only these widths (default SHOT_WIDTHS). */
  widths?: number[];
  /** Shoot this element only (the top bar), not the page. */
  element?: string;
  /** Steps after the page loaded (open a tab, a dialog, type into a field); `false` skips the shot (its state cannot be reached on this stack). */
  prepare?: (page: Page, browser: Browser) => Promise<void | false>;
  /** Selectors axe leaves out (a sandboxed frame it cannot run inside). */
  exclude?: string[];
  /** Let the first-login tour show (every other shot remembers it as done). */
  tour?: boolean;
  /** The viewport only, not the whole page: a modal dialog's backdrop covers the viewport. */
  viewportOnly?: boolean;
  /** A frame on the page whose own document is shot too (`<name>-frame-…`): the marked full proposal. */
  frame?: string;
}

const PEOPLE: Record<Demo, { email: string; name: string }> = {
  dev: { email: "amina@developers.example", name: "Amina Wanjiru" },
  devBrian: { email: "brian@developers.example", name: "Brian Otieno" },
  org: { email: "reviewer@telco-a.example", name: "Telco A reviewer" },
  orgOwner: { email: "owner@telco-a.example", name: "Telco A owner" },
  orgSacco: { email: "owner@sacco-b.example", name: "SACCO B owner" },
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

// --- The P19 scenes: what the seed lacks, made once per run and tidied up at its end (unless SHOT_KEEP=1) ----------

const baseUrl = () => test.info().project.use.baseURL as string;
const states = new Map<Exclude<Who, "none">, Promise<string>>();

/** A person's saved session, signed in (or, for the bell's scene, signed up) once per run. */
function stateOf(browser: Browser, who: Exclude<Who, "none">): Promise<string> {
  let state = states.get(who);
  if (!state) {
    state = who === "freshDev" || who === "freshOrg" ? bellScene(browser).then((scene) => scene[who]) : signIn(browser, who);
    states.set(who, state);
  }
  return state;
}

/** Runs `act` in a new context signed in as `who`. */
async function asPerson<T>(browser: Browser, who: Exclude<Who, "none">, act: (context: BrowserContext) => Promise<T>): Promise<T> {
  const context = await browser.newContext({ baseURL: baseUrl(), storageState: await stateOf(browser, who) });
  try {
    return await act(context);
  } finally {
    await context.close();
  }
}

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `${path}: ${response.status()}`).toBeTruthy();
  return (await response.json()) as T;
}

/** "YYYY-MM-DD" in Nairobi, `days` from today. */
function nairobiDay(days: number): string {
  const at = new Date(Date.now() + days * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi", year: "numeric", month: "2-digit", day: "2-digit" }).format(at);
}

const TELCO_A = "Telco A (fixture)";
// [[COPY-REVIEW]] demo content: Telco A's Brief, the problem Amina's seeded "Fuel-level alerts" idea answers.
const BRIEF = {
  title: "Tower-site generators run dry before anyone knows",
  statement:
    "Our field teams learn that a generator tank at an off-grid tower site is empty only after the site stops serving" +
    " calls, often at night. We want a warning early enough to plan the refuelling trip, one that fits the network" +
    " operations centre we already run.",
  affected_group: "Subscribers served by off-grid tower sites in rural counties",
  county_code: "KE-30",
};

interface BriefScene {
  orgId: string;
  id: string;
  title: string;
  /** Posted by this run (or left in review by a failed one): closed at the end. */
  ours: boolean;
  published: boolean;
}
let briefPosted: Promise<BriefScene> | null = null;
let briefPublished: Promise<BriefScene> | null = null;

/** Telco A's open Brief: one that is already published, else one in review, else a new one from its reviewer. */
function postedBrief(browser: Browser): Promise<BriefScene> {
  briefPosted ??= asPerson(browser, "org", async ({ request }) => {
    const me = await getJson<{ memberships: Array<{ org_id: string; org_name: string }> }>(request, "/api/auth/me");
    const orgId = me.memberships.find((m) => m.org_name === TELCO_A)?.org_id;
    expect(orgId, `${TELCO_A} from the demo seed`).toBeTruthy();
    const list = await getJson<{ items: Array<{ id: string; title: string; state: string }>; budget_bands: Array<{ code: string }> }>(
      request,
      `/api/orgs/${orgId}/briefs`,
    );
    const open = list.items.find((b) => b.state === "published") ?? list.items.find((b) => b.state === "in_review");
    if (open) return { orgId: orgId!, id: open.id, title: open.title, ours: open.state === "in_review", published: open.state === "published" };
    const niches = await getJson<Array<{ id: string; slug: string; children: Array<{ id: string; slug: string }> }>>(
      request,
      "/api/directory/niches",
    );
    const all = niches.flatMap((n) => [n, ...n.children]);
    const niche = all.find((n) => n.slug === "networks-telecommunications") ?? all[0];
    const brief = await post<{ id: string; title: string }>(
      request,
      `/api/orgs/${orgId}/briefs`,
      { ...BRIEF, niche_id: niche.id, budget_band: list.budget_bands[1]?.code ?? null, deadline: nairobiDay(30), visibility: "public" },
      201,
    );
    return { orgId: orgId!, id: brief.id, title: brief.title, ours: true, published: false };
  });
  return briefPosted;
}

/** Telco A's Brief, approved by the staff moderator through the queue's screens when it is still in review. */
function publishedBrief(browser: Browser): Promise<BriefScene> {
  briefPublished ??= postedBrief(browser).then(async (scene) => {
    if (scene.published) return scene;
    await asPerson(browser, "moderator", async (context) => {
      const page = await context.newPage();
      await page.goto("/admin/moderation");
      await page.locator("[data-case]").filter({ hasText: scene.title }).getByRole("link", { name: scene.title }).click();
      await page.waitForURL(/\/admin\/moderation\/cases\//);
      await page.locator('main [data-hydrated="true"]').first().waitFor();
      await page.getByRole("button", { name: "Approve" }).click();
      await page.getByRole("status").filter({ hasText: "Approved. The problem is published." }).waitFor();
    });
    return { ...scene, published: true };
  });
  return briefPublished;
}

// [[COPY-REVIEW]] demo content: a teaser whose summary says how it works, so the second check has something to name.
const TEASER = {
  title: "Shared solar chillers for dairy co-ops",
  summary:
    "Co-ops book a shared solar chiller by SMS and pay per litre cooled. We use a gradient-boosted model over M-Pesa" +
    " statements to set each co-op's booking quota.",
};
let teaserDraft: string | null = null;

/** Amina's draft for the teaser checks: made on the first visit (title and summary, saved), opened on the others. */
async function openTeaserDraft(page: Page) {
  if (teaserDraft) {
    await page.goto(teaserDraft, { waitUntil: "networkidle" });
    return;
  }
  await page.goto("/dev/ideas/new");
  await page.getByLabel("Title", { exact: true }).fill(TEASER.title);
  await page.waitForURL(/\/dev\/ideas\/[0-9a-f-]{36}\/edit/);
  await page.getByLabel("Summary").fill(TEASER.summary);
  await page.getByRole("status").filter({ hasText: /^Saved$/ }).waitFor();
  teaserDraft = new URL(page.url()).pathname;
}

/** Presses one teaser check and waits for its answer from the API (the fake LLM on the demo stack). */
async function runCheck(page: Page, name: string, endpoint: string) {
  const card = page.getByRole("region", { name: "Teaser checks" });
  await Promise.all([
    page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(endpoint), { timeout: 30_000 }),
    card.getByRole("button", { name }).click(),
  ]);
  await expect(card.getByRole("button", { name })).not.toHaveAttribute("aria-disabled", "true");
}

interface BellScene {
  freshDev: string;
  freshOrg: string;
}
let bell: Promise<BellScene> | null = null;

/**
 * Two new test accounts for the bell (the demo seed writes no in-app rows): an organisation, and a developer who
 * pitched to it; the organisation starts the review and approves to proceed, so the developer has three notifications
 * (the pitch's receipt and the two tracker notices the worker writes) and the organisation none.
 */
function bellScene(browser: Browser): Promise<BellScene> {
  bell ??= (async () => {
    const orgContext = await browser.newContext({ baseURL: baseUrl() });
    const devContext = await browser.newContext({ baseURL: baseUrl() });
    try {
      const org = await signUpOrg(orgContext.request, { orgName: "Kilimo Fresh Dairies Limited" });
      const dev = await pitchFromDeveloper(devContext.request, org.orgId, { title: TEASER.title });
      const step = async (command: string, body: Record<string, unknown> = {}) => {
        const detail = await getJson<{ lock_version: number }>(orgContext.request, `/api/engagements/${dev.engagementId}`);
        await post(orgContext.request, `/api/engagements/${dev.engagementId}/${command}`, { lock_version: detail.lock_version, ...body });
      };
      await step("start-review");
      const me = await getJson<{ user: { id: string } }>(orgContext.request, "/api/auth/me");
      await step("approve", { contact_user_id: me.user.id, contact_channel: "email", contact_by: nairobiDay(7) });
      const unread = async () => (await getJson<{ count: number }>(devContext.request, "/api/me/notifications/unread-count")).count;
      await expect.poll(unread, { timeout: 60_000, intervals: [500, 1_000, 2_000] }).toBe(3);
      const dir = join(__dirname, "..", "test-results", "design-shots");
      mkdirSync(dir, { recursive: true });
      const scene = { freshDev: join(dir, "state-freshDev.json"), freshOrg: join(dir, "state-freshOrg.json") };
      await devContext.storageState({ path: scene.freshDev });
      await orgContext.storageState({ path: scene.freshOrg });
      return scene;
    } finally {
      await orgContext.close();
      await devContext.close();
    }
  })();
  return bell;
}

/** Closes the Brief and deletes the draft this run made (the new test accounts stay, as the e2e's do). */
async function tidyUp(browser: Browser) {
  if (KEEP) return;
  const brief = briefPublished ? await briefPublished.catch(() => null) : null;
  if (brief?.ours) {
    await asPerson(browser, "org", ({ request }) => post(request, `/api/orgs/${brief.orgId}/briefs/${brief.id}/close`, {}));
  }
  const id = teaserDraft?.split("/")[3];
  if (id) {
    await asPerson(browser, "dev", async ({ request }) => {
      const { csrf_token } = await getJson<{ csrf_token: string }>(request, "/api/auth/csrf");
      const response = await request.delete(`/api/me/proposals/${id}`, { headers: { "X-CSRF-Token": csrf_token } });
      expect(response.ok(), `delete the teaser draft: ${response.status()}`).toBeTruthy();
    });
  }
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
  // A closed engagement's one-time celebration (a fresh browser context, so it shows), and a confirm dialog as a
  // bottom sheet on phones.
  { name: "tracker-closed", path: "/dev/engagements", who: "dev", prepare: async (page) => {
      await page.locator("main article").filter({ hasText: "Project closed" }).first().getByRole("link").first().click();
      await page.locator("[data-celebration]").waitFor();
    } },
  { name: "dialog-sheet", path: "/dev/ideas", who: "dev", viewportOnly: true, prepare: async (page) => {
      await page.locator("main article").filter({ hasText: "Published" }).first().getByRole("link").first().click();
      await page.getByRole("button", { name: "Delete idea" }).click();
      await page.getByRole("dialog").waitFor();
    } },
  { name: "ideas", path: "/dev/ideas", who: "dev" },
  // "Who has seen this" with a view in it: Brian's proposal, opened by Telco A's reviewer.
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
  { name: "org-proposal-full", path: "/org/inbox", who: "org", viewportOnly: true, prepare: async (page) => {
      await page.locator("main article").first().getByRole("link").first().click();
      await page.locator("[data-tier2-state]").waitFor();
      const accept = page.getByRole("button", { name: "Accept and view" });
      if (await accept.isVisible()) await accept.click();
      else await page.getByRole("link", { name: "View full proposal" }).click();
      await page.locator("[data-tier2-frame]").waitFor();
      await page.frameLocator("[data-tier2-frame]").locator(".mark").waitFor();
    }, frame: "[data-tier2-frame]" },
  // After org-proposal-full: the first view of Brian's full proposal is what this screen lists.
  { name: "idea-views", path: "/dev/ideas", who: "devBrian", prepare: async (page) => {
      await page.locator("main article").filter({ hasText: "Cashless market-fee" }).first().getByRole("link").first().click();
      await page.locator("[data-view]").first().waitFor();
    } },
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

  // --- P19 (docs/platform/tasks/P19-F.md), into docs/demo/screenshots/p19/ ------------------------------------------
  // The editor's step 1 with both teaser checks answered on the fake LLM (the second names the summary).
  { name: "editor-checks", set: "p19", path: "/dev/ideas", who: "dev", prepare: async (page) => {
      await openTeaserDraft(page);
      await runCheck(page, "Check overlap", "/originality");
      await runCheck(page, "Check what it gives away", "/disclosure-check");
    } },
  // An organisation with no Brief yet; SACCO B has some once the e2e has posted for it.
  { name: "org-problems-empty", set: "p19", path: "/org/problems", who: "orgSacco", prepare: async (page) => {
      if (!(await page.locator("[data-empty='briefs']").isVisible())) return false;
    } },
  { name: "org-brief-new", set: "p19", path: "/org/problems/new", who: "org", prepare: async (page) => {
      await page.locator("form[data-brief-form][data-hydrated='true']").waitFor();
    } },
  // The queue while the Brief waits: "Brief by Telco A (fixture)" (nothing to show when a run left one published).
  { name: "admin-moderation-brief", set: "p19", path: "/admin/moderation", who: "moderator", prepare: async (page, browser) => {
      const brief = await postedBrief(browser);
      if (brief.published) return false;
      await page.reload({ waitUntil: "networkidle" });
      await page.locator("[data-case]").filter({ hasText: brief.title }).waitFor();
    } },
  { name: "org-problems", set: "p19", path: "/org/problems", who: "org", prepare: async (page, browser) => {
      await publishedBrief(browser);
      await page.reload({ waitUntil: "networkidle" });
      await page.locator("[data-brief][data-state='published']").first().waitFor();
    } },
  { name: "org-brief", set: "p19", path: "/org/problems", who: "org", prepare: async (page, browser) => {
      const brief = await publishedBrief(browser);
      await page.goto(`/org/problems/${brief.id}`, { waitUntil: "networkidle" });
      await page.locator("[data-state-note='published']").waitFor();
    } },
  // A refusal: the plan's open Briefs are in use (402, with the next plan), else the form's own check of an empty form.
  { name: "org-brief-new-refused", set: "p19", path: "/org/problems/new", who: "org", prepare: async (page, browser) => {
      const brief = await publishedBrief(browser);
      await page.locator("form[data-brief-form][data-hydrated='true']").waitFor();
      const { plan } = await getJson<{ plan: { problem_briefs: number | null; used: number } }>(page.request, `/api/orgs/${brief.orgId}/briefs`);
      if (plan.problem_briefs !== null && plan.used >= plan.problem_briefs) {
        await page.getByLabel("Title").fill("Refuelling trips are planned from guesswork");
        await page.getByLabel("Problem statement").fill("Trucks visit sites with full tanks and miss the ones about to run dry.");
        await page.getByLabel("Niche").selectOption({ index: 1 });
        await page.getByRole("group", { name: "Budget band" }).getByRole("radio").first().check();
        await page.getByRole("button", { name: "Post the brief" }).click();
        await page.locator("[data-refusal='planLimit']").waitFor();
      } else {
        await page.getByRole("button", { name: "Post the brief" }).click();
        await page.getByText("Write a title.").waitFor();
      }
    } },
  { name: "discover-briefs", set: "p19", path: "/dev/discover?view=briefs", who: "dev", prepare: async (page, browser) => {
      const brief = await publishedBrief(browser);
      await page.reload({ waitUntil: "networkidle" });
      await page.locator(`[data-brief="${brief.id}"]`).waitFor();
    } },
  { name: "problem-brief", set: "p19", path: "/dev/discover?view=briefs", who: "dev", prepare: async (page, browser) => {
      const brief = await publishedBrief(browser);
      await page.goto(`/problems/${brief.id}`, { waitUntil: "networkidle" });
      await page.getByRole("heading", { level: 1 }).waitFor();
    } },
  { name: "notifications", set: "p19", path: "/notifications", who: "freshDev" },
  { name: "notifications-empty", set: "p19", path: "/notifications", who: "freshOrg" },
  // The top bar with the unread count, on a phone.
  { name: "bell", set: "p19", path: "/dev", who: "freshDev", widths: [375], element: "header" },
];

function wanted(shot: Shot) {
  return !FILTER || FILTER.test(shot.name);
}

/** Signs a demo person in through the real screens; a code already used in this window waits for the next one. */
async function signIn(browser: Browser, who: "pendingMfa" | Demo): Promise<string> {
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
  const report: Array<{ shot: string; theme: string; width: number; violations: unknown[]; primaries: number; overflow: number }> = [];
  try {
    for (const shot of SHOTS.filter(wanted)) {
      const out = outDir(shot.set);
      mkdirSync(out, { recursive: true });
      for (const theme of THEMES) {
        for (const width of shot.widths ?? WIDTHS) {
          const state = shot.who === "none" ? undefined : await stateOf(browser, shot.who);
          const context: BrowserContext = await browser.newContext({
            baseURL: test.info().project.use.baseURL,
            viewport: { width, height: width < 600 ? 812 : 900 },
            isMobile: width < 600,
            hasTouch: width < 600,
            colorScheme: theme,
            storageState: state,
          });
          // The tour is remembered as done (the storage key the client reads, the cookie the server reads) unless the
          // shot is the tour's own.
          if (!shot.tour) {
            const url = test.info().project.use.baseURL as string;
            await context.addCookies(["developer", "org"].map((side) => ({ name: `wazo-tour-${side}`, value: "done", url })));
          }
          await context.addInitScript(
            ({ choice, tour }) => {
              window.localStorage.setItem("wazo-theme", choice);
              for (const side of ["developer", "org"]) {
                if (tour) window.localStorage.removeItem(`wazo-tour:v1:${side}`);
                else window.localStorage.setItem(`wazo-tour:v1:${side}`, "done");
              }
            },
            { choice: theme, tour: shot.tour === true },
          );
          const page = await context.newPage();
          await page.goto(shot.path, { waitUntil: "networkidle" });
          if (shot.prepare && (await shot.prepare(page, browser)) === false) {
            console.log(`${shot.name} ${theme} ${width}: skipped (state not reachable on this stack)`);
            await context.close();
            continue;
          }
          await settled(page);
          await page.evaluate(() => document.fonts.ready);
          // The fixed phone tab bar sits at the page's end in a full-page shot.
          await page.addStyleTag({ content: "@media (width < 64rem){[data-tab-bar]{position:absolute!important}} body{position:relative} nextjs-portal{display:none!important}" });
          await page.waitForTimeout(300);
          const file = join(out, `${shot.name}-${theme}-${width}.jpg`);
          if (shot.element) await page.locator(shot.element).first().screenshot({ path: file, type: "jpeg", quality: 78 });
          else await page.screenshot({ path: file, fullPage: shot.viewportOnly !== true, type: "jpeg", quality: 78 });
          if (shot.frame) {
            // A full-page shot leaves a frame's document blank; its own shot shows the page inside it.
            await page.locator(shot.frame).scrollIntoViewIfNeeded();
            await page.locator(shot.frame).screenshot({ path: join(out, `${shot.name}-frame-${theme}-${width}.jpg`), type: "jpeg", quality: 78 });
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
  } finally {
    await tidyUp(browser);
  }
  mkdirSync(join(REPORT, ".."), { recursive: true });
  writeFileSync(REPORT, JSON.stringify(report, null, 2));
});
