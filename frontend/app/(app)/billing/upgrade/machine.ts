import { apiErrorCode, detailOf } from "@/lib/api/error-code";
import type { components } from "@/lib/api/schema";

// The simulated M-Pesa checkout as a small state machine (REQ-BIL-08; docs/spec/05). Plain code decides every step:
// the screen only draws the phase. Confirm → starting → pending (polling GET /api/billing/checkouts/{id} with a
// growing wait) → succeeded, failed or cancelled; a pending checkout that stays unanswered too long stops polling
// ("stalled") until the person asks again. The API's `detail.message` is never shown: each refusal has its own
// [[COPY-REVIEW]] sentence under `checkout.*`.

export type Checkout = components["schemas"]["CheckoutOut"];
export type SimulatedOutcome = components["schemas"]["SimulatedOutcome"];

// ---------------------------------------------------------------- refusals

/** Why a checkout could not start (POST /api/billing/checkouts). */
export type StartProblem =
  | "alreadyOnPlan"
  | "otherPending"
  | "notAvailable"
  | "notDeveloper"
  | "forbidden"
  | "notFound"
  | "notConfigured"
  | "providerError"
  | "mfaRequired"
  | "mfaSetup"
  | "signedOut"
  | "rateLimited"
  | "network"
  | "failed";

export interface StartRefusal {
  problem: StartProblem;
  /** 409 `checkout_pending`: the other plan's checkout that is still waiting. */
  checkoutId?: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function common(status: number, code: string | undefined): StartProblem | null {
  if (status === 0) return "network";
  if (status === 401) return code === "mfa_required" ? "mfaRequired" : "signedOut";
  if (status === 403 && code === "mfa_enrolment_required") return "mfaSetup";
  if (status === 429) return "rateLimited";
  return null;
}

/** A refused start, as the screen words it. */
export function startRefusal(status: number, body: unknown): StartRefusal {
  const code = apiErrorCode(body);
  const shared = common(status, code);
  if (shared) return { problem: shared };
  if (status === 409 && code === "already_on_plan") return { problem: "alreadyOnPlan" };
  if (status === 409 && code === "checkout_pending") {
    const id = detailOf(body)?.checkout_id;
    return typeof id === "string" && UUID.test(id) ? { problem: "otherPending", checkoutId: id } : { problem: "failed" };
  }
  if (status === 422 && (code === "plan_not_available" || code === "plan_wrong_side")) return { problem: "notAvailable" };
  if (status === 403 && code === "not_a_developer") return { problem: "notDeveloper" };
  if (status === 403) return { problem: "forbidden" };
  if (status === 404) return { problem: "notFound" };
  if (status === 503) return { problem: "notConfigured" };
  if (status === 502) return { problem: "providerError" };
  return { problem: "failed" };
}

/** Starting again can help: the person presses the primary action again after these. */
export function canRetryStart(problem: StartProblem): boolean {
  return problem === "providerError" || problem === "rateLimited" || problem === "network" || problem === "failed";
}

/** Why a poll could not read the checkout. "transient" is tried again on the next tick. */
export type PollProblem = "signedOut" | "mfaRequired" | "notFound" | "transient";

export function pollRefusal(status: number, body: unknown): PollProblem {
  const code = apiErrorCode(body);
  if (status === 401) return code === "mfa_required" ? "mfaRequired" : "signedOut";
  // 404: not the caller's (or no such checkout); 403: the caller no longer pays for the organisation.
  if (status === 404 || status === 403) return "notFound";
  return "transient";
}

/** How a finished checkout's failure is worded. */
export type FailureReason = "insufficientFunds" | "other";

export function failureReason(checkout: Pick<Checkout, "failure_code">): FailureReason {
  return checkout.failure_code === "insufficient_funds" ? "insufficientFunds" : "other";
}

// ---------------------------------------------------------------- polling schedule

/** The API's advice when it gives none (`poll_after_seconds`). */
export const DEFAULT_POLL_SECONDS = 2;
/** Each wait is this much longer than the one before, up to MAX_WAIT_MS. */
export const BACKOFF = 1.5;
export const MAX_WAIT_MS = 10_000;
/** Polling stops after this long without a final answer (an M-Pesa prompt times out in about a minute). */
export const POLL_BUDGET_MS = 120_000;
/** Consecutive failed reads (offline, 5xx, 429) before polling stops. */
export const MAX_POLL_ERRORS = 4;

/** The wait before poll number `attempt` (0 = the first after the start). */
export function waitMs(attempt: number, pollAfterSeconds: number | null | undefined): number {
  const advised = typeof pollAfterSeconds === "number" && pollAfterSeconds > 0 ? pollAfterSeconds : DEFAULT_POLL_SECONDS;
  const base = Math.min(advised, 30) * 1000;
  return Math.round(Math.min(MAX_WAIT_MS, base * BACKOFF ** Math.max(0, attempt)));
}

// ---------------------------------------------------------------- phases

export type Phase =
  | { kind: "confirm"; refusal?: StartRefusal }
  | { kind: "starting" }
  | {
      kind: "pending";
      id: string;
      /** Null until the first read of a checkout opened from the address (a reload, or "Check its status"). */
      checkout: Checkout | null;
      /** Polls made since the start (or since "Check again"). */
      attempt: number;
      /** When polling began (ms, the caller's clock). */
      since: number;
      /** Failed reads in a row. */
      errors: number;
    }
  | { kind: "stalled"; id: string; checkout: Checkout | null }
  | { kind: "lost"; problem: Exclude<PollProblem, "transient"> }
  | { kind: "succeeded"; checkout: Checkout }
  | { kind: "failed"; checkout: Checkout }
  | { kind: "cancelled"; checkout: Checkout };

export type Event =
  | { type: "start" }
  | { type: "started"; checkout: Checkout; at: number }
  | { type: "refused"; refusal: StartRefusal; at: number }
  | { type: "polled"; checkout: Checkout }
  | { type: "pollFailed"; problem: PollProblem }
  | { type: "timedOut" }
  | { type: "checkAgain"; at: number }
  | { type: "restart" };

/** The first phase: the confirm step, or polling a checkout named in the address. */
export function initialPhase(checkoutId: string | undefined, at: number): Phase {
  if (checkoutId && UUID.test(checkoutId)) {
    return { kind: "pending", id: checkoutId, checkout: null, attempt: 0, since: at, errors: 0 };
  }
  return { kind: "confirm" };
}

/** The phase a checkout's answer leads to, keeping `pending` bookkeeping from the phase before. */
function answered(checkout: Checkout, before: Extract<Phase, { kind: "pending" }> | null, at?: number): Phase {
  if (checkout.status === "succeeded") return { kind: "succeeded", checkout };
  if (checkout.status === "failed") return { kind: "failed", checkout };
  if (checkout.status === "cancelled") return { kind: "cancelled", checkout };
  if (before) return { ...before, checkout, attempt: before.attempt + 1, errors: 0 };
  return { kind: "pending", id: checkout.id, checkout, attempt: 0, since: at ?? 0, errors: 0 };
}

export function reduce(phase: Phase, event: Event): Phase {
  switch (event.type) {
    case "start":
      return phase.kind === "confirm" ? { kind: "starting" } : phase;
    case "started":
      return phase.kind === "starting" ? answered(event.checkout, null, event.at) : phase;
    case "refused":
      if (phase.kind !== "starting") return phase;
      // Another plan's checkout is still waiting: follow that one instead of starting a second.
      if (event.refusal.problem === "otherPending" && event.refusal.checkoutId) {
        return { kind: "pending", id: event.refusal.checkoutId, checkout: null, attempt: 0, since: event.at, errors: 0 };
      }
      return { kind: "confirm", refusal: event.refusal };
    case "polled":
      if (phase.kind !== "pending" || event.checkout.id !== phase.id) return phase;
      return answered(event.checkout, phase);
    case "pollFailed":
      if (phase.kind !== "pending") return phase;
      if (event.problem !== "transient") return { kind: "lost", problem: event.problem };
      if (phase.errors + 1 >= MAX_POLL_ERRORS) return { kind: "stalled", id: phase.id, checkout: phase.checkout };
      return { ...phase, attempt: phase.attempt + 1, errors: phase.errors + 1 };
    case "timedOut":
      return phase.kind === "pending" ? { kind: "stalled", id: phase.id, checkout: phase.checkout } : phase;
    case "checkAgain":
      if (phase.kind !== "stalled") return phase;
      return { kind: "pending", id: phase.id, checkout: phase.checkout, attempt: 0, since: event.at, errors: 0 };
    case "restart":
      return phase.kind === "failed" || phase.kind === "cancelled" || phase.kind === "confirm"
        ? { kind: "confirm" }
        : phase;
  }
}

/**
 * What a pending phase does next at time `now`: poll after `wait` ms, or stop (the budget is spent). The first read
 * of a checkout opened from the address is immediate.
 */
export function nextPoll(phase: Extract<Phase, { kind: "pending" }>, now: number): { wait: number } | "stop" {
  if (phase.checkout === null && phase.attempt === 0) return { wait: 0 };
  const elapsed = now - phase.since;
  if (elapsed >= POLL_BUDGET_MS) return "stop";
  return { wait: Math.min(waitMs(phase.attempt, phase.checkout?.poll_after_seconds), POLL_BUDGET_MS - elapsed) };
}

/** The step of the three-step stepper a phase belongs to (1 confirm, 2 phone, 3 result). */
export function stepOf(phase: Phase): 1 | 2 | 3 {
  if (phase.kind === "confirm" || phase.kind === "starting") return 1;
  if (phase.kind === "pending" || phase.kind === "stalled" || phase.kind === "lost") return 2;
  return 3;
}
