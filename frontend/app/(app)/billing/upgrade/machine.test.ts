import { describe, expect, it } from "vitest";

import {
  canRetryStart,
  failureReason,
  initialPhase,
  MAX_POLL_ERRORS,
  MAX_WAIT_MS,
  nextPoll,
  POLL_BUDGET_MS,
  pollRefusal,
  reduce,
  startRefusal,
  stepOf,
  waitMs,
  type Checkout,
  type Phase,
} from "./machine";

const ID = "0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f";
const OTHER = "0192a7c4-5b1e-7c3d-8e9f-ffffffffffff";

function checkout(over: Partial<Checkout> = {}): Checkout {
  return {
    id: ID,
    plan_code: "dev_pro_monthly",
    plan_name: "Pro (monthly)",
    side: "developer",
    org_id: null,
    amount_kes_minor: 49900,
    currency: "KES",
    status: "pending",
    failure_code: null,
    simulated: true,
    plan_active: false,
    created_at: "2026-09-30T08:00:00Z",
    settled_at: null,
    poll_after_seconds: 2,
    ...over,
  };
}

const error = (code: string, extra: Record<string, unknown> = {}) => ({ detail: { code, message: "x", ...extra } });

describe("startRefusal", () => {
  it.each([
    [409, error("already_on_plan"), "alreadyOnPlan"],
    [422, error("plan_not_available"), "notAvailable"],
    [422, error("plan_wrong_side"), "notAvailable"],
    [403, error("not_a_developer"), "notDeveloper"],
    [403, error("forbidden"), "failed"],
    [403, error("csrf_failed"), "failed"],
    [403, error("mfa_enrolment_required"), "mfaSetup"],
    [401, error("mfa_required"), "mfaRequired"],
    [401, error("unauthenticated"), "signedOut"],
    [404, error("not_found"), "notFound"],
    [503, error("not_configured"), "notConfigured"],
    [502, error("payment_provider_error"), "providerError"],
    [429, error("too_many_attempts"), "rateLimited"],
    [0, undefined, "network"],
    [422, error("simulation_not_available"), "failed"],
    [500, "Internal Server Error", "failed"],
  ])("maps %i %j to %s", (status, body, problem) => {
    expect(startRefusal(status, body).problem).toBe(problem);
  });

  it("says who pays only for an organisation's checkout", () => {
    expect(startRefusal(403, error("forbidden"), { forOrg: true }).problem).toBe("forbidden");
    expect(startRefusal(403, error("csrf_failed"), { forOrg: true }).problem).toBe("failed");
    expect(canRetryStart(startRefusal(403, error("csrf_failed")).problem)).toBe(true);
  });

  it("keeps the id of the other plan's checkout in progress", () => {
    expect(startRefusal(409, error("checkout_pending", { checkout_id: OTHER }))).toEqual({
      problem: "otherPending",
      checkoutId: OTHER,
    });
  });

  it("never follows a checkout id that is not a UUID", () => {
    expect(startRefusal(409, error("checkout_pending", { checkout_id: "../../admin" }))).toEqual({ problem: "failed" });
  });

  it("offers to try again only when trying again can help", () => {
    expect(canRetryStart("providerError")).toBe(true);
    expect(canRetryStart("network")).toBe(true);
    expect(canRetryStart("alreadyOnPlan")).toBe(false);
    expect(canRetryStart("notConfigured")).toBe(false);
    expect(canRetryStart("forbidden")).toBe(false);
  });
});

describe("pollRefusal", () => {
  it("treats a lost session, another person's checkout and passing failures apart", () => {
    expect(pollRefusal(401, error("unauthenticated"))).toBe("signedOut");
    expect(pollRefusal(401, error("mfa_required"))).toBe("mfaRequired");
    expect(pollRefusal(404, error("not_found"))).toBe("notFound");
    expect(pollRefusal(403, error("forbidden"))).toBe("notFound");
    expect(pollRefusal(0, undefined)).toBe("transient");
    expect(pollRefusal(502, undefined)).toBe("transient");
    expect(pollRefusal(429, error("too_many_attempts"))).toBe("transient");
  });
});

describe("failureReason", () => {
  it("names too little money and words everything else the same", () => {
    expect(failureReason({ failure_code: "insufficient_funds" })).toBe("insufficientFunds");
    expect(failureReason({ failure_code: "unknown_checkout" })).toBe("other");
    expect(failureReason({ failure_code: "amount_mismatch" })).toBe("other");
    expect(failureReason({ failure_code: null })).toBe("other");
  });
});

describe("waitMs", () => {
  it("starts at the API's advice and grows by half each time, up to the cap", () => {
    expect(waitMs(0, 2)).toBe(2000);
    expect(waitMs(1, 2)).toBe(3000);
    expect(waitMs(2, 2)).toBe(4500);
    expect(waitMs(3, 2)).toBe(6750);
    expect(waitMs(4, 2)).toBe(MAX_WAIT_MS);
    expect(waitMs(40, 2)).toBe(MAX_WAIT_MS);
  });

  it("uses two seconds when the API gives no advice, and never waits on a nonsense value", () => {
    expect(waitMs(0, null)).toBe(2000);
    expect(waitMs(0, 0)).toBe(2000);
    expect(waitMs(0, -5)).toBe(2000);
    expect(waitMs(0, 3600)).toBe(MAX_WAIT_MS);
  });
});

describe("the checkout phases", () => {
  const t0 = 1_000_000;

  function started(over: Partial<Checkout> = {}): Phase {
    return reduce(reduce({ kind: "confirm" }, { type: "start" }), { type: "started", checkout: checkout(over), at: t0 });
  }

  it("goes from confirm to starting to pending", () => {
    const phase = started();
    expect(phase).toMatchObject({ kind: "pending", id: ID, attempt: 0, since: t0, errors: 0 });
    expect(stepOf({ kind: "confirm" })).toBe(1);
    expect(stepOf(phase)).toBe(2);
  });

  it("ignores a second press while starting", () => {
    const starting = reduce({ kind: "confirm" }, { type: "start" });
    expect(reduce(starting, { type: "start" })).toBe(starting);
  });

  it("keeps polling while pending, then ends on the provider's answer", () => {
    let phase = started();
    phase = reduce(phase, { type: "polled", checkout: checkout() });
    expect(phase).toMatchObject({ kind: "pending", attempt: 1 });
    phase = reduce(phase, { type: "polled", checkout: checkout({ status: "succeeded", plan_active: true }) });
    expect(phase.kind).toBe("succeeded");
    expect(stepOf(phase)).toBe(3);
  });

  it.each([
    ["failed", "failed"],
    ["cancelled", "cancelled"],
  ] as const)("ends %s", (status, kind) => {
    const phase = reduce(started(), { type: "polled", checkout: checkout({ status }) });
    expect(phase.kind).toBe(kind);
    expect(reduce(phase, { type: "restart" })).toEqual({ kind: "confirm" });
  });

  it("settles at once when the start already has the answer", () => {
    expect(started({ status: "succeeded", plan_active: true }).kind).toBe("succeeded");
  });

  it("counts an answer about another checkout as a failed read, never as its outcome", () => {
    let phase = started();
    phase = reduce(phase, { type: "polled", checkout: checkout({ id: OTHER, status: "succeeded" }) });
    expect(phase).toMatchObject({ kind: "pending", id: ID, attempt: 1, errors: 1 });
    expect(MAX_POLL_ERRORS).toBe(4);
    for (let i = 1; i < MAX_POLL_ERRORS; i++) {
      phase = reduce(phase, { type: "polled", checkout: checkout({ id: OTHER }) });
    }
    expect(phase).toMatchObject({ kind: "stalled", id: ID });
  });

  it("shows a refused start on the confirm step, where it can be tried again", () => {
    const phase = reduce(reduce({ kind: "confirm" }, { type: "start" }), {
      type: "refused",
      refusal: { problem: "providerError" },
      at: t0,
    });
    expect(phase).toEqual({ kind: "confirm", refusal: { problem: "providerError" } });
    expect(reduce(phase, { type: "start" })).toEqual({ kind: "starting" });
  });

  it("follows the other plan's checkout in progress instead of starting a second", () => {
    const phase = reduce(reduce({ kind: "confirm" }, { type: "start" }), {
      type: "refused",
      refusal: { problem: "otherPending", checkoutId: OTHER },
      at: t0,
    });
    expect(phase).toEqual({ kind: "pending", id: OTHER, checkout: null, attempt: 0, since: t0, errors: 0 });
  });

  it("retries passing read failures, then stops after too many in a row", () => {
    let phase = started();
    for (let i = 1; i < MAX_POLL_ERRORS; i++) {
      phase = reduce(phase, { type: "pollFailed", problem: "transient" });
      expect(phase).toMatchObject({ kind: "pending", errors: i });
    }
    phase = reduce(phase, { type: "pollFailed", problem: "transient" });
    expect(phase).toMatchObject({ kind: "stalled", id: ID });
  });

  it("clears the error count on a good read", () => {
    let phase = reduce(started(), { type: "pollFailed", problem: "transient" });
    phase = reduce(phase, { type: "polled", checkout: checkout() });
    expect(phase).toMatchObject({ kind: "pending", errors: 0 });
  });

  it("stops at once when the checkout cannot be read by this person", () => {
    expect(reduce(started(), { type: "pollFailed", problem: "notFound" })).toEqual({ kind: "lost", problem: "notFound" });
    expect(reduce(started(), { type: "pollFailed", problem: "signedOut" })).toEqual({
      kind: "lost",
      problem: "signedOut",
    });
  });

  it("stalls when the budget runs out and polls afresh on Check again", () => {
    const stalled = reduce(started(), { type: "timedOut" });
    expect(stalled).toMatchObject({ kind: "stalled", id: ID });
    expect(stepOf(stalled)).toBe(2);
    expect(reduce(stalled, { type: "checkAgain", at: t0 + 5 })).toMatchObject({
      kind: "pending",
      attempt: 0,
      since: t0 + 5,
      errors: 0,
    });
  });

  it("does not restart a pending checkout", () => {
    const phase = started();
    expect(reduce(phase, { type: "restart" })).toBe(phase);
  });
});

describe("nextPoll", () => {
  const t0 = 5_000_000;

  it("reads a checkout opened from the address at once", () => {
    const phase = initialPhase(ID, t0);
    expect(phase.kind).toBe("pending");
    if (phase.kind === "pending") expect(nextPoll(phase, t0)).toEqual({ wait: 0 });
  });

  it("ignores an address value that is not a checkout id", () => {
    expect(initialPhase("not-a-uuid", t0)).toEqual({ kind: "confirm" });
    expect(initialPhase(undefined, t0)).toEqual({ kind: "confirm" });
  });

  it("waits longer each time and stops when the budget is spent", () => {
    const pending = { kind: "pending" as const, id: ID, checkout: checkout(), attempt: 0, since: t0, errors: 0 };
    expect(nextPoll(pending, t0)).toEqual({ wait: 2000 });
    expect(nextPoll({ ...pending, attempt: 2 }, t0 + 5000)).toEqual({ wait: 4500 });
    // Never waits past the budget, and stops once it is spent.
    expect(nextPoll({ ...pending, attempt: 9 }, t0 + POLL_BUDGET_MS - 1000)).toEqual({ wait: 1000 });
    expect(nextPoll({ ...pending, attempt: 9 }, t0 + POLL_BUDGET_MS)).toBe("stop");
  });

  it("makes a bounded number of reads over the whole budget", () => {
    let phase: Phase = { kind: "pending", id: ID, checkout: checkout(), attempt: 0, since: t0, errors: 0 };
    let now = t0;
    let reads = 0;
    while (phase.kind === "pending") {
      const next = nextPoll(phase, now);
      if (next === "stop") {
        phase = reduce(phase, { type: "timedOut" });
        break;
      }
      now += next.wait;
      reads += 1;
      phase = reduce(phase, { type: "polled", checkout: checkout() });
    }
    expect(phase.kind).toBe("stalled");
    expect(reads).toBeGreaterThan(5);
    expect(reads).toBeLessThanOrEqual(20);
  });
});
