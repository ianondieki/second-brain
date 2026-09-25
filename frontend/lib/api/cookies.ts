// Cookie names the API sets (backend config.py): with COOKIE_SECURE=true they carry the __Host- prefix (Secure,
// Path=/, no Domain, so they cannot be planted from a sibling domain); a plain-http dev stack uses the bare names.
// The web app accepts either, the prefixed name first.

export const CSRF_COOKIES = ["__Host-bridge_csrf", "bridge_csrf"] as const;
export const SESSION_COOKIES = ["__Host-bridge_session", "bridge_session"] as const;

/** The first of `names` that has a value, with the name it was found under. */
export function pickCookie(
  names: readonly string[],
  get: (name: string) => string | undefined,
): { name: string; value: string } | undefined {
  for (const name of names) {
    const value = get(name);
    if (value) return { name, value };
  }
  return undefined;
}
