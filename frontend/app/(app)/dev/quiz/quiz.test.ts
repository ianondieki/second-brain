import { describe, expect, it } from "vitest";

import { board, quizToday } from "@/test/quiz";
import {
  answeredCount,
  answersBody,
  boardLine,
  finishProblem,
  flagEndsSheet,
  flagNote,
  flagOutcome,
  isNoQuiz,
  optionMark,
  outcomes,
} from "./quiz";

// REQ-DEV-01 (P22-AF): the plain rules of Today's five on screen. The API scores; these only word what it says.

const err = (code: string) => ({ detail: { code, message: "x" } });

describe("finishing today's five", () => {
  it("sends five answers by position, skipped ones as null, and the time clamped to the API's range", () => {
    expect(answersBody("s", [2, null, 1], 1234.6)).toEqual({ set_id: "s", answers: [2, null, 1, null, null], time_ms: 1235 });
    expect(answersBody("s", [0, 1, 2, 3, 4], -5).answers).toEqual([0, 1, 2, 3, null]);
    expect(answersBody("s", [], -5).time_ms).toBe(0);
    expect(answersBody("s", [], 9e10).time_ms).toBe(86_400_000);
    expect(answersBody("s", [], Number.NaN).time_ms).toBe(0);
    expect(answeredCount([0, null, 3, null, 1])).toBe(3);
  });

  it("words each refusal: played elsewhere shows the results, a day that ended or has no set is one sentence", () => {
    expect(finishProblem(409, err("already_played"))).toBe("played");
    expect(finishProblem(409, err("set_closed"))).toBe("closed");
    expect(finishProblem(404, err("no_quiz"))).toBe("noQuiz");
    expect(finishProblem(401, err("unauthenticated"))).toBe("signedOut");
    expect(finishProblem(422, err("validation"))).toBe("failed");
    expect(finishProblem(0, undefined)).toBe("network");
  });

  it("knows a day without a set from any other 404", () => {
    expect(isNoQuiz(404, err("no_quiz"))).toBe(true);
    expect(isNoQuiz(404, err("not_found"))).toBe(false);
    expect(isNoQuiz(500, err("no_quiz"))).toBe(false);
  });
});

describe("the scoring display", () => {
  it("marks the right option, the caller's choice, or both", () => {
    expect(optionMark(2, 2, 2)).toBe("rightChosen");
    expect(optionMark(2, 2, 1)).toBe("right");
    expect(optionMark(1, 2, 1)).toBe("wrongChosen");
    expect(optionMark(0, 2, 1)).toBeNull();
    expect(optionMark(0, 2, null)).toBeNull();
  });

  it("gives each question its outcome in order: right, wrong, skipped, withdrawn", () => {
    const today = quizToday({ played: true, answers: [2, 0, 2, null, 0], pulled: 2 });
    expect(outcomes(today, today.attempt!)).toEqual(["right", "wrong", "pulled", "skipped", "right"]);
  });
});

describe("flags", () => {
  it("ends the sheet when sent, already flagged or already withdrawn; says the rest in the sheet", () => {
    expect(flagOutcome(201, undefined)).toBe("sent");
    expect(flagOutcome(409, err("already_flagged"))).toBe("already");
    expect(flagOutcome(409, err("question_pulled"))).toBe("pulled");
    expect(flagOutcome(429, err("flag_limit"))).toBe("limit");
    expect(flagOutcome(403, err("play_first"))).toBe("playFirst");
    expect(flagOutcome(500, undefined)).toBe("failed");
    expect(["sent", "already", "pulled"].every((o) => flagEndsSheet(o as never))).toBe(true);
    expect(flagEndsSheet("limit")).toBe(false);
  });

  it("sends a note on one line, at most 300 characters, or none", () => {
    expect(flagNote("  the   answer\nis 3 ")).toBe("the answer is 3");
    expect(flagNote("   ")).toBeNull();
    expect(flagNote("x".repeat(400))).toHaveLength(300);
  });
});

describe("the caller's line on the board", () => {
  it("ranks an opted-in player, asks a player who is not on the board to join, and says when nothing was played", () => {
    expect(boardLine(board().me)).toEqual({ key: "ranked", points: 12, rank: 4 });
    expect(boardLine(board({ opted_in: false }).me)).toEqual({ key: "join", points: 12 });
    expect(boardLine(board({ played: false, rank: null, points: 0 }).me)).toEqual({ key: "notPlayed" });
  });
});
