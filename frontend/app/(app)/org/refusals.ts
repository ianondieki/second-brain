import { apiErrorCode } from "@/lib/api/errors";

// Why an organisation screen cannot show something, as a plain sentence and at most one action (docs/spec/07 item 4;
// REQ-REPO-01, REQ-SEC-01). The API names the first condition that fails (bridge/proposals/access.py, the gate order
// D-40: second factor → tenancy 404 → flag 403 → predicate 403 naming the condition); each code has its own sentence
// under `orgProposal.refusal.*`, and never the server's message text.

/** Every refusal the Tier-2 routes (GET|POST …/nda, GET …/tier2) and the Inbox can answer with a code of their own. */
export const REFUSALS = [
  "mfa_required",
  "mfa_enrolment_required",
  "step_up_required",
  "tier2_disabled",
  "org_not_e2",
  "org_suspended",
  "role_not_permitted",
  "email_unverified",
  "domain_mismatch",
  "master_terms_required",
  "grant_required",
  "grant_revoked",
  "engagement_ended",
  "nda_required",
  "nda_outdated",
  "not_configured",
  "not_found",
] as const;

/** A known refusal, or "generic" for anything else (a 5xx, an unknown code, an unreadable body). */
export type Refusal = (typeof REFUSALS)[number] | "generic";

/**
 * What the one action does. `enterCode`: the second-factor page; `turnOnMfa`: security settings; `stepUp`: the code
 * form on the page itself; `newVersion`: show the NDA version published meanwhile; `reload`: fetch the page again (a
 * passing failure); `inbox`: back to the list.
 * Null: nothing the person can do here (an admin, the developer or the platform has to act).
 */
export type RefusalAction = "enterCode" | "turnOnMfa" | "stepUp" | "newVersion" | "reload" | "inbox" | null;

export const REFUSAL_ACTION: Record<Refusal, RefusalAction> = {
  mfa_required: "enterCode",
  mfa_enrolment_required: "turnOnMfa",
  step_up_required: "stepUp",
  tier2_disabled: null,
  org_not_e2: null,
  org_suspended: null,
  role_not_permitted: null,
  email_unverified: null,
  domain_mismatch: null,
  master_terms_required: null,
  grant_required: "inbox",
  grant_revoked: "inbox",
  engagement_ended: "inbox",
  nda_required: "reload",
  nda_outdated: "newVersion",
  not_configured: "reload",
  not_found: "inbox",
  generic: "reload",
};

const KNOWN: ReadonlySet<string> = new Set(REFUSALS);

/** The refusal for an API answer's status and error body. 404 is always "not_found" (existence is never confirmed). */
export function refusalOf(status: number, error: unknown): Refusal {
  if (status === 404) return "not_found";
  const code = apiErrorCode(error);
  return code !== undefined && KNOWN.has(code) ? (code as Refusal) : "generic";
}

/** Where a link action goes; `stepUp`, `newVersion` and `reload` are handled on the page, not by a link. */
export const ACTION_HREF: Partial<Record<Exclude<RefusalAction, null>, string>> = {
  enterCode: "/auth/mfa",
  turnOnMfa: "/settings/security",
};
