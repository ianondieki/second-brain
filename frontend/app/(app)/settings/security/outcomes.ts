import type { ApiOutcome } from "@/lib/api/call";
import type { ErrorKey } from "@/lib/api/errors";

// What the two-step sign-in screens do with an API answer (REQ-AUTH-01 follow-ups 7 and 8). Plain functions, so every
// refusal has one fixed outcome and a test per answer; the screens only show the `errors.*` message for a key, never
// the API's own words.

/**
 * What DELETE /api/auth/totp/enrol ("Cancel setup") says about two-step sign-in. The route takes the same per-user
 * lock as the confirmation, so its answer settles a confirmation whose own answer was lost:
 *
 * - "off": 204 (the pending key is cleared) or 409 no_pending_enrolment (nothing was pending and two-step sign-in is
 *   off, so no later confirmation can turn it on);
 * - "on": 409 totp_already_enabled (a confirmation committed first; its answer, with the recovery codes, may never
 *   have arrived);
 * - "unknown": anything else (no answer, a 5xx, a timeout, the session ended).
 */
export type TwoStepStatus = "off" | "on" | "unknown";

export function cancelStatus(outcome: ApiOutcome<unknown>): TwoStepStatus {
  if (outcome.ok) return "off";
  if (outcome.status === 409 && outcome.key === "no_pending_enrolment") return "off";
  if (outcome.status === 409 && outcome.key === "totp_already_enabled") return "on";
  return "unknown";
}

/** The next step of "Get new recovery codes" after POST /api/auth/totp/recovery-codes answers. */
export type RenewalStep =
  /** Ten new codes, shown once; the old ones no longer work. */
  | { kind: "codes"; codes: string[] }
  /** 403 step_up_required: a fresh code from the authenticator app, then the same request again. */
  | { kind: "stepUp" }
  /** 403 current_password_required: the password was missing or wrong; ask for it again. */
  | { kind: "password" }
  /** 409 totp_not_enabled: two-step sign-in was turned off meanwhile, so there are no codes to replace. */
  | { kind: "off" }
  /** Any other refusal (throttled, CSRF, session ended, no answer...): its fixed message, and the form stays. */
  | { kind: "error"; key: ErrorKey };

export function renewalStep(outcome: ApiOutcome<{ recovery_codes: string[] }>): RenewalStep {
  if (outcome.ok) {
    const codes = outcome.data?.recovery_codes;
    // A success without its codes would leave the person with neither the old codes (replaced) nor new ones on
    // screen: say something went wrong rather than show an empty list.
    return Array.isArray(codes) && codes.length > 0 ? { kind: "codes", codes } : { kind: "error", key: "generic" };
  }
  if (outcome.status === 403 && outcome.key === "step_up_required") return { kind: "stepUp" };
  if (outcome.status === 403 && outcome.key === "current_password_required") return { kind: "password" };
  if (outcome.status === 409 && outcome.key === "totp_not_enabled") return { kind: "off" };
  return { kind: "error", key: outcome.key };
}
