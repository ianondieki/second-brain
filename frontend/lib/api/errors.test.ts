import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";

import { settle } from "./call";
import { apiErrorCode, errorKey, fieldForError, KNOWN_ERROR_CODES } from "./errors";

describe("errorKey", () => {
  it("maps a known API code to its own key, never to the server's text", () => {
    const body = { detail: { code: "invalid_credentials", message: "That email and password do not match." } };
    expect(errorKey(body)).toBe("invalid_credentials");
  });

  it("maps unknown codes and odd bodies to the generic message", () => {
    expect(errorKey({ detail: { code: "brand_new_code", message: "Server wording" } })).toBe("generic");
    expect(errorKey("Internal Server Error")).toBe("generic");
    expect(errorKey(undefined)).toBe("generic");
    expect(errorKey({ detail: "plain string" })).toBe("generic");
  });

  it("reads request-validation errors by field", () => {
    const invalidEmail = { detail: [{ loc: ["body", "email"], msg: "value is not a valid email address", type: "x" }] };
    expect(apiErrorCode(invalidEmail)).toBe("invalid_email");
    expect(errorKey(invalidEmail)).toBe("invalid_email");
    expect(errorKey({ detail: [{ loc: ["body", "code"], msg: "too short", type: "x" }] })).toBe("invalid_code");
    expect(errorKey({ detail: [{ loc: ["body", "token"], msg: "too short", type: "x" }] })).toBe("generic");
  });

  it("has an English message for every key it can return", () => {
    for (const key of [...KNOWN_ERROR_CODES, "generic", "network"] as const) {
      expect(en.errors[key], key).toBeTruthy();
    }
  });
});

describe("fieldForError", () => {
  it("places field errors next to their field", () => {
    expect(fieldForError("invalid_email")).toBe("email");
    expect(fieldForError("weak_password")).toBe("password");
    expect(fieldForError("terms_not_accepted")).toBe("terms");
    expect(fieldForError("org_details_required")).toBe("orgName");
    expect(fieldForError("invalid_code")).toBe("code");
    expect(fieldForError("invalid_credentials")).toBeUndefined();
    expect(fieldForError("generic")).toBeUndefined();
  });
});

describe("settle", () => {
  it("returns the data of a successful call", async () => {
    const outcome = await settle(Promise.resolve({ data: { ok: 1 }, response: new Response(null, { status: 200 }) }));
    expect(outcome).toEqual({ ok: true, data: { ok: 1 }, status: 200 });
  });

  it("returns the error key and status of a refused call", async () => {
    const outcome = await settle(
      Promise.resolve({
        error: { detail: { code: "too_many_attempts", message: "x" } },
        response: new Response(null, { status: 429 }),
      }),
    );
    expect(outcome).toEqual({ ok: false, key: "too_many_attempts", status: 429 });
  });

  it("turns a network failure into the network message", async () => {
    const outcome = await settle(Promise.reject(new TypeError("Failed to fetch")));
    expect(outcome).toEqual({ ok: false, key: "network", status: 0 });
  });
});
