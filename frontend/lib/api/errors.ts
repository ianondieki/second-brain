/**
 * Maps API error bodies to i18n keys under `errors.*`. The server's `detail.message` is never shown for a known
 * code: the wording lives in locales/*.json so it can be translated and reviewed ([[COPY-REVIEW]]).
 *
 * Error bodies (ApiErrorBody in the OpenAPI): `{"detail": {"code", "message", ...extra}}`, or
 * `{"detail": [{"loc", "msg", "type"}]}` for request validation (FastAPI 422).
 */

export const KNOWN_ERROR_CODES = [
  "invalid_email",
  "terms_not_accepted",
  "org_details_required",
  "consents_version_required",
  "consent_text_changed",
  "weak_password",
  "invalid_credentials",
  "email_unverified",
  "too_many_attempts",
  "invalid_or_expired_link",
  "invalid_code",
  "totp_already_enabled",
  "no_pending_enrolment",
  "mfa_mandatory_for_role",
  "current_password_required",
  "recent_sign_in_required",
  "csrf_failed",
  "unauthenticated",
  "mfa_required",
  "step_up_required",
] as const;

export type KnownErrorCode = (typeof KNOWN_ERROR_CODES)[number];
/**
 * Keys under `errors.*` in locales/en.json and locales/sw.json. "validation" is a 422 whose fields map to no known
 * code; "generic" is anything else unknown.
 */
export type ErrorKey = KnownErrorCode | "validation" | "generic" | "network";

/** Form fields a code belongs to, so the message can sit next to the field as well as in the summary. */
export type ErrorField = "email" | "password" | "terms" | "orgName" | "code" | "currentPassword";

const KNOWN = new Set<string>(KNOWN_ERROR_CODES);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function detailOf(error: unknown): Record<string, unknown> | undefined {
  if (!isRecord(error)) return undefined;
  const detail = error.detail;
  return isRecord(detail) && !Array.isArray(detail) ? detail : undefined;
}

/** The machine code of an API error body, or undefined when the body has none. */
export function apiErrorCode(error: unknown): string | undefined {
  const detail = detailOf(error);
  if (detail && typeof detail.code === "string") return detail.code;
  const list = isRecord(error) ? error.detail : undefined;
  if (Array.isArray(list)) {
    // Request validation: an invalid email, password or code field maps to the code the service would return.
    for (const item of list) {
      const loc = isRecord(item) && Array.isArray(item.loc) ? item.loc : [];
      if (loc.includes("email")) return "invalid_email";
      if (loc.includes("password") || loc.includes("new_password")) return "weak_password";
      if (loc.includes("code")) return "invalid_code";
    }
    return "validation";
  }
  return undefined;
}

export function isKnownErrorCode(code: string | undefined): code is KnownErrorCode {
  return code !== undefined && KNOWN.has(code);
}

/** The `errors.*` key to show for an API error body. Unmapped validation errors and unknown codes get their own. */
export function errorKey(error: unknown): ErrorKey {
  const code = apiErrorCode(error);
  if (code === "validation") return "validation";
  return isKnownErrorCode(code) ? code : "generic";
}

/**
 * The upgrade path of a 402 plan-limit body (`detail.upgrade.url`), or null: at the top of the plan ladder the API
 * sends `upgrade: null`, and other bodies have none. Only a same-origin path is accepted ("/billing/..."): anything
 * that resolves to another host would turn the upgrade link into an open redirect.
 */
export function apiErrorUpgrade(error: unknown): { plan: string; url: string } | null {
  const upgrade = detailOf(error)?.upgrade;
  if (!isRecord(upgrade) || typeof upgrade.plan !== "string" || typeof upgrade.url !== "string") return null;
  const url = sameOriginPath(upgrade.url);
  return url ? { plan: upgrade.plan, url } : null;
}

// Any control character or whitespace, and backslashes: the URL parser drops tab, CR and LF and treats "\\" as
// "/", so "/\t/evil.example" or "/\\evil.example" would resolve to another host.
const UNSAFE_IN_PATH = /[\u0000-\u0020\u007f-\u00a0\s\\]/;
const SERVER_BASE = "https://bridge.invalid"; // any fixed origin works where there is no window

/** `url` when it is a path on this site (same origin once resolved), otherwise null. */
export function sameOriginPath(url: string): string | null {
  if (!url.startsWith("/") || url.startsWith("//") || UNSAFE_IN_PATH.test(url)) return null;
  const base = typeof window === "undefined" ? SERVER_BASE : window.location.origin;
  try {
    return new URL(url, base).origin === new URL(base).origin ? url : null;
  } catch {
    return null;
  }
}

const FIELD_OF: Partial<Record<KnownErrorCode, ErrorField>> = {
  invalid_email: "email",
  weak_password: "password",
  terms_not_accepted: "terms",
  org_details_required: "orgName",
  invalid_code: "code",
  current_password_required: "currentPassword",
};

export function fieldForError(key: ErrorKey): ErrorField | undefined {
  return key === "generic" || key === "network" || key === "validation" ? undefined : FIELD_OF[key];
}
