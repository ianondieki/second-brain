import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";

import { refusalOf, type Refusal, type Run } from "./research";

// The research screens' browser calls (REQ-RES-01): each settles into data or a refusal, never a thrown error, so the
// screens show a fixed sentence whatever happens (a thrown fetch is "generic").

export type Outcome<T> = { ok: true; data: T } | { ok: false; refusal: Refusal };

async function settle<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<Outcome<T>> {
  try {
    const { data, error, response } = await call;
    if (response.ok && data !== undefined) return { ok: true, data };
    return { ok: false, refusal: refusalOf(response.status, error) };
  } catch {
    return { ok: false, refusal: { kind: "refusal", code: "generic" } };
  }
}

/** POST /api/admin/research/runs: a running run of the niche in Kenya (202), or why not. */
export function startRun(niche: string, client: ApiClient = api): Promise<Outcome<Run>> {
  return settle(client.POST("/api/admin/research/runs", { body: { niche, country: "KE" } }));
}

/** GET /api/admin/research/runs/{run_id}: the run's status and counts now. */
export function getRun(runId: string, client: ApiClient = api): Promise<Outcome<Run>> {
  return settle(client.GET("/api/admin/research/runs/{run_id}", { params: { path: { run_id: runId } } }));
}

export type Decision = "approve" | "reject";

/** POST …/candidates/{problem_id}/decision: publish (after the publish checks) or reject the card. */
export function decide(
  problemId: string,
  decision: Decision,
  checklistConfirmed: boolean,
  client: ApiClient = api,
): Promise<Outcome<{ status: string }>> {
  return settle(
    client.POST("/api/admin/research/candidates/{problem_id}/decision", {
      params: { path: { problem_id: problemId } },
      body: { decision, checklist_confirmed: checklistConfirmed },
    }),
  );
}

export type StepUpOutcome = { ok: true } | { ok: false; invalidCode: boolean };

/** POST /api/auth/step-up with a fresh authenticator code (ADR-002: the staff console needs one within 12 hours). */
export async function confirmStepUp(code: string, client: ApiClient = api): Promise<StepUpOutcome> {
  try {
    const { error, response } = await client.POST("/api/auth/step-up", { body: { code } });
    if (response.ok) return { ok: true };
    return { ok: false, invalidCode: apiErrorCode(error) === "invalid_code" };
  } catch {
    return { ok: false, invalidCode: false };
  }
}
