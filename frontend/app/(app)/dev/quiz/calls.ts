import { api, type ApiClient } from "@/lib/api/client";

import { answersBody, finishProblem, flagNote, flagOutcome, type FinishProblem, type FlagOutcome, type FlagReason } from "./quiz";

// The browser's quiz calls (same-origin /api, CSRF header added by the client). Each settles into what the screen
// says, never a thrown error: a thrown fetch (offline, reset) is "network".

export type FinishOutcome = { ok: true } | { ok: false; problem: FinishProblem };

export interface QuizCalls {
  finish: (setId: string, chosen: readonly (number | null)[], elapsedMs: number) => Promise<FinishOutcome>;
  flag: (questionId: string, reason: FlagReason, note: string) => Promise<FlagOutcome>;
  /** The board opt-in; true when the API kept it. */
  optIn: (value: boolean) => Promise<boolean>;
}

export function quizCalls(client: ApiClient = api): QuizCalls {
  return {
    async finish(setId, chosen, elapsedMs) {
      try {
        const { error, response } = await client.POST("/api/me/quiz/today/answers", {
          body: answersBody(setId, chosen, elapsedMs),
        });
        return response.ok ? { ok: true } : { ok: false, problem: finishProblem(response.status, error) };
      } catch {
        return { ok: false, problem: "network" };
      }
    },
    async flag(questionId, reason, note) {
      try {
        const { error, response } = await client.POST("/api/me/quiz/questions/{question_id}/flag", {
          params: { path: { question_id: questionId } },
          body: { reason, note: flagNote(note) },
        });
        return flagOutcome(response.status, error);
      } catch {
        return "network";
      }
    },
    async optIn(value) {
      try {
        const { response } = await client.PUT("/api/me/quiz/settings", { body: { leaderboard_opt_in: value } });
        return response.ok;
      } catch {
        return false;
      }
    },
  };
}
