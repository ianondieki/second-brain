import { api, type ApiClient } from "@/lib/api/client";

import { refusalOf, type Refusal } from "./quiz";

// The staff quiz screens' browser calls (REQ-DEV-01): each settles into data or a refusal, never a thrown error (a
// thrown fetch is "generic"). The step-up itself is research/calls.ts's confirmStepUp, shared by the console.

export type Outcome<T> = { ok: true; data: T } | { ok: false; refusal: Refusal };
type Answer<T> = { data?: T; error?: unknown; response: Response };

async function settle<T>(call: Promise<Answer<T>>): Promise<Outcome<T>> {
  try {
    const { data, error, response } = await call;
    if (response.ok && data !== undefined) return { ok: true, data };
    return { ok: false, refusal: refusalOf(response.status, error) };
  } catch {
    return { ok: false, refusal: { kind: "refusal", code: "generic" } };
  }
}

export type Decision = "approve" | "reject";

export interface AdminQuizCalls {
  decide: (setId: string, decision: Decision) => Promise<Outcome<{ status: string }>>;
  /** Pull or restore one question: how many plays were scored again. */
  pull: (questionId: string, reason: string) => Promise<Outcome<{ rescored: number }>>;
  restore: (questionId: string) => Promise<Outcome<{ rescored: number }>>;
}

export function adminQuizCalls(client: ApiClient = api): AdminQuizCalls {
  return {
    decide: (setId, decision) =>
      settle(client.POST("/api/admin/quiz/sets/{set_id}/decision", { params: { path: { set_id: setId } }, body: { decision } })),
    pull: (questionId, reason) =>
      settle(
        client.POST("/api/admin/quiz/questions/{question_id}/pull", {
          params: { path: { question_id: questionId } },
          body: { reason: reason.replace(/\s+/g, " ").trim() },
        }),
      ),
    restore: (questionId) =>
      settle(client.POST("/api/admin/quiz/questions/{question_id}/restore", { params: { path: { question_id: questionId } } })),
  };
}
