/**
 * Maps API error bodies to i18n keys under `errors.*`. The server's `detail.message` is never shown for a known
 * code: the wording lives in locales/*.json so it can be translated and reviewed ([[COPY-REVIEW]]).
 *
 * Error bodies: `{"detail": {"code", "message"}}` for ApiError (backend/src/bridge/errors.py), and
 * `{"detail": [{"loc", "msg", "type"}]}` for request validation (FastAPI 422).
 */

export const KNOWN_ERROR_CODES = [
  "invalid_email",
  "terms_not_accepted",
  "org_details_required",
  "weak_password",
  "invalid_credentials",
  "email_unverified",
  "too_many_attempts",
  "invalid_or_expired_link",
  "invalid_code",
  "totp_already_enabled",
  "no_pending_enrolment",
  "mfa_mandatory_for_role",
  "csrf_failed",
  "unauthenticated",
  "mfa_required",
  "step_up_required",
] as const;

export type KnownErrorCode = (typeof KNOWN_ERROR_CODES)[number];
/** Keys under `errors.*` in locales/en.json and locales/sw.json. */
export type ErrorKey = KnownErrorCode | "generic" | "network";

/** Form fields a code belongs to, so the message can sit next to the field as well as in the summary. */
export type ErrorField = "email" | "password" | "terms" | "orgName" | "code";

const KNOWN = new Set<string>(KNOWN_ERROR_CODES);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** The machine code of an API error body, or undefined when the body has none. */
export function apiErrorCode(error: unknown): string | undefined {
  if (!isRecord(error)) return undefined;
  const detail = error.detail;
  if (isRecord(detail) && !Array.isArray(detail) && typeof detail.code === "string") return detail.code;
  if (Array.isArray(detail)) {
    // Request validation: an invalid email or password field maps to the same code the service would return.
    for (const item of detail) {
      const loc = isRecord(item) && Array.isArray(item.loc) ? item.loc : [];
      if (loc.includes("email")) return "invalid_email";
      if (loc.includes("password")) return "weak_password";
      if (loc.includes("code")) return "invalid_code";
    }
    return "validation";
  }
  return undefined;
}

export function isKnownErrorCode(code: string | undefined): code is KnownErrorCode {
  return code !== undefined && KNOWN.has(code);
}

/** The `errors.*` key to show for an API error body. Unknown codes get the generic message. */
export function errorKey(error: unknown): ErrorKey {
  const code = apiErrorCode(error);
  return isKnownErrorCode(code) ? code : "generic";
}

const FIELD_OF: Partial<Record<KnownErrorCode, ErrorField>> = {
  invalid_email: "email",
  weak_password: "password",
  terms_not_accepted: "terms",
  org_details_required: "orgName",
  invalid_code: "code",
};

export function fieldForError(key: ErrorKey): ErrorField | undefined {
  return key === "generic" || key === "network" ? undefined : FIELD_OF[key];
}
