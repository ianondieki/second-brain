import { expect, test, type Page } from "@playwright/test";

import {
  insertCandidate,
  letterTag,
  newDeveloper,
  newStaffAdmin,
  OWNER_DATABASE_URL,
  saccoSources,
  savedExcerpts,
  type SavedExcerpt,
} from "./support/research-scene";
import { checkScreen, expectEmptyState, expectSeparateTargets } from "./support/screen";
import { PASSWORD, type Person } from "./support/tracker-scene";

// REQ-RES-01 and REQ-RES-02 (prototype part; M2 walkthrough step 3): a staff admin signs in, starts a research run,
// reviews a drafted card with its citations and approves it, and the card is then readable by a signed-in developer
// with its sources. Against the compose stack (worker running, fake LLM), in both projects (360 px and desktop).

const SERVER_STEP = { timeout: 20_000 };

async function hydrated(page: Page) {
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
}

async function signIn(page: Page, person: Person) {
  await page.goto("/login");
  await hydrated(page);
  await page.getByLabel("Email address").fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
  await expect(page).toHaveURL(/\/auth\/mfa$/, SERVER_STEP);
  await hydrated(page);
  await page.getByLabel("6-digit code").fill(await person.code());
  await page.getByRole("button", { name: "Continue" }).click();
}

/** What identifies a response before any script runs: its status, <html lang> and <title>, and its text. */
async function rawAnswer(page: Page, path: string) {
  const response = await page.request.get(path, { maxRedirects: 0 });
  const html = await response.text();
  return {
    status: response.status(),
    lang: /<html[^>]*\slang="([^"]*)"/.exec(html)?.[1] ?? null,
    title: /<title>([^<]*)<\/title>/.exec(html)?.[1] ?? null,
  };
}

/** The console answers `page`'s session exactly as an unknown address does, before and after scripts run. */
async function expectUnknownAddress(page: Page, paths: string[]) {
  const unknown = await rawAnswer(page, "/no-such-page-anywhere");
  expect(unknown.status).toBe(404);
  await page.goto("/no-such-page-anywhere");
  const unknownText = await page.locator("body").innerText();
  for (const path of paths) {
    expect(await rawAnswer(page, path), path).toEqual(unknown);
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(404);
    expect(await page.locator("body").innerText(), path).toBe(unknownText);
  }
}

const CONSOLE_PATHS = ["/admin", "/admin/research", "/admin/research/candidates/01a0ee62-f783-733e-9321-9f34ec389ac2"];

test("the staff console answers signed-out visitors and people who are not staff like an unknown address", async ({
  page,
}) => {
  await expectUnknownAddress(page, CONSOLE_PATHS);
  await newDeveloper(page.request);
  await expectUnknownAddress(page, CONSOLE_PATHS);
});

test.describe("a staff admin", () => {
  test.beforeAll(() => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL makes the staff admin and writes the drafted card").toBeTruthy();
  });
  test.setTimeout(150_000);

  test("without two-step sign-in gets the unknown-address answer too, and a portal home", async ({
    page,
    browser,
    baseURL,
  }) => {
    const staff = await newStaffAdmin(browser, baseURL!, { totp: false });
    await page.goto("/login");
    await hydrated(page);
    await page.getByLabel("Email address").fill(staff.email);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByRole("button", { name: "Log in", exact: true }).click();
    await expect(page).toHaveURL(/\/dev$/, SERVER_STEP);
    await expectUnknownAddress(page, CONSOLE_PATHS);
  });

  test("runs research, approves a cited card, and developers can read it", async ({ page, browser, baseURL }, info) => {
    const staff = await newStaffAdmin(browser, baseURL!);

    // Signing in lands on the staff console, which opens Research.
    await signIn(page, staff);
    await expect(page).toHaveURL(/\/admin\/research$/, SERVER_STEP);
    const nav = page.getByRole("navigation", { name: "Staff console" });
    if (info.project.name === "desktop") {
      expect(await nav.getByRole("link").count()).toBeLessThanOrEqual(5); // AC-UX-1
      await expect(nav.getByRole("link", { name: "Research" })).toHaveAttribute("aria-current", "page");
    } else {
      await expect(nav).toBeHidden(); // one section: no tab bar on a phone
    }
    await expect(page.getByRole("heading", { name: "Research", level: 1 })).toBeVisible();
    await checkScreen(page);

    // Start a run (the screen's one primary action). The dev stack's fake LLM gives no usable answer: the run
    // finishes with the demo fallback and no card, and says so.
    const niche = info.project.name === "desktop" ? "Agriculture" : "Health";
    await hydrated(page);
    await page.getByLabel("Niche").selectOption({ label: niche });
    await expect(page.locator("[data-primary]")).toHaveText("Start run");
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status").filter({ hasText: `The ${niche} run has finished.` })).toBeVisible({
      timeout: 45_000,
    });
    const runs = page.getByRole("list", { name: "Recent research runs" });
    await expect(runs.locator("[data-run]").first()).toContainText(niche, SERVER_STEP);
    await expect(runs.locator("[data-run]").first()).toContainText(
      "No card: this run used the demo fallback (no live model answer).",
    );
    await checkScreen(page);

    // The card the run would have drafted, from the saved excerpts: it names SASRA, so it cites SASRA's own site.
    const runId = await page.locator("[data-run]").first().getAttribute("data-run");
    const sources = saccoSources(await savedExcerpts(page.request));
    const tag = letterTag();
    const title = `Saccos need stronger cyber defences, case ${tag}`;
    const problemId = insertCandidate({
      title,
      statement:
        "SASRA is asking regulated saccos to strengthen cyber resilience and protect member funds as more of their" +
        " services go digital.",
      affectedGroup: "Members and staff of deposit-taking saccos",
      namedOrgs: ["SASRA"],
      sources,
      runId: runId ?? undefined,
    });

    // A candidate is on no public page (AC-RES-2): a signed-in developer cannot open it yet.
    const developer = await browser.newContext({ baseURL });
    const devPage = await developer.newPage();
    await newDeveloper(devPage.request);
    await devPage.goto(`/problems/${problemId}`);
    await expectEmptyState(devPage, "This problem is not available.", "Back to home");

    // The card waits for review, with its tags (at most two) and the way in.
    await page.reload();
    const card = page.locator(`[data-candidate="${problemId}"]`);
    await expect(card).toContainText("AI-drafted");
    await expect(card).toContainText("Names an organisation");
    expect(await card.locator("[data-chip]").count()).toBeLessThanOrEqual(2); // AC-UX-1
    await expectSeparateTargets(page.locator("[data-review-link]")); // WCAG 2.2 target size
    await checkScreen(page);
    await card.getByRole("link", { name: title }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/research/candidates/${problemId}$`), SERVER_STEP);

    // The review shows every source with its publisher, date and verbatim quote, and the D-45 checklist.
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    await expectCitations(page, sources);
    await expect(page.getByRole("heading", { name: "Named-organisation checklist" })).toBeVisible();
    await expect(page.locator("[data-checklist] li")).not.toHaveCount(0);
    await expect(page.locator("[data-primary]")).toHaveText("Approve and publish");
    await checkScreen(page);

    // Approving without the checklist is stopped on the page; ticked, the card is published.
    await page.getByRole("button", { name: "Approve and publish" }).click();
    await expect(page.getByText("Tick the checklist before you approve this card.")).toBeVisible();
    await page.getByLabel("I have worked through the checklist above for this card.").check();
    await page.getByRole("button", { name: "Approve and publish" }).click();
    await expect(page.locator('[data-decision="approve"]')).toHaveText(
      "Published. Signed-in people can now see this card and its sources.",
      SERVER_STEP,
    );
    await checkScreen(page);

    // The published card, with its label and citations, for staff and developers alike.
    await page.getByRole("link", { name: "Open the public card" }).click();
    await expect(page).toHaveURL(new RegExp(`/problems/${problemId}$`), SERVER_STEP);
    await expectPublicCard(page, title, sources);
    await checkScreen(page);

    await devPage.goto(`/problems/${problemId}`);
    await expectPublicCard(devPage, title, sources);
    await checkScreen(devPage);
    await developer.close();

    // Decided cards leave the queue, and their review page says so.
    await page.goto(`/admin/research/candidates/${problemId}`);
    await expectEmptyState(page, "This card is no longer waiting for review.", "Back to Research");
  });

  test("sees a failed publish check as a plain sentence, rejects the card, and confirms a stale sign-in", async ({
    page,
    browser,
    baseURL,
  }) => {
    const staff = await newStaffAdmin(browser, baseURL!);
    await signIn(page, staff);
    await expect(page).toHaveURL(/\/admin\/research$/, SERVER_STEP);

    // A source that no longer matches its saved excerpt fails the publish checks (source_not_saved).
    const [official, other] = saccoSources(await savedExcerpts(page.request));
    const tampered = { ...other, quote: `${other.quote} It added more.` };
    const title = `Saccos lose members to digital lenders, case ${letterTag()}`;
    const problemId = insertCandidate({
      title,
      statement: "Regulated saccos are losing younger members to faster digital lenders.",
      affectedGroup: "Deposit-taking saccos",
      namedOrgs: [],
      sources: [official, tampered],
    });

    // A second factor older than 12 hours asks for a fresh code first (ADR-002).
    staff.staleSecondFactor();
    await page.goto(`/admin/research/candidates/${problemId}`);
    await expect(page.locator('[data-refusal="step_up_required"]')).toBeVisible(SERVER_STEP);
    await checkScreen(page);
    await hydrated(page);
    await page.getByLabel("Code from your app").fill(await staff.code());
    await page.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeFocused(SERVER_STEP);

    await page.getByRole("button", { name: "Approve and publish" }).click();
    const refusal = page.locator('[data-refusal="publish.source_not_saved"]');
    await expect(refusal).toHaveText(
      "This card cannot be published: a cited source no longer matches its saved excerpt (link, publisher, date or" +
        " quote). Reject it.",
      SERVER_STEP,
    );
    await expect(page.getByText("source_not_saved")).toHaveCount(0); // never the API's own words
    // The check is final: Reject is now the one primary action and Approve is inert.
    await expect(page.locator("[data-primary]")).toHaveText("Reject");
    await expect(page.getByRole("button", { name: "Approve and publish" })).toHaveAttribute("aria-disabled", "true");
    await checkScreen(page);

    // Reject asks once more, with focus on the question; Cancel gives focus back to Reject.
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    const question = page.getByRole("group", {
      name: "Reject this card? It stays private and cannot be published later.",
    });
    await expect(question).toBeFocused();
    await checkScreen(page);
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("button", { name: "Reject", exact: true })).toBeFocused();
    await page.getByRole("button", { name: "Reject", exact: true }).click();
    await page.getByRole("button", { name: "Reject card" }).click();
    await expect(page.locator('[data-decision="reject"]')).toHaveText("Rejected. The card stays private.", SERVER_STEP);

    // Rejected is private for good: not on the public page, not in the queue.
    await page.goto(`/problems/${problemId}`);
    await expectEmptyState(page, "This problem is not available.", "Back to home");
    await page.goto("/admin/research");
    await expect(page.locator(`[data-candidate="${problemId}"]`)).toHaveCount(0);
  });
});

async function expectCitations(page: Page, sources: SavedExcerpt[]) {
  const citations = page.locator("[data-citation]");
  await expect(citations).toHaveCount(sources.length);
  for (const source of sources) {
    const citation = citations.filter({ hasText: source.quote });
    await expect(citation).toHaveCount(1);
    await expect(citation.locator("blockquote")).toHaveText(source.quote);
    await expect(citation).toContainText(source.publisher);
    await expect(citation.getByRole("link", { name: `Read it at ${source.publisher}` })).toHaveAttribute(
      "href",
      source.url,
    );
  }
}

async function expectPublicCard(page: Page, title: string, sources: SavedExcerpt[]) {
  await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible(SERVER_STEP);
  await expect(page.locator("[data-label]")).toHaveText(/^AI-drafted, human-reviewed on \d{1,2} \w+ \d{4}$/);
  await expect(page.getByText("SASRA", { exact: true })).toBeVisible(); // the named organisation
  await expectCitations(page, sources);
}
