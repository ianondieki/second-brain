import { redirect } from "next/navigation";

import { forwardHeaders, serverApi } from "@/lib/api/server";

import { isNoQuiz, type QuizBoard, type QuizCardState, type QuizToday } from "./quiz";

// Server-side reads of Today's five (REQ-DEV-01; bridge/quiz/router.py), signed in, developers only. Each is bounded,
// so a hung API ends in the route's error page (or, on Home, in a Home without the card) instead of a page that
// never renders.
const TIMEOUT_MS = 5000;
const HOME = "/dev";

async function options() {
  return { headers: await forwardHeaders(), signal: AbortSignal.timeout(TIMEOUT_MS), cache: "no-store" as const };
}

/**
 * Home's "Today's five" card: today's set, "none" for a day without an approved set (404 no_quiz), or null when the
 * card is left out (any other answer, no answer in time, the network): Home stands without it and never shows the
 * error page for it. Only a lost session (401) leaves Home, to sign in again.
 */
export async function quizCard(): Promise<QuizCardState> {
  let answer;
  try {
    answer = await serverApi().GET("/api/me/quiz/today", await options());
  } catch {
    return null;
  }
  if (answer.data) return { kind: "set", today: answer.data };
  if (answer.response.status === 401) redirect("/login");
  if (isNoQuiz(answer.response.status, answer.error)) return { kind: "none" };
  return null;
}

/**
 * /dev/quiz: today's set, or "none" (404 no_quiz). Any other 404 (an account the quiz is not for, such as staff with
 * a developer profile) goes back to Home, never the error page; anything else is the route's error page.
 */
export async function quizToday(): Promise<{ kind: "set"; today: QuizToday } | { kind: "none" }> {
  const { data, error, response } = await serverApi().GET("/api/me/quiz/today", await options());
  if (data) return { kind: "set", today: data };
  if (response.status === 401) redirect("/login");
  if (isNoQuiz(response.status, error)) return { kind: "none" };
  if (response.status === 404) redirect(HOME);
  throw new Error(`GET /api/me/quiz/today answered ${response.status}`);
}

/** /dev/quiz/board: this week's board and the caller's own numbers; a 404 (the quiz is not for them) goes to Home. */
export async function quizBoard(): Promise<QuizBoard> {
  const { data, response } = await serverApi().GET("/api/me/quiz/leaderboard", await options());
  if (data) return data;
  if (response.status === 401) redirect("/login");
  if (response.status === 404) redirect(HOME);
  throw new Error(`GET /api/me/quiz/leaderboard answered ${response.status}`);
}
