import { describe, expect, it } from "vitest";

import { destinationFor, homeFor, isMfaPending, isPending, needsMfaSetup } from "./routing";
import { checkEmail, validateLogin, validateSignup, type SignupValues } from "./validation";

const developer: SignupValues = {
  side: "developer",
  displayName: "Wanjiru",
  email: "wanjiru@example.test",
  password: "a long enough password",
  orgName: "",
  orgKind: "",
  terms: true,
};

describe("validateSignup", () => {
  it("accepts a complete developer signup without organisation details", () => {
    expect(validateSignup(developer)).toEqual({});
  });

  it("asks for the side first and for the terms", () => {
    expect(validateSignup({ ...developer, side: null, terms: false })).toEqual({ side: "side", terms: "terms" });
  });

  it("needs organisation name and type only for an organisation", () => {
    expect(validateSignup({ ...developer, side: "org" })).toEqual({ orgName: "orgName", orgKind: "orgKind" });
    expect(validateSignup({ ...developer, side: "org", orgName: "Kisumu Water", orgKind: "county_govt" })).toEqual({});
  });

  it("checks the password length the server enforces (12 to 128)", () => {
    expect(validateSignup({ ...developer, password: "" }).password).toBe("password");
    expect(validateSignup({ ...developer, password: "x".repeat(11) }).password).toBe("passwordLength");
    expect(validateSignup({ ...developer, password: "x".repeat(12) }).password).toBeUndefined();
    expect(validateSignup({ ...developer, password: "x".repeat(129) }).password).toBe("passwordLength");
  });

  it("checks the name and the shape of the email address", () => {
    expect(validateSignup({ ...developer, displayName: "  " }).displayName).toBe("displayName");
    expect(validateSignup({ ...developer, email: "" }).email).toBe("email");
    expect(validateSignup({ ...developer, email: "wanjiru@" }).email).toBe("emailFormat");
    expect(validateSignup({ ...developer, email: "wanjiru.example.test" }).email).toBe("emailFormat");
  });
});

describe("validateLogin and checkEmail", () => {
  it("needs both fields to log in", () => {
    expect(validateLogin({ email: "", password: "" })).toEqual({ email: "email", password: "password" });
    expect(validateLogin({ email: "a@b.co", password: "x" })).toEqual({});
  });

  it("uses the sign-in-link wording when only an email is needed", () => {
    expect(checkEmail("", "emailForLink")).toBe("emailForLink");
    expect(checkEmail(" name@example.com ")).toBeUndefined();
  });
});

describe("routing helpers", () => {
  it("sends each side to its home", () => {
    expect(homeFor("developer")).toBe("/dev");
    expect(homeFor("org")).toBe("/org");
    expect(homeFor("staff")).toBe("/dev");
  });

  it("knows when the second factor is still owed", () => {
    expect(isMfaPending({ required: true, enrolled: true, verified: false })).toBe(true);
    expect(isMfaPending({ required: true, enrolled: true, verified: true })).toBe(false);
    expect(isMfaPending({ required: false, enrolled: false, verified: false })).toBe(false);
  });

  it("sends a session that still owes its second factor to /auth/mfa", () => {
    const owed = { required: true, enrolled: true, verified: false };
    const done = { required: true, enrolled: true, verified: true };
    expect(isPending({ side: "pending", mfa: owed })).toBe(true);
    expect(destinationFor({ side: "pending", mfa: owed })).toBe("/auth/mfa");
    expect(destinationFor({ side: "org", mfa: done })).toBe("/org");
    expect(destinationFor({ side: "staff", mfa: done })).toBe("/dev");
    expect(destinationFor({ side: "developer", mfa: { required: false, enrolled: false, verified: false } })).toBe("/dev");
  });

  it("flags roles that need two-step sign-in but lack it", () => {
    expect(needsMfaSetup({ required: true, enrolled: false, verified: false })).toBe(true);
    expect(needsMfaSetup({ required: true, enrolled: true, verified: true })).toBe(false);
    expect(needsMfaSetup({ required: false, enrolled: false, verified: false })).toBe(false);
  });
});
