import { api, type ApiClient } from "@/lib/api/client";
import { apiErrorCode } from "@/lib/api/error-code";

import type { CommandRequest } from "./model";

// The tracker's calls from the browser (same-origin /api through the Next.js rewrite; the typed client adds the CSRF
// header to every POST). Each settles into ok or a refusal the screen words from locales (never the server's text).

/** Why a command was refused, as the screen words it (`trackerActions.refusal.*`). */
export type Refusal =
  | "stale"
  | "conflict"
  | "stepUp"
  | "notAllowed"
  | "d2"
  | "dealsOff"
  | "mfaSetup"
  | "signOutside"
  | "paymentMismatch"
  | "invalid"
  | "invalidContactBy"
  | "attestation"
  | "reasonText"
  | "containsContact"
  | "invalidNote"
  | "invalidResumeAt"
  | "questionLimit"
  | "holdLimit"
  | "tooMany"
  | "notFound"
  | "network"
  | "generic";

/** API codes with their own wording; any other code falls back by status. */
const BY_CODE: Record<string, Refusal> = {
  stale: "stale",
  step_up_required: "stepUp",
  d2_required: "d2",
  deals_disabled: "dealsOff",
  mfa_enrolment_required: "mfaSetup",
  not_your_action: "notAllowed",
  role_required: "notAllowed",
  counterparty_marks_final: "notAllowed",
  both_parties: "notAllowed",
  sign_outside_platform: "signOutside",
  payment_amount_mismatch: "paymentMismatch",
  invalid_contact_by: "invalidContactBy",
  attestation_required: "attestation",
  reason_text_required: "reasonText",
  // The side states (REQ-ENG-10 part): a text with contact details before first contact, a blank or refused text, a
  // resume date out of range, the caps on questions and holds (policy.yaml), and one party's side-state steps per hour.
  contains_contact: "containsContact",
  invalid_note: "invalidNote",
  invalid_resume_at: "invalidResumeAt",
  info_request_limit: "questionLimit",
  hold_limit: "holdLimit",
  too_many_actions: "tooMany",
};

export function refusalOf(status: number, error: unknown): Refusal {
  const code = apiErrorCode(error);
  if (code && code in BY_CODE) return BY_CODE[code];
  if (status === 404) return "notFound";
  if (status === 409) return "conflict";
  if (status === 403) return "notAllowed";
  if (status === 422 || status === 400) return "invalid";
  return "generic";
}

export type CommandOutcome = { ok: true } | { ok: false; refusal: Refusal; status: number };

/** The typed client's POST for a path the model built from the generated paths (model.ts checks they exist). */
type Post = (
  path: string,
  options: { params: { path: CommandRequest["params"] }; body: CommandRequest["body"] },
) => Promise<{ error?: unknown; response: Response }>;

/** Runs one command. The caller refreshes the page on success and on 404/409 (the engagement moved on). */
export async function runCommand(request: CommandRequest, client: ApiClient = api): Promise<CommandOutcome> {
  try {
    const post = client.POST as unknown as Post;
    const { error, response } = await post(request.path, { params: { path: request.params }, body: request.body });
    if (response.ok) return { ok: true };
    return { ok: false, refusal: refusalOf(response.status, error), status: response.status };
  } catch {
    return { ok: false, refusal: "network", status: 0 };
  }
}

export type StepUpOutcome = { ok: true } | { ok: false; invalidCode: boolean };

/** A fresh second factor for this session (ADR-002: signing, endorsing and payments need one within 12 hours). */
export async function confirmStepUp(code: string, client: ApiClient = api): Promise<StepUpOutcome> {
  try {
    const { error, response } = await client.POST("/api/auth/step-up", { body: { code } });
    if (response.ok) return { ok: true };
    return { ok: false, invalidCode: apiErrorCode(error) === "invalid_code" };
  } catch {
    return { ok: false, invalidCode: false };
  }
}

export type Contact = { developer_name: string; email: string | null; phone: string | null };
export type ContactOutcome = { ok: true; contact: Contact } | { ok: false; refusal: Refusal };

/** The developer's contact details, for the organisation's named contact once approved (each reveal is audited). */
export async function revealContact(engagementId: string, client: ApiClient = api): Promise<ContactOutcome> {
  try {
    const { data, error, response } = await client.GET("/api/engagements/{engagement_id}/contact", {
      params: { path: { engagement_id: engagementId } },
    });
    if (data) return { ok: true, contact: data };
    return { ok: false, refusal: refusalOf(response.status, error) };
  } catch {
    return { ok: false, refusal: "network" };
  }
}
