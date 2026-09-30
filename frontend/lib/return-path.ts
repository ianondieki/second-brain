// The page a signed-out reader wanted, kept through /login and the second factor (P16-A open item 2): a reader who
// opens "Manage notifications" or any in-product link from an email signs in and lands on that page, not on their
// home. Only this site's signed-in pages, as plain relative paths (the rule of lib/billing/upgrade.ts safeNext): no
// scheme, no host, no "//", no backslash, no "." or ".." segment, no percent-encoding in the path, so the address can
// never leave the site (no open redirect). Pure: the proxy, the pages and the forms all use it.

/** The signed-in portals: a signed-out visit below one of them goes to /login with its return path. */
export const SIGNED_IN_PREFIXES = ["/dev", "/org", "/billing", "/settings", "/problems"] as const;

const RETURN_PATH =
  /^\/(dev|org|billing|settings|problems)(\/[A-Za-z0-9._~\-/]*)?(\?[A-Za-z0-9._~\-=&%]*)?$/;

/** The return path when `value` is one of this site's signed-in pages written plainly, else undefined. */
export function safeReturnPath(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length > 300 || !RETURN_PATH.test(value)) return undefined;
  if (value.includes("//") || value.split(/[/?]/).some((segment) => segment === "." || segment === "..")) {
    return undefined;
  }
  return value;
}

/** "/login", or "/login?next=<path>" with a safe return path. */
export function loginHref(next?: string): string {
  const back = safeReturnPath(next);
  return back ? `/login?${new URLSearchParams({ next: back }).toString()}` : "/login";
}

/** "/auth/mfa", or "/auth/mfa?next=<path>" with a safe return path (the second factor keeps it). */
export function mfaHref(next?: string): string {
  const back = safeReturnPath(next);
  return back ? `/auth/mfa?${new URLSearchParams({ next: back }).toString()}` : "/auth/mfa";
}

/** A page's `?next=` search parameter (the first, when repeated), checked. */
export function returnPathParam(value: string | string[] | undefined): string | undefined {
  return safeReturnPath(Array.isArray(value) ? value[0] : value);
}
