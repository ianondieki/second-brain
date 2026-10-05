import { api, type ApiClient } from "@/lib/api/client";

import { refusalOf, type Choice, type DecisionOut, type Refusal } from "./moderation";

// The moderation screen's browser call (REQ-MOD-01): it settles into the decision or a refusal, never a thrown error,
// so the screen shows a fixed sentence whatever happens (a thrown fetch is "generic").

export type DecisionOutcome = { ok: true; data: DecisionOut } | { ok: false; refusal: Refusal };

/**
 * POST /api/admin/moderation/cases/{case_id}/decision: approve or reject the version the moderator reviewed
 * (`subject_version_id`, null for problems; 409 case_changed when the author has published another since).
 */
export async function decideCase(
  caseId: string,
  decision: Choice,
  subjectVersionId: string | null,
  client: ApiClient = api,
): Promise<DecisionOutcome> {
  try {
    const { data, error, response } = await client.POST("/api/admin/moderation/cases/{case_id}/decision", {
      params: { path: { case_id: caseId } },
      body: { decision, subject_version_id: subjectVersionId },
    });
    if (response.ok && data !== undefined) return { ok: true, data };
    return { ok: false, refusal: refusalOf(response.status, error) };
  } catch {
    return { ok: false, refusal: { kind: "refusal", code: "generic" } };
  }
}

/**
 * A message report's decision (REQ-ENG-11): dismiss (the message breaks no rule) or uphold, with an optional staff
 * note kept in the decision's audit details (never shown to the parties). A message has no version.
 */
export async function decideMessageCase(
  caseId: string,
  decision: "dismiss" | "uphold",
  note: string,
  client: ApiClient = api,
): Promise<DecisionOutcome> {
  try {
    const { data, error, response } = await client.POST("/api/admin/moderation/cases/{case_id}/decision", {
      params: { path: { case_id: caseId } },
      body: { decision, subject_version_id: null, note: note.trim() || null },
    });
    if (response.ok && data !== undefined) return { ok: true, data };
    return { ok: false, refusal: refusalOf(response.status, error) };
  } catch {
    return { ok: false, refusal: { kind: "refusal", code: "generic" } };
  }
}
