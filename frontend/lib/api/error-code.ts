// Reading an API error body's machine code, on its own so screens that only need the code (the idea editor) do not
// bundle the auth screens' error table. lib/api/errors.ts re-exports it.

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function detailOf(error: unknown): Record<string, unknown> | undefined {
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
