import { expect, test, type APIRequestContext, type Browser, type Page, type TestInfo } from "@playwright/test";

import { checkScreen } from "./support/screen";
import { OWNER_DATABASE_URL, ownerSql, pitchFromDeveloper, post, signUpOrg, type DevSide, type OrgSide } from "./support/tracker-scene";

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
  "Contact details stay out of the tracker until the organisation approves; please remove the email, phone number or link.";

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
  await actions(page).getByRole("button", { name, exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: DONE })).toBeVisible(SERVER_STEP);
}

/** Opens a side state's sheet (a modal dialog; a bottom sheet on phones) from the caller's buttons. */
async function openSheet(page: Page, name: string) {
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

/** The app's day in Nairobi (the shared test clock, else the real day), as "2026-10-02". */
async function appToday(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/test-clock");
  const now = response.ok() ? new Date(((await response.json()) as { now: string }).now) : new Date();
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(now);
}

function plusDays(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** The banner's due date ("… due 23 Oct 2026") as a time, to compare two of them. */
async function dueAt(page: Page): Promise<number> {
  const text = (await banner(page).locator("[data-due]").textContent()) ?? "";
  const day = /(\d{1,2} \w{3} \d{4})\s*$/.exec(text)?.[1];
  expect(day, text).toBeTruthy();
  return Date.parse(`${day} UTC`);
}

test("the organisation asks a question, the developer answers it, both read it in the History", async ({ page, browser }, info) => {
  test.setTimeout(180_000);
  const { dev, org, devPage, orgPage, close } = await scene(page, browser, info);
  const question = "Which co-ops ran the pilot?\nA rough count of litres a day is enough.";
  const answer = "Kipkelion and Olenguruone, about 1,200 litres a day over six weeks.";
  try {
    const ask = await openSheet(orgPage, "Request information");
    await expect(ask).toContainText("two questions at this stage");
    await expect(ask.getByLabel("Your question")).toBeFocused();
    await ask.getByLabel("Your question").fill(question);
    await expect(ask).toContainText(`${question.length} of 2,000 characters`);
    await send(orgPage, "Send the question");

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
    expect(await orgPage.locator("[data-event]").allTextContents()).toEqual(await devPage.locator("[data-event]").allTextContents());
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
    await expect(ask.getByRole("alert")).toHaveText(CONTACT_REFUSAL, SERVER_STEP);
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

  test("a question answered days later moves the review's deadline by the business days it was open", async ({ page, browser }, info) => {
    test.setTimeout(180_000);
    const { dev, devPage, orgPage, close } = await scene(page, browser, info);
    try {
      const before = await dueAt(orgPage);
      const ask = await openSheet(orgPage, "Request information");
      await ask.getByLabel("Your question").fill("Which co-ops ran the pilot?");
      await send(orgPage, "Send the question");
      await advance(orgPage.request, 7);

      await devPage.goto(`/dev/engagements/${dev.engagementId}`);
      const reply = await openSheet(devPage, "Answer the question");
      await reply.getByLabel("Your answer").fill("Kipkelion and Olenguruone.");
      await send(devPage, "Send the answer");
      await expect(banner(devPage).locator("[data-side='answered']")).toBeVisible();
      expect(await dueAt(devPage), "the deadline moved by the days the question was open").toBeGreaterThan(before);
      await checkScreen(devPage, { strict: true });
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
      await advance(orgPage.request, 16); // past ten business days, whatever the holidays
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
