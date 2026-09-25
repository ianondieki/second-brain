import type { components } from "@/lib/api/schema";

/** Keys under `validation.*` in the locale files. */
export type ValidationKey =
  | "side"
  | "displayName"
  | "email"
  | "emailFormat"
  | "password"
  | "passwordLength"
  | "orgName"
  | "orgKind"
  | "terms"
  | "code"
  | "recoveryCode"
  | "emailForLink";

export type OrgKind = components["schemas"]["OrgKind"];
export type SignupSide = components["schemas"]["SignupRequest"]["side"];

/** Every org type the API accepts, in the order the select lists them (generated OrgKind enum). */
export const ORG_KINDS = [
  "company",
  "sme",
  "sacco_mfi",
  "university_tvet",
  "school",
  "national_govt",
  "county_govt",
  "ngo_pbo",
  "development_partner",
] as const satisfies readonly OrgKind[];

// Compile-time check that the list above covers the whole generated enum.
type MissingKinds = Exclude<OrgKind, (typeof ORG_KINDS)[number]>;
const allKindsListed: MissingKinds extends never ? true : false = true;
void allKindsListed;

export const PASSWORD_MIN = 12; // backend passwords.MIN_LENGTH
export const PASSWORD_MAX = 128;

// A light shape check only; the server decides (it also refuses addresses it cannot email safely).
const EMAIL_SHAPE = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/;

export function checkEmail(email: string, missingKey: ValidationKey = "email"): ValidationKey | undefined {
  const value = email.trim();
  if (!value) return missingKey;
  if (!EMAIL_SHAPE.test(value)) return "emailFormat";
  return undefined;
}

export interface SignupValues {
  side: SignupSide | null;
  displayName: string;
  email: string;
  password: string;
  orgName: string;
  orgKind: OrgKind | "";
  terms: boolean;
}

export type SignupField = keyof SignupValues;
/** Field order on the screen: the first invalid one takes focus. */
export const SIGNUP_FIELDS: readonly SignupField[] = [
  "side",
  "displayName",
  "email",
  "password",
  "orgName",
  "orgKind",
  "terms",
];

export function validateSignup(values: SignupValues): Partial<Record<SignupField, ValidationKey>> {
  const errors: Partial<Record<SignupField, ValidationKey>> = {};
  if (!values.side) errors.side = "side";
  if (!values.displayName.trim()) errors.displayName = "displayName";
  const email = checkEmail(values.email);
  if (email) errors.email = email;
  if (!values.password) errors.password = "password";
  else if (values.password.length < PASSWORD_MIN || values.password.length > PASSWORD_MAX)
    errors.password = "passwordLength";
  if (values.side === "org") {
    if (values.orgName.trim().length < 2) errors.orgName = "orgName";
    if (!values.orgKind) errors.orgKind = "orgKind";
  }
  if (!values.terms) errors.terms = "terms";
  return errors;
}

export interface LoginValues {
  email: string;
  password: string;
}

export function validateLogin(values: LoginValues): Partial<Record<keyof LoginValues, ValidationKey>> {
  const errors: Partial<Record<keyof LoginValues, ValidationKey>> = {};
  const email = checkEmail(values.email);
  if (email) errors.email = email;
  if (!values.password) errors.password = "password";
  return errors;
}
