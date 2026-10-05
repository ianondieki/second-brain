/**
 * Screenshots of the real screens on the demo stack, light and dark, 1440 and 375 px, each with a strict axe pass
 * (every impact), the one-primary-action rule and the no-sideways-scroll rule (e2e/support/screen.ts), for the P18
 * and P19 quality loops. One sign-in per demo person; the session is reused across the shots. Writes
 * docs/demo/screenshots/<set>/<name>-<theme>-<width>.jpg (the set is p18 unless the shot names its own) and
 * test-results/design-shots/axe.json.
 *
 * The P19 shots make what the seed lacks and tidy up after themselves (SHOT_KEEP=1 keeps it, for the JS budget and
 * Lighthouse runs on the same pages): one Problem Brief from Telco A's reviewer, approved by the staff moderator and
 * closed at the end; one draft idea of Brian's for the teaser checks, deleted at the end; and two new test accounts
 * (an organisation and a developer who pitched to it, reviewed and approved to proceed) whose notifications the bell
 * and the Notifications page show. The test accounts need E2E_DATABASE_OWNER_URL (frontend/.env.e2e), as the e2e does.
 *
 * The P21 shots (docs/platform/tasks/P21.md) read the demo seed's thread, shortlist entry and saved search; Compare needs
 * a second shortlisted proposal, so Telco A's reviewer stars one more Inbox proposal and the end of the run takes the
 * star off again (SHOT_KEEP=1 leaves it). They post no message and report none: the moderation shot is skipped unless
 * a reported message is already in the queue.
 *
 * The P22-A shots (docs/platform/tasks/P22.md A, Today's five) read the demo seed's quiz: Amina has played today's set
 * (a 2-day streak, on the board), Brian has played and is off the board. The not-played states are a new test developer's,
 * signed up through the emailed link (as e2e/quiz.spec.ts does), who opens the play form and answers nothing, or two
 * questions, and never sends it. The flag sheet is opened, never sent; the staff admin's shots decide, pull and restore
 * nothing.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { signUpDeveloper } from "../e2e/support/accounts";
import { DEMO_PASSWORD, DemoStaff } from "../e2e/support/moderation-scene";
import { settled } from "../e2e/support/screen";
import { demoTotpSecret, totp } from "../e2e/support/totp";
import { appToday, plusDays } from "../e2e/support/clock";
import { actionsReady, pitchFromDeveloper, post, signUpOrg } from "../e2e/support/tracker-scene";

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
/** A demo person, a session that owes its second factor, or a new test account of the bell's or the side states' scene. */
type Who = "none" | "pendingMfa" | Demo | "freshDev" | "freshOrg" | "sideDev" | "sideOrg" | "quizDev";
interface Shot {
  name: string;
  path: string;
  who: Who;
  /** The screenshots folder under docs/demo/screenshots/ (default p18). */
  set?: "p19" | "p21" | "p22a";
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
    state =
      who === "freshDev" || who === "freshOrg"
        ? bellScene(browser).then((scene) => scene[who])
        : who === "sideDev" || who === "sideOrg"
          ? sideScene(browser).then((scene) => scene[who])
          : who === "quizDev"
            ? quizNewcomer(browser)
            : signIn(browser, who);
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
  /** The scene's own Brief (this run's or a failed run's): closed at the end. */
  ours: boolean;
  published: boolean;
}
let briefPosted: Promise<BriefScene> | null = null;
let briefPublished: Promise<BriefScene> | null = null;

/** Approves the Brief of this title in the moderation queue, through its screens, as the staff moderator. */
async function approveInQueue(browser: Browser, title: string) {
  await asPerson(browser, "moderator", async (context) => {
    const page = await context.newPage();
    await page.goto("/admin/moderation");
    await page.locator("[data-case]").filter({ hasText: title }).getByRole("link", { name: title }).click();
    await page.waitForURL(/\/admin\/moderation\/cases\//);
    await page.locator('main [data-hydrated="true"]').first().waitFor();
    await page.getByRole("button", { name: "Approve" }).click();
    await page.getByRole("status").filter({ hasText: "Approved. The Brief is published to developers." }).waitFor();
  });
}

/**
 * Telco A's Brief for the shots: this scene's own when it is open (published or in review), else a new one from its
 * reviewer. Briefs an e2e run left open (titles with a run tag) are closed first, as the e2e's own set-up does, so
 * the claimed plan has room and the shots show the scene's words.
 */
function postedBrief(browser: Browser): Promise<BriefScene> {
  briefPosted ??= asPerson(browser, "org", async ({ request }) => {
    const me = await getJson<{ memberships: Array<{ org_id: string; org_name: string }> }>(request, "/api/auth/me");
    const orgId = me.memberships.find((m) => m.org_name === TELCO_A)?.org_id;
    expect(orgId, `${TELCO_A} from the demo seed`).toBeTruthy();
    type Listed = { id: string; title: string; state: string };
    const read = () =>
      getJson<{ items: Listed[]; budget_bands: Array<{ code: string }> }>(request, `/api/orgs/${orgId}/briefs`);
    let list = await read();
    const isOpen = (b: Listed) => b.state === "published" || b.state === "in_review";
    for (const leftover of list.items.filter((b) => isOpen(b) && b.title !== BRIEF.title)) {
      if (leftover.state === "in_review") await approveInQueue(browser, leftover.title); // only a published Brief closes
      await post(request, `/api/orgs/${orgId}/briefs/${leftover.id}/close`, {});
    }
    list = await read();
    const open = list.items.find((b) => isOpen(b) && b.title === BRIEF.title);
    if (open) return { orgId: orgId!, id: open.id, title: open.title, ours: true, published: open.state === "published" };
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
    await approveInQueue(browser, scene.title);
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
/** Whose draft it is: Brian, so Amina's demo ideas stay as seeded and her daily overlap checks stay unused. */
const TEASER_WHO = "devBrian" as const;

/**
 * The teaser checks' draft: one a kept run left (SHOT_KEEP=1), else made on the first visit (title and
 * summary, saved); opened on the others.
 */
async function openTeaserDraft(page: Page) {
  if (!teaserDraft) {
    const { items } = await getJson<{ items: Array<{ id: string; title: string | null; status: string }> }>(page.request, "/api/me/proposals");
    const kept = items.find((item) => item.status === "draft" && item.title === TEASER.title);
    if (kept) teaserDraft = `/dev/ideas/${kept.id}/edit`;
  }
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
  await page.mouse.move(0, 0); // no hover left on the button in the shot
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
  const starred = shortlisted ? await shortlisted.catch(() => null) : null;
  if (starred?.added) {
    const added = starred.added;
    await asPerson(browser, "org", async ({ request }) => {
      const { csrf_token } = await getJson<{ csrf_token: string }>(request, "/api/auth/csrf");
      const response = await request.delete(`/api/orgs/${starred.orgId}/shortlist/${added}`, { headers: { "X-CSRF-Token": csrf_token } });
      expect(response.ok(), `take the shot's star off: ${response.status()}`).toBeTruthy();
    });
  }
  const brief = briefPublished ? await briefPublished.catch(() => null) : null;
  if (brief?.ours) {
    await asPerson(browser, "org", ({ request }) => post(request, `/api/orgs/${brief.orgId}/briefs/${brief.id}/close`, {}));
  }
  const id = teaserDraft?.split("/")[3];
  if (id) {
    await asPerson(browser, TEASER_WHO, async ({ request }) => {
      const { csrf_token } = await getJson<{ csrf_token: string }>(request, "/api/auth/csrf");
      const response = await request.delete(`/api/me/proposals/${id}`, { headers: { "X-CSRF-Token": csrf_token } });
      expect(response.ok(), `delete the teaser draft: ${response.status()}`).toBeTruthy();
    });
  }
}

/** One step on an engagement through the API, on the lock version it last read. */
async function engagementCommand(request: APIRequestContext, id: string, command: string, body: Record<string, unknown> = {}) {
  const detail = await getJson<{ lock_version: number }>(request, `/api/engagements/${id}`);
  await post(request, `/api/engagements/${id}/${command}`, { lock_version: detail.lock_version, ...body });
}

// [[COPY-REVIEW]] demo content: the side states' question, answer, hold and resume.
const SIDE = {
  orgName: "Maziwa Bora Dairies Limited",
  question: "Which co-ops ran the pilot, and roughly how many litres a day did the chillers keep cold?",
  answer: "Kipkelion and Olenguruone dairy co-ops, about 1,200 litres a day over six weeks.",
  nextQuestion: "Did the co-ops pay per litre during the pilot, or was it free?",
  holdReason: "Our budget committee meets next week; we pick this up after it.",
  resumeReason: "The committee met early and approved the review.",
};

interface SideScene {
  sideDev: string;
  sideOrg: string;
  id: string;
}
let side: Promise<SideScene> | null = null;
let sideAnswered: Promise<SideScene> | null = null;
let sidePaused: Promise<SideScene> | null = null;
let sideResumed: Promise<SideScene> | null = null;

/**
 * The tracker's side states (REQ-ENG-10) on one engagement of two new test accounts, as e2e/tracker-branches.spec.ts
 * builds them: a developer pitches to a new organisation, which starts the review and asks a question. The later
 * states follow on demand, in the shots' order: the developer answers; the organisation pauses for 7 days on the app's
 * clock; the developer resumes early.
 */
function sideScene(browser: Browser): Promise<SideScene> {
  side ??= (async () => {
    const orgContext = await browser.newContext({ baseURL: baseUrl() });
    const devContext = await browser.newContext({ baseURL: baseUrl() });
    try {
      const org = await signUpOrg(orgContext.request, { orgName: SIDE.orgName });
      const dev = await pitchFromDeveloper(devContext.request, org.orgId, { title: TEASER.title });
      await engagementCommand(orgContext.request, dev.engagementId, "start-review");
      await engagementCommand(orgContext.request, dev.engagementId, "request-info", { question: SIDE.question });
      const dir = join(__dirname, "..", "test-results", "design-shots");
      mkdirSync(dir, { recursive: true });
      const scene = { sideDev: join(dir, "state-sideDev.json"), sideOrg: join(dir, "state-sideOrg.json"), id: dev.engagementId };
      await devContext.storageState({ path: scene.sideDev });
      await orgContext.storageState({ path: scene.sideOrg });
      return scene;
    } finally {
      await orgContext.close();
      await devContext.close();
    }
  })();
  return side;
}

function answeredSide(browser: Browser): Promise<SideScene> {
  sideAnswered ??= sideScene(browser).then(async (scene) => {
    await asPerson(browser, "sideDev", ({ request }) => engagementCommand(request, scene.id, "answer-info", { answer: SIDE.answer }));
    return scene;
  });
  return sideAnswered;
}

function pausedSide(browser: Browser): Promise<SideScene> {
  sidePaused ??= answeredSide(browser).then(async (scene) => {
    await asPerson(browser, "sideOrg", async ({ request }) =>
      engagementCommand(request, scene.id, "pause", { reason: SIDE.holdReason, resume_at: plusDays(await appToday(request), 7) }),
    );
    return scene;
  });
  return sidePaused;
}

function resumedSide(browser: Browser): Promise<SideScene> {
  sideResumed ??= pausedSide(browser).then(async (scene) => {
    await asPerson(browser, "sideDev", ({ request }) => engagementCommand(request, scene.id, "resume", { reason: SIDE.resumeReason }));
    return scene;
  });
  return sideResumed;
}

/** Opens a tracker's side-state sheet through its button, once the actions have hydrated. */
async function openSideSheet(page: Page, name: string) {
  await actionsReady(page);
  await page.locator("[data-actions]").getByRole("button", { name, exact: true }).click();
  const sheet = page.locator("dialog[open][data-side-sheet]");
  await sheet.waitFor();
  return sheet;
}


// --- The P21 scenes: the demo seed's thread, shortlist and saved search (docs/platform/tasks/P21.md) -----------------

const SACCO_B = "SACCO B (fixture)";
const ENDED = new Set(["CLOSED", "DECLINED", "WITHDRAWN", "EXPIRED", "TERMINATED"]);

/** The engagement whose thread the shot shows, from `who`'s own list (Amina's open one with SACCO B, Telco A's SUBMITTED one). */
async function engagementOf(page: Page, org: string, pick: (state: string) => boolean): Promise<string | null> {
  const { items } = await getJson<{ items: Array<{ id: string; org_name: string; state: string }> }>(page.request, "/api/me/engagements");
  return items.find((e) => e.org_name === org && pick(e.state))?.id ?? null;
}

/** Telco A's engagement at SUBMITTED, read from its organisation's list (the thread is not open yet). */
async function submittedAtTelcoA(page: Page): Promise<string | null> {
  const me = await getJson<{ memberships: Array<{ org_id: string; org_name: string }> }>(page.request, "/api/auth/me");
  const orgId = me.memberships.find((m) => m.org_name === TELCO_A)?.org_id;
  if (!orgId) return null;
  const { items } = await getJson<{ items: Array<{ id: string; state: string }> }>(page.request, `/api/orgs/${orgId}/engagements`);
  return items.find((e) => e.state === "SUBMITTED")?.id ?? null;
}

interface ShortlistScene {
  orgId: string;
  ids: string[];
  /** The proposal this run starred (taken off at the end), if the seed's one entry was alone. */
  added: string | null;
}
let shortlisted: Promise<ShortlistScene> | null = null;

/** Telco A's shortlist with at least two entries: the seed's one, and one more Inbox proposal starred by its reviewer. */
function shortlistScene(browser: Browser): Promise<ShortlistScene> {
  shortlisted ??= asPerson(browser, "org", async ({ request }) => {
    const me = await getJson<{ memberships: Array<{ org_id: string; org_name: string }> }>(request, "/api/auth/me");
    const orgId = me.memberships.find((m) => m.org_name === TELCO_A)?.org_id;
    expect(orgId, `${TELCO_A} from the demo seed`).toBeTruthy();
    const read = async () =>
      (await getJson<{ items: Array<{ proposal_id: string }> }>(request, `/api/orgs/${orgId}/shortlist`)).items.map((i) => i.proposal_id);
    let ids = await read();
    let added: string | null = null;
    if (ids.length < 2) {
      const inbox = await getJson<{ items: Array<{ proposal: { id: string }; shortlisted: boolean }> }>(request, `/api/orgs/${orgId}/inbox`);
      const next = inbox.items.find((item) => !item.shortlisted && !ids.includes(item.proposal.id));
      expect(next, "an Inbox proposal to star for Compare").toBeTruthy();
      const { csrf_token } = await getJson<{ csrf_token: string }>(request, "/api/auth/csrf");
      const response = await request.put(`/api/orgs/${orgId}/shortlist/${next!.proposal.id}`, { headers: { "X-CSRF-Token": csrf_token } });
      expect(response.ok(), `star an Inbox proposal: ${response.status()}`).toBeTruthy();
      added = next!.proposal.id;
      ids = await read();
    }
    return { orgId: orgId!, ids, added };
  });
  return shortlisted;
}

// --- The P22-A scene: a developer who has not played today's five (docs/platform/tasks/P22.md A) ------------------

/** A new test developer, signed in through the emailed link; the demo accounts have all played today's set. */
async function quizNewcomer(browser: Browser): Promise<string> {
  const context = await browser.newContext({ baseURL: baseUrl() });
  try {
    const page = await context.newPage();
    await signUpDeveloper(page, "Wanjiku Mwangi");
    const dir = join(__dirname, "..", "test-results", "design-shots");
    mkdirSync(dir, { recursive: true });
    const file = join(dir, "state-quizDev.json");
    await context.storageState({ path: file });
    return file;
  } finally {
    await context.close();
  }
}

/** The play form, hydrated (a radio answered on the server's HTML would be lost). */
async function quizForm(page: Page) {
  const today = await page.request.get("/api/me/quiz/today");
  if (!today.ok()) return false;
  const { attempt } = (await today.json()) as { attempt: unknown };
  if (attempt) return false;
  await page.locator("form[data-quiz-play]").waitFor();
  await expect(page.getByRole("group")).toHaveCount(5);
  await page.waitForLoadState("networkidle");
  return true;
}

/** A thread's island, hydrated. */
async function threadShown(page: Page) {
  await page.locator("[data-thread][data-hydrated='true']").waitFor();
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
  { name: "editor-checks", set: "p19", path: "/dev/ideas", who: TEASER_WHO, prepare: async (page) => {
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
  // The queue while the Brief waits, scrolled to its row: "Brief by Telco A (fixture)" (none once it is published).
  { name: "admin-moderation-brief", set: "p19", path: "/admin/moderation", who: "moderator", viewportOnly: true, prepare: async (page, browser) => {
      const brief = await postedBrief(browser);
      if (brief.published) return false;
      await page.reload({ waitUntil: "networkidle" });
      const row = page.locator("[data-case]").filter({ hasText: brief.title });
      await row.waitFor();
      await row.evaluate((element) => element.scrollIntoView({ block: "center" }));
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
      // A page opened with the plan's Briefs in use shows that in place of the form: that is the refusal to shoot.
      const form = page.locator("form[data-brief-form][data-hydrated='true']");
      const capFull = page.getByText(/Every open Brief your plan allows is in use/);
      await form.or(capFull).first().waitFor();
      if (await capFull.isVisible()) return;
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

  // The tracker's side states (REQ-ENG-10), in the order the scene moves: asked, answered, a sheet of each kind, on
  // hold, then the History after an early resume. EXPIRED is left out: only moving the shared test clock reaches it.
  { name: "tracker-info-requested-org", set: "p19", path: "/org/engagements", who: "sideOrg", prepare: async (page, browser) => {
      const scene = await sideScene(browser);
      await page.goto(`/org/engagements/${scene.id}`, { waitUntil: "networkidle" });
      await page.locator("[data-whose-turn] [data-side='info']").waitFor();
      await actionsReady(page);
    } },
  { name: "tracker-info-requested-dev", set: "p19", path: "/dev/engagements", who: "sideDev", prepare: async (page, browser) => {
      const scene = await sideScene(browser);
      await page.goto(`/dev/engagements/${scene.id}`, { waitUntil: "networkidle" });
      await page.locator("[data-whose-turn] [data-info-clock]").waitFor();
      await actionsReady(page);
    } },
  { name: "tracker-answered", set: "p19", path: "/dev/engagements", who: "sideDev", prepare: async (page, browser) => {
      const scene = await answeredSide(browser);
      await page.goto(`/dev/engagements/${scene.id}`, { waitUntil: "networkidle" });
      await page.locator("[data-whose-turn] [data-side='answered']").waitFor();
    } },
  { name: "sheet-request-information", set: "p19", path: "/org/engagements", who: "sideOrg", viewportOnly: true, prepare: async (page, browser) => {
      const scene = await answeredSide(browser);
      await page.goto(`/org/engagements/${scene.id}`, { waitUntil: "networkidle" });
      const sheet = await openSideSheet(page, "Request information");
      await sheet.getByLabel("Your question").fill(SIDE.nextQuestion);
      await sheet.getByText(`${SIDE.nextQuestion.length} of 2,000 characters`).waitFor();
    } },
  { name: "sheet-pause", set: "p19", path: "/org/engagements", who: "sideOrg", viewportOnly: true, prepare: async (page, browser) => {
      const scene = await answeredSide(browser);
      await page.goto(`/org/engagements/${scene.id}`, { waitUntil: "networkidle" });
      const sheet = await openSideSheet(page, "Pause this engagement");
      await sheet.getByLabel("Reason").fill(SIDE.holdReason);
      await sheet.getByLabel("Resumes on").fill(plusDays(await appToday(page.request), 7));
      await sheet.locator("[data-resumes]").filter({ hasText: "It resumes by itself on" }).waitFor();
    } },
  { name: "tracker-on-hold", set: "p19", path: "/dev/engagements", who: "sideDev", prepare: async (page, browser) => {
      const scene = await pausedSide(browser);
      await page.goto(`/dev/engagements/${scene.id}`, { waitUntil: "networkidle" });
      await page.locator("[data-whose-turn] [data-side='hold']").waitFor();
    } },
  { name: "history-side-states", set: "p19", path: "/dev/engagements", who: "sideDev", prepare: async (page, browser) => {
      const scene = await resumedSide(browser);
      await page.goto(`/dev/engagements/${scene.id}?tab=history`, { waitUntil: "networkidle" });
      await page.locator("[data-event='resume'] [data-note='resume']").waitFor();
    } },

  // --- P21 (docs/platform/tasks/P21.md), into docs/demo/screenshots/p21/ ------------------------------------------
  // The seed's thread on Amina's engagement with SACCO B, from both sides.
  { name: "messages-dev", set: "p21", path: "/dev/engagements", who: "dev", prepare: async (page) => {
      const id = await engagementOf(page, SACCO_B, (state) => !ENDED.has(state));
      if (!id) return false;
      await page.goto(`/dev/engagements/${id}/messages`, { waitUntil: "networkidle" });
      await threadShown(page);
      await page.locator("[data-message]").first().waitFor();
    } },
  { name: "messages-org", set: "p21", path: "/org/engagements", who: "orgSacco", prepare: async (page) => {
      const me = await getJson<{ memberships: Array<{ org_id: string; org_name: string }> }>(page.request, "/api/auth/me");
      const orgId = me.memberships.find((m) => m.org_name === SACCO_B)?.org_id;
      if (!orgId) return false;
      const { items } = await getJson<{ items: Array<{ id: string; state: string; developer_name: string }> }>(
        page.request,
        `/api/orgs/${orgId}/engagements`,
      );
      const id = items.find((e) => e.developer_name === PEOPLE.dev.name && !ENDED.has(e.state))?.id;
      if (!id) return false;
      await page.goto(`/org/engagements/${id}/messages`, { waitUntil: "networkidle" });
      await threadShown(page);
      await page.locator("[data-message]").first().waitFor();
    } },
  // Before Approve to proceed: Brian's pitch to Telco A, at SUBMITTED, from both sides.
  { name: "messages-not-open-org", set: "p21", path: "/org/engagements", who: "org", prepare: async (page) => {
      const id = await submittedAtTelcoA(page);
      if (!id) return false;
      await page.goto(`/org/engagements/${id}/messages`, { waitUntil: "networkidle" });
      await page.locator("[data-thread-closed='not_open']").waitFor();
    } },
  { name: "messages-not-open-dev", set: "p21", path: "/dev/engagements", who: "devBrian", prepare: async (page) => {
      const id = await engagementOf(page, TELCO_A, (state) => state === "SUBMITTED");
      if (!id) return false;
      await page.goto(`/dev/engagements/${id}/messages`, { waitUntil: "networkidle" });
      await page.locator("[data-thread-closed='not_open']").waitFor();
    } },
  { name: "history-messages", set: "p21", path: "/dev/engagements", who: "dev", prepare: async (page) => {
      const id = await engagementOf(page, SACCO_B, (state) => !ENDED.has(state));
      if (!id) return false;
      await page.goto(`/dev/engagements/${id}?tab=history`, { waitUntil: "networkidle" });
      await page.locator("[data-history-message]").first().waitFor();
    } },
  // The Inbox's stars, the proposal page's star, the Shortlist and Compare, as Telco A's reviewer.
  { name: "org-inbox-star", set: "p21", path: "/org/inbox", who: "org", prepare: async (page, browser) => {
      await shortlistScene(browser);
      await page.reload({ waitUntil: "networkidle" });
      await page.locator("[data-shortlist='on'], [data-shortlisted]").first().waitFor();
    } },
  { name: "org-proposal-star", set: "p21", path: "/org/inbox", who: "org", viewportOnly: true, prepare: async (page, browser) => {
      const scene = await shortlistScene(browser);
      const inbox = await getJson<{ items: Array<{ proposal: { id: string } }> }>(page.request, `/api/orgs/${scene.orgId}/inbox`);
      const id = scene.ids.find((pid) => inbox.items.some((item) => item.proposal.id === pid));
      if (!id) return false;
      await page.goto(`/org/inbox/${id}`, { waitUntil: "networkidle" });
      await page.locator("[data-shortlist='on']").waitFor();
    } },
  { name: "org-shortlist", set: "p21", path: "/org/inbox/shortlist", who: "org", prepare: async (page, browser) => {
      await shortlistScene(browser);
      await page.reload({ waitUntil: "networkidle" });
      await page.locator("[data-shortlist-entry]").nth(1).waitFor();
    } },
  { name: "org-compare", set: "p21", path: "/org/inbox/shortlist", who: "org", prepare: async (page, browser) => {
      const scene = await shortlistScene(browser);
      await page.goto(`/org/inbox/shortlist/compare?ids=${scene.ids.slice(0, 4).join(",")}`, { waitUntil: "networkidle" });
      await page.locator("[data-tier1-note]").waitFor();
    } },
  // Discover with Amina's saved search: the list open, then the save form.
  { name: "discover-saved", set: "p21", path: "/dev/discover", who: "dev", prepare: async (page) => {
      const strip = page.locator("[data-saved-searches]");
      await strip.getByRole("button", { name: /^Saved searches \(\d+\)$/ }).click();
      await strip.getByRole("listitem").first().waitFor();
    } },
  { name: "discover-save-form", set: "p21", path: "/dev/discover?niche=agriculture&county=KE-32", who: "dev", prepare: async (page) => {
      const strip = page.locator("[data-saved-searches]");
      await strip.getByRole("button", { name: "Save this search" }).click();
      await strip.getByRole("textbox", { name: "Name" }).waitFor();
    } },
  // The two new rows: N18 (a new message) and the saved-search email, on both sides.
  { name: "settings-notifications-dev", set: "p21", path: "/settings/notifications", who: "dev", prepare: async (page) => {
      await page.locator('[data-hydrated="true"]').first().waitFor().catch(() => undefined);
    } },
  { name: "settings-notifications-org", set: "p21", path: "/settings/notifications", who: "orgSacco", prepare: async (page) => {
      await page.locator('[data-hydrated="true"]').first().waitFor().catch(() => undefined);
    } },
  // A reported message in the moderation console: only one a party already reported (the shots report nothing).
  { name: "admin-moderation-message", set: "p21", path: "/admin/moderation", who: "moderator", prepare: async (page) => {
      const cases = await getJson<{ items: Array<{ id: string; subject_type: string; status: string }> }>(page.request, "/api/admin/moderation/cases");
      const open = cases.items.find((c) => c.subject_type === "message" && c.status === "open");
      if (!open) return false;
      await page.goto(`/admin/moderation/cases/${open.id}`, { waitUntil: "networkidle" });
      await page.locator("[data-message-body]").waitFor();
    } },

  // --- P22-A (docs/platform/tasks/P22.md A, Today's five), into docs/demo/screenshots/p22a/ -------------------------
  // Home's card: played (Amina's score, streak and marks), then not played (a new developer: one sentence and Play).
  { name: "home-quiz-played", set: "p22a", path: "/dev", who: "dev", prepare: async (page) => {
      if (!(await page.locator("[data-home=quiz] [data-quiz-card=played]").isVisible())) return false;
    } },
  { name: "home-quiz-play", set: "p22a", path: "/dev", who: "quizDev", prepare: async (page) => {
      if (!(await page.locator("[data-home=quiz] [data-quiz-card=play]").isVisible())) return false;
    } },
  // The five questions, none answered, then two (the "Check 2, skip 3" line appears); never sent.
  { name: "quiz-play", set: "p22a", path: "/dev/quiz", who: "quizDev", prepare: async (page) => {
      if (!(await quizForm(page))) return false;
    } },
  { name: "quiz-play-partial", set: "p22a", path: "/dev/quiz", who: "quizDev", prepare: async (page) => {
      if (!(await quizForm(page))) return false;
      const groups = page.getByRole("group");
      await expect(async () => {
        await groups.nth(0).getByRole("radio").nth(1).check();
        await groups.nth(1).getByRole("radio").nth(2).check();
        await expect(page.locator("[data-quiz-progress]")).toHaveText("2 of 5 answered", { timeout: 2_000 });
      }).toPass({ timeout: 20_000 });
      await page.locator("[data-quiz-skip]").waitFor();
      await page.mouse.move(0, 0);
    } },
  // Amina's results: the score, the streak, every why with its source and Flag; then one question's flag sheet (not sent).
  { name: "quiz-results", set: "p22a", path: "/dev/quiz", who: "dev", prepare: async (page) => {
      if ((await page.locator("[data-why]").count()) === 0) return false;
      await expect(page.locator("[data-why]")).toHaveCount(5);
    } },
  { name: "quiz-flag", set: "p22a", path: "/dev/quiz", who: "dev", viewportOnly: true, prepare: async (page) => {
      const open = page.locator("[data-flag-open]").first();
      if (!(await open.isVisible())) return false;
      const sheet = page.locator("dialog[open][data-sheet]");
      await expect(async () => {
        await open.click();
        await expect(sheet).toBeVisible({ timeout: 2_000 });
      }).toPass({ timeout: 20_000 });
      await page.mouse.move(0, 0);
    } },
  // This week's board: Brian, off it (his own row only); Amina, on it.
  { name: "quiz-board-out", set: "p22a", path: "/dev/quiz/board", who: "devBrian", prepare: async (page) => {
      if (!(await page.locator("[data-opt-in=off]").isVisible())) return false;
    } },
  { name: "quiz-board-in", set: "p22a", path: "/dev/quiz/board", who: "dev", prepare: async (page) => {
      if (!(await page.locator("[data-opt-in=on]").isVisible())) return false;
    } },
  // The staff admin's queue, then an approved set's page (nothing is decided, pulled or restored).
  { name: "admin-quiz", set: "p22a", path: "/admin/quiz", who: "staff", prepare: async (page) => {
      await page.getByRole("heading", { level: 1 }).waitFor();
    } },
  { name: "admin-quiz-set", set: "p22a", path: "/admin/quiz", who: "staff", prepare: async (page) => {
      const row = page.locator("[data-quiz-set][data-status=approved]").first();
      if (!(await row.isVisible())) return false;
      await row.getByRole("link").first().click();
      await page.waitForURL(/\/admin\/quiz\/[^/]+$/);
      await page.locator("[data-admin-question]").first().waitFor();
    } },
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
