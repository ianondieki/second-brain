import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkWidths, shot } from "./support/discover-scene";
import { OWNER_DATABASE_URL, signUpOrg } from "./support/tracker-scene";

// REQ-DEV-01 (D-59; docs/platform/tasks/P22.md A9) against the demo stack, in both projects: a new developer finds
// Today's five on Home, plays the seeded set, sees the score and every why, flags a question, opts in to this week's
// board and finds their handle on it; an organisation member has no quiz on their Home and is sent home from
// /dev/quiz as from every developer route. Strict axe, one primary action and no sideways scroll on every state, at
// 360 and 375 px (mobile-360) and 1440 px (desktop). E2E_SHOTS_DIR saves screenshots at 375 and 1440 px.
//
// Precondition: an approved set for the current Nairobi day on the stack's clock (the demo seed writes one for the
// day it runs, `make demo` / `make demo-reset`). Without it GET /api/me/quiz/today answers 404 no_quiz and the
// developer test is skipped with that reason. The new developer opts back out of the board at the end, so repeated
// runs never fill this week's top 20.

const SERVER_STEP = { timeout: 20_000 };

// Today's seeded set (backend/src/bridge/seed/demo/quiz.py SEEDED_SETS["today"]): each prompt's right option. An
// unknown prompt is answered with its first option; the score is then whatever it is.
const ANSWERS: Record<string, number> = {
  "How many spaces per indentation level does PEP 8 recommend for Python code?": 2,
  "In Kubernetes, what are the smallest deployable units of computing that you can create and manage?": 1,
  "Which HTTP method does a browser use for a CORS preflight request?": 2,
  "Which defence does the OWASP SQL Injection Prevention Cheat Sheet list first among its primary defences?": 1,
  "Under Rust's ownership rules, how many owners can a value have at one time?": 0,
};

/** Turns the board opt-in on or off through the API (the screen's switch is tested above it). */
async function setOptIn(request: APIRequestContext, value: boolean) {
  const csrf = (await (await request.get("/api/auth/csrf")).json()) as { csrf_token: string };
  const response = await request.put("/api/me/quiz/settings", {
    headers: { "X-CSRF-Token": csrf.csrf_token },
    data: { leaderboard_opt_in: value },
  });
  expect(response.status(), await response.text()).toBe(200);
}

test.describe("Today's five", () => {
  test.setTimeout(150_000);

  test("a new developer plays, reads why, flags one and joins the board", async ({ page }, info) => {
    await signUpDeveloper(page, "Njeri Kamau");
    const profile = await page.request.get("/api/me/profile");
    expect(profile.ok()).toBeTruthy();
    const { handle } = (await profile.json()) as { handle: string };
    const today = await page.request.get("/api/me/quiz/today");
    if (today.status() === 404) {
      const { detail } = (await today.json()) as { detail: { code: string } };
      test.skip(detail.code === "no_quiz", "No approved quiz set for today's Nairobi day on this stack (seed the demo first)");
    }
    expect(today.status()).toBe(200);

    // Home: the card, not played yet: one sentence and Play (Home keeps its own one primary action).
    const card = page.locator("[data-home=quiz]");
    await expect(card.getByRole("heading", { name: "Today's five" })).toBeVisible();
    await expect(card.locator("[data-quiz-card=play]")).toBeVisible();
    await expect(card.locator("[data-primary]")).toHaveCount(0);
    await checkWidths(page, info);
    await shot(page, info, "quiz-home-play");

    // The five questions; Check answers ignores presses until all five are answered.
    await card.getByRole("link", { name: "Play" }).click();
    await expect(page).toHaveURL(/\/dev\/quiz$/, SERVER_STEP);
    const check = page.getByRole("button", { name: "Check answers" });
    await expect(check).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByRole("group")).toHaveCount(5);
    await checkWidths(page, info);
    await shot(page, info, "quiz-play");

    for (const group of await page.getByRole("group").all()) {
      const prompt = ((await group.locator("legend").textContent()) ?? "").trim();
      await group.getByRole("radio").nth(ANSWERS[prompt] ?? 0).check();
    }
    await expect(page.locator("[data-quiz-progress]")).toHaveText("5 of 5 answered");
    await expect(check).not.toHaveAttribute("aria-disabled", "true");
    await check.click();

    // The results: focus on their heading, the score, the marks in words and every why with its source.
    const results = page.getByRole("heading", { name: "Your answers", level: 2 });
    await expect(results).toBeFocused(SERVER_STEP);
    await expect(page.locator("[data-quiz-score]")).toHaveText(/^\d of \d right$/);
    await expect(page.locator("[data-quiz-streak]")).toContainText("1-day streak.");
    await expect(page.locator("[data-why]")).toHaveCount(5);
    await expect(page.locator("[data-mark=rightChosen], [data-mark=wrongChosen]")).toHaveCount(5);
    const source = page.locator("[data-result='1'] [data-source]");
    await expect(source).toHaveAttribute("target", "_blank");
    await expect(source).toHaveAttribute("rel", /noopener/);
    await checkWidths(page, info);
    await shot(page, info, "quiz-results");

    // Flag the first question: the sheet, a reason, Send; the thanks takes the button's place, with focus.
    await page.getByRole("button", { name: "Flag question 1" }).click();
    const sheet = page.getByRole("dialog", { name: "Flag question 1" });
    await expect(sheet).toBeVisible();
    await checkWidths(page, info);
    await shot(page, info, "quiz-flag");
    await sheet.getByRole("radio", { name: "The question is unclear" }).check();
    await sheet.getByRole("textbox", { name: "Note (optional)" }).fill("Spaces or tabs is not asked.");
    await sheet.getByRole("button", { name: "Send" }).click();
    await expect(sheet).toBeHidden(SERVER_STEP);
    const thanks = page.locator("[data-result='1'] [data-flag-outcome]");
    await expect(thanks).toHaveText("Thanks, we'll look.");
    await expect(thanks).toBeFocused();

    // Back on Home the card has the score and the streak.
    await page.goto("/dev");
    await expect(card.locator("[data-quiz-card=played]")).toContainText("today · 1-day streak");
    await checkWidths(page, info);

    // The board: not on it until the switch is on; then ranked, and listed (marked as theirs) when in the top 20.
    try {
      await board(page, info, handle);
    } finally {
      await setOptIn(page.request, false);
    }
  });

  async function board(page: Page, info: TestInfo, handle: string) {
    await page.goto("/dev/quiz/board");
    await expect(page.getByRole("heading", { name: "This week", level: 1 })).toBeVisible();
    await expect(page.locator("[data-board-line]")).toHaveAttribute("data-board-line", "join");
    const optIn = page.getByRole("switch", { name: "Show me on the board" });
    await expect(optIn).toHaveAttribute("aria-checked", "false");
    await checkWidths(page, info);
    await optIn.click();
    await expect(page.getByRole("status").filter({ hasText: "You are on the board." })).toBeVisible(SERVER_STEP);
    await expect(page.locator("[data-board-line]")).toHaveAttribute("data-board-line", "ranked", SERVER_STEP);
    await expect(page.locator("[data-board-line]")).toHaveText(/^You: \d+ points?, rank \d+$/);
    const week = (await (await page.request.get("/api/me/quiz/leaderboard")).json()) as { me: { rank: number | null } };
    const mine = page.locator(`[data-board-row="${handle}"]`);
    if (week.me.rank !== null && week.me.rank <= 20) {
      await expect(mine).toBeVisible(SERVER_STEP);
      await expect(mine).toHaveAttribute("data-you", "");
    } else {
      await expect(mine).toHaveCount(0);
    }
    await page.reload();
    await expect(optIn).toHaveAttribute("aria-checked", "true");
    await checkWidths(page, info);
    await shot(page, info, "quiz-board");
  }

  test("an organisation member has no quiz and is sent home from it", async ({ page }, info) => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL makes the organisation E2").toBeTruthy();
    await signUpOrg(page.request);
    await page.goto("/dev/quiz");
    await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
    await expect(page.locator("[data-home=quiz]")).toHaveCount(0);
    await page.goto("/dev/quiz/board");
    await expect(page).toHaveURL(/\/org$/, SERVER_STEP);
    expect((await page.request.get("/api/me/quiz/today")).status()).toBe(404);
    await checkWidths(page, info);
  });
});
