import { describe, expect, it } from "vitest";

import en from "@/locales/en.json";

import { settle } from "./call";
import { apiErrorCode, apiErrorUpgrade, errorKey, fieldForError, KNOWN_ERROR_CODES, sameOriginPath } from "./errors";

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
    expect(errorKey({ detail: [{ loc: ["body", "token"], msg: "too short", type: "x" }] })).toBe("validation");
    expect(errorKey({ detail: [{ loc: ["body", "new_password"], msg: "too short", type: "x" }] })).toBe("weak_password");
  });

  it("knows the codes added by the auth review", () => {
    const codes = [
      "consents_version_required",
      "consent_text_changed",
      "current_password_required",
      "recent_sign_in_required",
    ];
    for (const code of codes) {
      expect(errorKey({ detail: { code, message: "server text" } })).toBe(code);
    }
  });

  it("has an English message for every key it can return", () => {
    for (const key of [...KNOWN_ERROR_CODES, "validation", "generic", "network"] as const) {
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
    expect(fieldForError("current_password_required")).toBe("currentPassword");
    expect(fieldForError("invalid_credentials")).toBeUndefined();
    expect(fieldForError("generic")).toBeUndefined();
  });
});

describe("apiErrorUpgrade", () => {
  it("reads the next plan from a 402 body", () => {
    const body = {
      detail: { code: "plan_limit", message: "x", upgrade: { plan: "org_team", url: "/billing/upgrade?plan=org_team" } },
    };
    expect(apiErrorUpgrade(body)).toEqual({ plan: "org_team", url: "/billing/upgrade?plan=org_team" });
  });

  it("returns null at the top of the plan ladder (upgrade: null) and for other bodies", () => {
    expect(apiErrorUpgrade({ detail: { code: "plan_limit", message: "x", upgrade: null } })).toBeNull();
    expect(apiErrorUpgrade({ detail: { code: "forbidden", message: "x" } })).toBeNull();
    expect(apiErrorUpgrade({ detail: [{ loc: ["body"], msg: "x", type: "x" }] })).toBeNull();
    expect(apiErrorUpgrade(undefined)).toBeNull();
  });

  it("accepts only a same-origin path, never an absolute or protocol-relative URL", () => {
    const body = (url: string) => ({ detail: { code: "plan_limit", message: "x", upgrade: { plan: "p", url } } });
    expect(apiErrorUpgrade(body("/billing/upgrade?plan=p"))).toEqual({ plan: "p", url: "/billing/upgrade?plan=p" });
    expect(apiErrorUpgrade(body("//evil.example/pay"))).toBeNull();
    expect(apiErrorUpgrade(body("https://evil.example/pay"))).toBeNull();
    expect(apiErrorUpgrade(body("javascript:alert(1)"))).toBeNull();
    expect(apiErrorUpgrade(body("billing/upgrade"))).toBeNull();
    expect(apiErrorUpgrade(body("/\\evil.example"))).toBeNull();
  });

  it.each([
    ["tab", "/\t/evil.example"],
    ["carriage return", "/\r/evil.example"],
    ["line feed", "/\n/evil.example"],
    ["space", "/ /evil.example"],
    ["NUL", "/\u0000/evil.example"],
  ])("rejects a path with a %s that the URL parser would strip into //evil.example", (_name, url) => {
    // The parser really does resolve these to the other host; the check must not rely on the raw prefix.
    if (url !== "/ /evil.example" && !url.includes("\u0000")) {
      expect(new URL(url, "https://bridge.example").host).toBe("evil.example");
    }
    expect(sameOriginPath(url)).toBeNull();
    const body = { detail: { code: "plan_limit", message: "x", upgrade: { plan: "p", url } } };
    expect(apiErrorUpgrade(body)).toBeNull();
  });

  it("keeps ordinary same-origin paths with a query and fragment", () => {
    expect(sameOriginPath("/billing/upgrade?plan=org_team#compare")).toBe("/billing/upgrade?plan=org_team#compare");
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
