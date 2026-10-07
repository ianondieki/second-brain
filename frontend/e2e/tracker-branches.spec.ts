import { expect, test, type APIRequestContext, type Browser, type Locator, type Page, type TestInfo } from "@playwright/test";

import { appToday, plusDays } from "./support/clock";
import { checkScreen } from "./support/screen";
import { actionsReady, OWNER_DATABASE_URL, ownerSql, pitchFromDeveloper, post, signUpOrg, type DevSide, type OrgSide } from "./support/tracker-scene";

// REQ-ENG-10 part (AC-TRACK-4 part; docs/spec/06 6.9 side branches): the tracker's side states walked by both parties
// in their own browsers against the compose stack: a question and its answer, a hold and an early resume, a question
// withdrawn (and one refused for its contact details), each said in the pinned whose-turn banner on the stage where
// it occurred, never as an extra step, with the texts on the History tab; strict axe, one primary action and no
// horizontal scroll with each sheet open (mobile-360 and desktop).
//
// The test-clock scenarios (a question answered days later moves the deadline; a question left unanswered expires)
// move the shared clock forward for the whole database, which every date-relative spec run alongside would feel (a
// contact-by date computed from the real day, the demo seed's open engagements expiring). They run only with
// E2E_TEST_CLOCK=1, on their own after the rest of the suite (`E2E_TEST_CLOCK=1 npx playwright test
// tracker-branches -g "test clock" --workers=1`), on a stack whose clock may move (APP_ENV dev or test, the seed run).
// The expiry pass is the worker's job `engagements.expire` (bridge/jobs/expiry.py), deferred at once through
// Procrastinate's own SQL function rather than waiting for its 15-minute schedule.
//
// Needs E2E_DATABASE_OWNER_URL and an API with FEATURE_DEALS_ENABLED=true and FEATURE_TIER2_ENABLED=true, like
// tracker.spec.ts.

const SERVER_STEP = { timeout: 20_000 };
const DONE = "Done. The tracker is up to date.";
const CONTACT_REFUSAL =
  "Contact details stay out of the tracker until first contact is made; please remove the email, phone number or link.";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
});

interface Scene {
  dev: DevSide;
  org: OrgSide;
  devPage: Page;
  orgPage: Page;
  close: () => Promise<void>;
}

/** The developer on the test's page, the organisation in its own browser context; the review started. */
async function scene(page: Page, browser: Browser, info: TestInfo): Promise<Scene> {
  const orgContext = await browser.newContext({ ...info.project.use });
  const orgPage = await orgContext.newPage();
  const org = await signUpOrg(orgPage.request);
  const dev = await pitchFromDeveloper(page.request, org.orgId);
  await orgPage.goto(`/org/engagements/${dev.engagementId}`);
  await step(orgPage, "Start the review");
  return { dev, org, devPage: page, orgPage, close: () => orgContext.close() };
}

const banner = (page: Page) => page.locator("[data-whose-turn]");
const stepper = (page: Page) => page.getByRole("list", { name: "Stages" });
const actions = (page: Page) => page.locator("[data-actions]");

/** Presses one of the caller's buttons and waits until the step ran and the tracker refreshed. */
async function step(page: Page, name: string) {
  await actionsReady(page);
  await actions(page).getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
}

/** Opens a side state's sheet (a modal dialog; a bottom sheet on phones) from the caller's buttons. */
async function openSheet(page: Page, name: string) {
  await actionsReady(page);
  await actions(page).getByRole("button", { name, exact: true }).click();
  const sheet = page.locator("dialog[open][data-side-sheet]");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByRole("heading", { level: 2 })).toHaveText(name);
  return sheet;
}

/** Sends the open sheet with `submit`, checks the page rules first, and waits for the refreshed tracker. */
async function send(page: Page, submit: string) {
  const sheet = page.locator("dialog[open][data-side-sheet]");
  await checkScreen(page, { strict: true });
  await sheet.getByRole("button", { name: submit, exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
  await expect(page.locator("dialog[open]")).toHaveCount(0);
}

interface Due {
  due_on: string;
  business_days_left: number;
}

/** Calendar days from one ISO day to another ("2026-10-09" to "2026-10-26": 17). */
function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/** The engagement's countdown as the API sends it (Kenyan business days from the app's today to the due day). */
async function dueOf(request: APIRequestContext, id: string): Promise<Due> {
  const response = await request.get(`/api/engagements/${id}`);
  expect(response.ok()).toBeTruthy();
  const due = ((await response.json()) as { due: Due | null }).due;
  expect(due, "a stage deadline").not.toBeNull();
  return due!;
}

/** The time a countdown shows, in minutes, from its <time>'s ISO 8601 duration ("P6DT14H23M"). */
function shownMinutes(duration: string): number {
  const match = /^P(\d+)DT(\d+)H(\d+)M$/.exec(duration);
  expect(match, `a duration in "${duration}"`).not.toBeNull();
  return (Number(match![1]) * 24 + Number(match![2])) * 60 + Number(match![3]);
}

/**
 * P23-3 (REQ-TRACK-03): a countdown on the page counts to the API's `due_at` from the API's own clock (X-App-Now),
 * not the browser's: its <time>'s duration is the minutes between the two, read just before the page was drawn (a
 * minute or two apart at most), and its title the full instant.
 */
async function expectCountdown(page: Page, timer: Locator, id: string) {
  const response = await page.request.get(`/api/engagements/${id}`);
  expect(response.ok()).toBeTruthy();
  const stamp = response.headers()["x-app-now"];
  expect(stamp, "the API stamps its clock on every response").toBeTruthy();
  const due = ((await response.json()) as { due: (Due & { due_at: string }) | null }).due!;
  const expected = Math.floor((Date.parse(due.due_at) - Date.parse(stamp)) / 60_000);
  await page.reload();
  await expect(timer.locator("time")).toHaveAttribute("title", /EAT$/);
  const shown = shownMinutes((await timer.locator("time").getAttribute("datetime")) ?? "");
  expect(Math.abs(expected - shown), `${shown} minutes shown, ${expected} expected`).toBeLessThanOrEqual(2);
  return shown;
}

const homeTimer = (page: Page) => page.locator("[data-stat='deadline'] [data-timer]");
const bannerTimer = (page: Page) => banner(page).locator("[data-timer]");

test("the deadline counts down in days, hours and minutes on Home and the tracker, from the API's clock", async ({ page, browser }, info) => {
  test.setTimeout(120_000);
  const { dev, devPage, orgPage, close } = await scene(page, browser, info);
  try {
    // The review is the organisation's step: the countdown is said to both parties, warm for neither on the developer's side.
    await devPage.goto("/dev");
    await expectCountdown(devPage, homeTimer(devPage), dev.engagementId);
    await expect(homeTimer(devPage)).toHaveText(/^in (\d+ days? )?(\d+ h )?\d+ min$/);
    await expect(devPage.locator("[data-stat='deadline']")).toHaveAttribute("title", /business day/);
    await checkScreen(devPage, { strict: true });
    await devPage.goto(`/dev/engagements/${dev.engagementId}`);
    await expectCountdown(devPage, bannerTimer(devPage), dev.engagementId);
    // One deadline, said once: the figure's secondary line carries the date and the time left.
    await expect(bannerTimer(devPage)).toHaveText(/^Due \d{1,2} \w{3} \d{4} · in /);
    await expect(bannerTimer(devPage)).not.toHaveAttribute("data-timer", "warm");
    await orgPage.goto(`/org/engagements/${dev.engagementId}`);
    await expectCountdown(orgPage, bannerTimer(orgPage), dev.engagementId);
    // No live region: a ticking figure is never announced.
    await expect(banner(orgPage).locator("[aria-live]")).toHaveCount(0);
    await checkScreen(orgPage, { strict: true });
  } finally {
    await close();
  }
});

test("the organisation asks a question, the developer answers it, both read it in the History", async ({ page, browser }, info) => {
  test.setTimeout(180_000);
  const { dev, org, devPage, orgPage, close } = await scene(page, browser, info);
  const question = "Which co-ops ran the pilot?\nA rough count of litres a day is enough.";
  const answer = "Kipkelion and Olenguruone, about 1,200 litres a day over six weeks.";
  try {
    // Escape closes a sheet and gives focus back to its button.
    await openSheet(orgPage, "Request information");
    await orgPage.keyboard.press("Escape");
    await expect(orgPage.locator("dialog[open]")).toHaveCount(0);
    await expect(actions(orgPage).getByRole("button", { name: "Request information", exact: true })).toBeFocused();

    const ask = await openSheet(orgPage, "Request information");
    await expect(ask).toContainText("two questions at this stage");
    await expect(ask).toContainText("Questions left at this stage: 2");
    await expect(ask.getByLabel("Your question")).toBeFocused();
    await ask.getByLabel("Your question").fill(question);
    await expect(ask).toContainText(`${question.length} of 2,000 characters`);
    await checkScreen(orgPage, { strict: true });
    // While the request is in flight the sheet's buttons and Escape do nothing (the request is held until checked).
    let release: () => void = () => {};
    const held = new Promise<void>((resolve) => (release = resolve));
    await orgPage.route("**/api/engagements/*/request-info", async (route) => {
      await held;
      await route.continue();
    });
    await ask.getByRole("button", { name: "Send the question", exact: true }).click();
    await expect(ask.getByRole("button", { name: "Working…" })).toHaveAttribute("aria-disabled", "true");
    await expect(ask.getByRole("button", { name: "Cancel" })).toHaveAttribute("aria-disabled", "true");
    await orgPage.keyboard.press("Escape");
    // Cancel is aria-disabled while the request is in flight: a forced click (Playwright would otherwise wait for it
    // to be enabled, which only the release below allows) must do nothing.
    await ask.getByRole("button", { name: "Cancel" }).click({ force: true });
    await expect(ask).toBeVisible();
    release();
    await expect(orgPage.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
    await expect(orgPage.locator("dialog[open]")).toHaveCount(0);
    await orgPage.unroute("**/api/engagements/*/request-info");

    // The organisation waits on the developer; the review stays the current step, on hold.
    await expect(banner(orgPage)).toContainText("Awaiting: ");
    await expect(banner(orgPage).locator("[data-side='info']")).toContainText("Which co-ops ran the pilot?");
    await expect(banner(orgPage)).toContainText("Answer the question");
    await expect(stepper(orgPage).locator("[aria-current='step']")).toHaveAttribute("data-state", "onHold");
    await expect(stepper(orgPage).locator("[aria-current='step']")).toContainText("Review");
    await expect(stepper(orgPage).getByRole("listitem")).toHaveCount(5);
    await expect(actions(orgPage).getByRole("button")).toHaveText(["Withdraw the question"]);
    await checkScreen(orgPage, { strict: true });

    await devPage.goto(`/dev/engagements/${dev.engagementId}`);
    await expect(banner(devPage)).toContainText("Awaiting: you");
    await expect(banner(devPage).locator("[data-info-clock]")).toContainText("Unanswered by");
    await expect(devPage.locator("[data-primary]")).toHaveText("Answer the question");
    await checkScreen(devPage, { strict: true });
    const reply = await openSheet(devPage, "Answer the question");
    await expect(reply.locator("[data-question]")).toHaveText(question);
    await expect(reply.getByLabel("Your answer")).toBeFocused();
    await reply.getByLabel("Your answer").fill(answer);
    await send(devPage, "Send the answer");

    await expect(banner(devPage).locator("[data-side='answered']")).toContainText(answer);
    await expect(banner(devPage)).toContainText(`Awaiting: ${org.orgName}`);
    await expect(stepper(devPage).locator("[aria-current='step']")).toHaveAttribute("data-state", "current");
    await expect(stepper(devPage).locator("[aria-current='step']")).toContainText("Now: Under review");

    // The History: both texts under their events, the same list for both parties (AC-TRACK-3).
    await devPage.goto(`/dev/engagements/${dev.engagementId}?tab=history`);
    await orgPage.goto(`/org/engagements/${dev.engagementId}?tab=history`);
    await expect(devPage.locator("[data-event='request_info'] [data-note='info_request']")).toContainText("Which co-ops ran the pilot?");
    await expect(devPage.locator("[data-event='answer_info'] [data-note='info_answer']")).toContainText(answer);
    // Both parties read the same events and notes; the developer is their handle to the organisation until contact
    // is agreed (docs/spec/06 6.9) and their own name to themselves, so only the names differ.
    const orgHistory = await orgPage.locator("[data-event]").allTextContents();
    const devHistory = await devPage.locator("[data-event]").allTextContents();
    expect(orgHistory.map((text) => text.replace(dev.handle, dev.name))).toEqual(devHistory);
    expect(orgHistory.join("\n")).not.toContain(dev.name);
    await checkScreen(devPage, { strict: true });
  } finally {
    await close();
  }
});

test("either party pauses before the agreement and the other resumes it early", async ({ page, browser }, info) => {
  test.setTimeout(180_000);
  const { dev, org, devPage, orgPage, close } = await scene(page, browser, info);
  try {
    const resumeAt = plusDays(await appToday(orgPage.request), 10);
    const pause = await openSheet(orgPage, "Pause this engagement");
    await expect(pause).toContainText("at most 60 days ahead");
    await pause.getByLabel("Reason").fill("Our budget committee meets next week");
    await pause.getByLabel("Resumes on").fill(resumeAt);
    await expect(pause.locator("[data-resumes]")).toContainText("It resumes by itself on");
    await send(orgPage, "Pause until then");

    await expect(banner(orgPage)).toContainText("This engagement is on hold.");
    await expect(banner(orgPage).locator("[data-side='hold']")).toContainText("You paused this engagement until");
    await expect(stepper(orgPage).locator("[aria-current='step']")).toHaveAttribute("data-state", "onHold");

    await devPage.goto(`/dev/engagements/${dev.engagementId}`);
    await expect(banner(devPage).locator("[data-side='hold']")).toContainText(`Paused by ${org.orgName} until`);
    await expect(banner(devPage).locator("[data-side='hold']")).toContainText("Our budget committee meets next week");
    await expect(devPage.locator("[data-primary]")).toHaveCount(0); // nobody's turn while on hold
    await checkScreen(devPage, { strict: true });
    const resume = await openSheet(devPage, "Resume now");
    await expect(resume).toContainText("It was due to resume on");
    await resume.getByLabel("Reason for resuming now").fill("The committee met early");
    await send(devPage, "Resume now");

    await expect(banner(devPage)).toContainText(`Awaiting: ${org.orgName}`);
    await expect(stepper(devPage).locator("[aria-current='step']")).toContainText("Now: Under review");
    await devPage.goto(`/dev/engagements/${dev.engagementId}?tab=history`);
    await expect(devPage.locator("[data-event='pause'] [data-note='hold']")).toContainText("Our budget committee meets next week");
    await expect(devPage.locator("[data-event='resume'] [data-note='resume']")).toContainText("The committee met early");
  } finally {
    await close();
  }
});

test("a question with contact details is refused in words; the organisation withdraws the one it sent", async ({ page, browser }, info) => {
  test.setTimeout(180_000);
  const { dev, org, devPage, orgPage, close } = await scene(page, browser, info);
  try {
    const ask = await openSheet(orgPage, "Request information");
    await ask.getByLabel("Your question").fill("Please write to desk@example.com or call 0712 345 678 about the pilot.");
    await ask.getByRole("button", { name: "Send the question", exact: true }).click();
    // The refusal sits on the field (aria-invalid, aria-describedby), which keeps the focus; the text is kept to edit.
    await expect(ask.getByText(CONTACT_REFUSAL)).toBeVisible(SERVER_STEP);
    await expect(ask.getByLabel("Your question")).toHaveAttribute("aria-invalid", "true");
    await expect(ask.getByLabel("Your question")).toBeFocused();
    await expect(ask.getByLabel("Your question")).toHaveValue(/0712 345 678/); // kept, to be edited
    await checkScreen(orgPage, { strict: true });
    await ask.getByLabel("Your question").fill("How many co-ops ran the pilot?");
    await send(orgPage, "Send the question");

    const withdraw = await openSheet(orgPage, "Withdraw the question");
    await expect(withdraw.getByRole("button", { name: "Cancel" })).toBeFocused();
    await expect(withdraw).toContainText("still counts towards the two this stage allows");
    await send(orgPage, "Withdraw the question");
    await expect(banner(orgPage)).toContainText("Awaiting: you");
    await expect(banner(orgPage).locator("[data-side]")).toHaveCount(0);
    await expect(stepper(orgPage).locator("[aria-current='step']")).toHaveAttribute("data-state", "current");

    await devPage.goto(`/dev/engagements/${dev.engagementId}?tab=history`);
    await expect(devPage.locator("[data-event='cancel_request']")).toContainText("Question withdrawn");
    await devPage.goto(`/dev/engagements/${dev.engagementId}`);
    await expect(banner(devPage)).toContainText(`Awaiting: ${org.orgName}`);
    await expect(actions(devPage).getByRole("button", { name: "Answer the question" })).toHaveCount(0);
  } finally {
    await close();
  }
});

test.describe("on the test clock", () => {
  test.describe.configure({ mode: "serial" });
  test.skip(!process.env.E2E_TEST_CLOCK, "moves the shared clock: run alone with E2E_TEST_CLOCK=1 (see the file's header)");

  async function advance(request: APIRequestContext, days: number) {
    await post(request, "/api/test-clock/advance", { days });
  }

  /** One pass of the worker's clock job now (bridge/jobs/expiry.py), instead of its 15-minute schedule. */
  function runClockJob() {
    ownerSql(
      "SELECT (procrastinate_defer_jobs_v1(ARRAY[ROW(CAST('engagements' AS varchar), CAST('engagements.expire' AS varchar)," +
        " 0, CAST('engagements:expire' AS text), CAST(NULL AS text)," +
        " jsonb_build_object('timestamp', floor(extract(epoch FROM now()))::bigint), CAST(NULL AS timestamptz))" +
        "::procrastinate_job_to_defer_v1]))[1];",
      {},
    );
  }

  test("a question answered days later keeps the review's business days: its deadline moved by the days it was open", async ({ page, browser }, info) => {
    test.setTimeout(180_000);
    const { dev, devPage, orgPage, close } = await scene(page, browser, info);
    try {
      const before = await dueOf(orgPage.request, dev.engagementId);
      const ask = await openSheet(orgPage, "Request information");
      await ask.getByLabel("Your question").fill("Which co-ops ran the pilot?");
      await send(orgPage, "Send the question");
      await advance(orgPage.request, 7); // at least four Kenyan business days, whatever the holidays

      await devPage.goto(`/dev/engagements/${dev.engagementId}`);
      const reply = await openSheet(devPage, "Answer the question");
      await reply.getByLabel("Your answer").fill("Kipkelion and Olenguruone.");
      await send(devPage, "Send the answer");
      await expect(banner(devPage).locator("[data-side='answered']")).toBeVisible();

      // The clock was paused while the question was open: the business days left are those the review had when it
      // was asked, so the due day moved by exactly the business days the question was open (holidays included).
      const after = await dueOf(devPage.request, dev.engagementId);
      expect(after.business_days_left, "the review's business days left, unchanged by the pause").toBe(before.business_days_left);
      expect(after.due_on > before.due_on, `${before.due_on} → ${after.due_on}`).toBe(true);
      await expect(banner(devPage).locator("[data-due]")).toContainText(`${after.business_days_left} business days left`);
      await checkScreen(devPage, { strict: true });
    } finally {
      await close();
    }
  });

  test("the countdown follows the moved clock, never the browser's", async ({ page, browser }, info) => {
    test.setTimeout(120_000);
    const { dev, devPage, close } = await scene(page, browser, info);
    try {
      await devPage.goto("/dev");
      const before = await expectCountdown(devPage, homeTimer(devPage), dev.engagementId);
      await advance(devPage.request, 1);
      // The due day is the review's, unchanged; a day less is left on the app clock (the browser's has not moved).
      const after = await expectCountdown(devPage, homeTimer(devPage), dev.engagementId);
      expect(Math.abs(before - after - 24 * 60), `${before} then ${after} minutes`).toBeLessThanOrEqual(3);
    } finally {
      await close();
    }
  });

  test("a question left unanswered past its answer-by date expires the engagement", async ({ page, browser }, info) => {
    test.setTimeout(180_000);
    const { dev, devPage, orgPage, close } = await scene(page, browser, info);
    try {
      const ask = await openSheet(orgPage, "Request information");
      await ask.getByLabel("Your question").fill("Which co-ops ran the pilot?");
      await send(orgPage, "Send the question");
      // To the day after the answer-by date the API sends (ten Kenyan business days from the question, holidays
      // included). A fixed count is not enough: on a fresh demo the question falls on Friday 9 Oct 2026 and Mashujaa
      // Day (Tuesday 20 Oct) puts the answer-by date seventeen days on, so a sixteen-day move left it rightly unexpired.
      const asked = (await (await orgPage.request.get(`/api/engagements/${dev.engagementId}`)).json()) as {
        due: Due | null;
        today?: string | null;
      };
      expect(asked.due, "the question's answer-by date").not.toBeNull();
      const today = asked.today ?? (await appToday(orgPage.request));
      await advance(orgPage.request, daysBetween(today, asked.due!.due_on) + 1);
      runClockJob();
      await expect
        .poll(
          async () =>
            ((await (await devPage.request.get(`/api/engagements/${dev.engagementId}`)).json()) as { state: string }).state,
          { timeout: 60_000 },
        )
        .toBe("EXPIRED");

      await devPage.goto(`/dev/engagements/${dev.engagementId}`);
      await expect(banner(devPage)).toContainText("This engagement has ended.");
      await expect(banner(devPage).locator("[data-side='expired']")).toHaveText("Expired: the developer did not answer in time.");
      await expect(stepper(devPage).locator("[data-state='ended']")).toContainText("Review");
      await expect(actions(devPage)).toHaveCount(0);
      await checkScreen(devPage, { strict: true });
      await devPage.goto(`/dev/engagements/${dev.engagementId}?tab=history`);
      await expect(devPage.locator("[data-event='expire']")).toContainText("Platform");
    } finally {
      await close();
    }
  });
});
