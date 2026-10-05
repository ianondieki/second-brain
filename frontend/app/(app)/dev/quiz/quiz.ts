import { apiErrorCode } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

// Today's five (REQ-DEV-01; D-59; docs/platform/tasks/P22.md track A): the plain logic of the Home card, /dev/quiz and
// the weekly board. The API decides and scores; this only words it. Nothing here calls the API.

type Schemas = components["schemas"];
export type QuizToday = Schemas["QuizTodayOut"];
export type QuizQuestion = Schemas["QuizQuestionOut"];
export type QuizAttempt = Schemas["QuizAttemptOut"];
export type QuizBoard = Schemas["QuizBoardOut"];
export type FlagReason = Schemas["QuizFlagIn"]["reason"];

export const QUIZ_PATH = "/dev/quiz";
export const BOARD_PATH = "/dev/quiz/board";
/** How many questions a set has (the API's QuizAnswersIn takes exactly five). */
export const QUESTIONS = 5;
/** The API's longest attempt (QuizAnswersIn.time_ms). */
export const MAX_TIME_MS = 86_400_000;
/** The longest flag note staff read (the API collapses whitespace, then keeps at most 300 characters). */
export const MAX_NOTE = 300;
export const FLAG_REASONS: readonly FlagReason[] = ["wrong_answer", "unclear", "outdated", "other"];

/** What the Home card shows: today's set (played or not), no set today, or nothing at all (the read failed). */
export type QuizCardState = { kind: "set"; today: QuizToday } | { kind: "none" } | null;

/** GET /api/me/quiz/today's 404 for a day without an approved set (any other 404: not a developer). */
export function isNoQuiz(status: number, error: unknown): boolean {
  return status === 404 && apiErrorCode(error) === "no_quiz";
}

/** The body of POST /api/me/quiz/today/answers: five answers by position (null: skipped), time clamped to the API's. */
export function answersBody(setId: string, chosen: readonly (number | null)[], elapsedMs: number) {
  const answers = Array.from({ length: QUESTIONS }, (_, i) => {
    const value = chosen[i];
    return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 3 ? value : null;
  });
  const time_ms = Math.min(MAX_TIME_MS, Math.max(0, Math.round(Number.isFinite(elapsedMs) ? elapsedMs : 0)));
  return { set_id: setId, answers, time_ms };
}

/** How many of the five have an answer. */
export function answeredCount(chosen: readonly (number | null)[]): number {
  return chosen.filter((value) => value !== null && value !== undefined).length;
}

/** Why finishing did not work (`quizPlay.problem.*`); "played": it is already finished (another tab): show the results. */
export type FinishProblem = "played" | "closed" | "noQuiz" | "signedOut" | "failed" | "network";

export function finishProblem(status: number, error: unknown): FinishProblem {
  if (status === 0) return "network";
  if (status === 401) return "signedOut";
  const code = apiErrorCode(error);
  if (status === 409 && code === "already_played") return "played";
  if (status === 409 && code === "set_closed") return "closed";
  if (status === 404 && code === "no_quiz") return "noQuiz";
  return "failed";
}

/** What a flag ended in (`quizPlay.flag.*`): sent, or why not. */
export type FlagOutcome = "sent" | "already" | "pulled" | "limit" | "playFirst" | "signedOut" | "failed" | "network";

export function flagOutcome(status: number, error: unknown): FlagOutcome {
  if (status >= 200 && status < 300) return "sent";
  if (status === 0) return "network";
  if (status === 401) return "signedOut";
  const code = apiErrorCode(error);
  if (status === 409 && code === "already_flagged") return "already";
  if (status === 409 && code === "question_pulled") return "pulled";
  if (status === 429) return "limit";
  if (status === 403 && code === "play_first") return "playFirst";
  return "failed";
}

/** Outcomes that end the sheet (said where the Flag button was); the others are said inside the sheet. */
export function flagEndsSheet(outcome: FlagOutcome): boolean {
  return outcome === "sent" || outcome === "already" || outcome === "pulled";
}

/** The flag note as sent: trimmed, at most 300 characters, null when empty. */
export function flagNote(note: string): string | null {
  const trimmed = note.replace(/\s+/g, " ").trim();
  return trimmed ? trimmed.slice(0, MAX_NOTE) : null;
}

/** How one option of a finished question is marked. */
export type OptionMark = "rightChosen" | "right" | "wrongChosen" | null;

export function optionMark(index: number, answer: number | null, chosen: number | null): OptionMark {
  if (answer === null) return chosen === index ? "wrongChosen" : null;
  if (index === answer) return chosen === index ? "rightChosen" : "right";
  return chosen === index ? "wrongChosen" : null;
}

/** One question's outcome for the caller: right, wrong, skipped, or withdrawn (counts for nobody). */
export type QuestionOutcome = "right" | "wrong" | "skipped" | "pulled";

export function questionOutcome(question: Pick<QuizQuestion, "pulled">, attempt: QuizAttempt, index: number): QuestionOutcome {
  if (question.pulled || attempt.correct[index] === null) return "pulled";
  if (attempt.answers[index] === null || attempt.answers[index] === undefined) return "skipped";
  return attempt.correct[index] ? "right" : "wrong";
}

/** The five outcomes in order, for the small marks beside a score. */
export function outcomes(today: Pick<QuizToday, "questions">, attempt: QuizAttempt): QuestionOutcome[] {
  const ordered = [...today.questions].sort((a, b) => a.position - b.position);
  return ordered.map((question, index) => questionOutcome(question, attempt, index));
}

/** The caller's line on the board (`quiz.board.me.*`). */
export type BoardLine =
  | { key: "ranked"; points: number; rank: number }
  | { key: "join"; points: number }
  | { key: "notPlayed" };

export function boardLine(me: QuizBoard["me"]): BoardLine {
  if (!me.played || me.rank === null) return { key: "notPlayed" };
  if (!me.opted_in) return { key: "join", points: me.points };
  return { key: "ranked", points: me.points, rank: me.rank };
}
