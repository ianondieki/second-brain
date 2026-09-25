// Cookie names the API sets (backend config.py): with COOKIE_SECURE=true they carry the __Host- prefix (Secure,
// Path=/, no Domain, so they cannot be planted from a sibling domain); a plain-http dev stack uses the bare names.

/** CSRF cookie names in browser-side preference order. A planted bare cookie is never picked while the prefixed one
 * exists, and a wrong token self-heals through the 403 csrf_failed retry (lib/api/client.ts). */
export const CSRF_COOKIES = ["__Host-bridge_csrf", "bridge_csrf"] as const;

export const SESSION_COOKIE_SECURE = "__Host-bridge_session";
export const SESSION_COOKIE_PLAIN = "bridge_session";

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

/** COOKIE_SECURE for the web server, read like the API reads it (pydantic booleans); true unless clearly off. */
export function cookieSecure(raw: string | undefined): boolean {
  return !["false", "0", "no", "off", "f", "n"].includes((raw ?? "true").trim().toLowerCase());
}

/** The API's session token alphabet (secrets.token_urlsafe(32) is 43 characters). */
const SESSION_TOKEN = /^[A-Za-z0-9_-]{20,128}$/;

/**
 * The Cookie header for server-side calls to the API, or undefined (treated as signed out).
 * - One name only, chosen by COOKIE_SECURE (no fallback): with Secure cookies a bare `bridge_session`, which any
 *   sibling domain could plant, is ignored.
 * - The value must look like a session token. Next's `cookies()` hands over percent-decoded values, so an unchecked
 *   value such as "x; __Host-bridge_session=<attacker token>" would add a second cookie to the forwarded header.
 */
export function sessionCookieHeader(get: (name: string) => string | undefined, secure: boolean): string | undefined {
  const name = secure ? SESSION_COOKIE_SECURE : SESSION_COOKIE_PLAIN;
  const value = get(name);
  return value && SESSION_TOKEN.test(value) ? `${name}=${value}` : undefined;
}
