import { describe, expect, it } from "vitest";

import type { ApiOutcome } from "@/lib/api/call";
import type { ErrorKey } from "@/lib/api/errors";

import { cancelStatus, renewalStep } from "./outcomes";

const refused = (status: number, key: ErrorKey): ApiOutcome<never> => ({ ok: false, status, key });
const CODES = Array.from({ length: 10 }, (_, i) => `abcd-ef${i}g`);

describe("cancelStatus (DELETE /api/auth/totp/enrol, follow-up 7)", () => {
  it("reads off from 204 and from 409 no_pending_enrolment", () => {
    expect(cancelStatus({ ok: true, status: 204, data: undefined })).toBe("off");
    expect(cancelStatus(refused(409, "no_pending_enrolment"))).toBe("off");
  });

  it("reads on from 409 totp_already_enabled (a confirmation committed first)", () => {
    expect(cancelStatus(refused(409, "totp_already_enabled"))).toBe("on");
  });

  it.each<[number, ErrorKey]>([
    [0, "network"],
    [500, "generic"],
    [502, "generic"],
    [504, "generic"],
    [401, "unauthenticated"],
    [403, "csrf_failed"],
    [429, "too_many_attempts"],
    [409, "generic"], // a conflict the page does not know says nothing about the status
    [422, "validation"],
  ])("cannot tell from anything else (%i %s)", (status, key) => {
    expect(cancelStatus(refused(status, key))).toBe("unknown");
  });
});

describe("renewalStep (POST /api/auth/totp/recovery-codes, follow-up 8)", () => {
  it("shows the ten new codes", () => {
    expect(renewalStep({ ok: true, status: 200, data: { recovery_codes: CODES } })).toEqual({
      kind: "codes",
      codes: CODES,
    });
  });

  it("never shows an empty list: a success without codes is an error to retry", () => {
    expect(renewalStep({ ok: true, status: 200, data: { recovery_codes: [] } })).toEqual({
      kind: "error",
      key: "generic",
    });
    expect(renewalStep({ ok: true, status: 200, data: undefined as never })).toEqual({ kind: "error", key: "generic" });
  });

  it("asks for a fresh authenticator code on 403 step_up_required", () => {
    expect(renewalStep(refused(403, "step_up_required"))).toEqual({ kind: "stepUp" });
  });

  it("asks for the password again on 403 current_password_required", () => {
    expect(renewalStep(refused(403, "current_password_required"))).toEqual({ kind: "password" });
  });

  it("goes back to the start on 409 totp_not_enabled (turned off meanwhile)", () => {
    expect(renewalStep(refused(409, "totp_not_enabled"))).toEqual({ kind: "off" });
  });

  it.each<[number, ErrorKey]>([
    [429, "too_many_attempts"],
    [403, "csrf_failed"],
    [401, "unauthenticated"],
    [401, "mfa_required"],
    [403, "recent_sign_in_required"],
    [0, "network"],
    [500, "generic"],
    [422, "validation"],
  ])("keeps the form with the fixed message for anything else (%i %s)", (status, key) => {
    expect(renewalStep(refused(status, key))).toEqual({ kind: "error", key });
  });
});
