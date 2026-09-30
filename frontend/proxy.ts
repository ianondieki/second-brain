import { NextResponse, type NextRequest } from "next/server";

import { cookieSecure, sessionCookieHeader } from "@/lib/api/cookies";

// Two jobs, before any page renders:
//
// 1. Signed-out visits to the signed-in portals (/dev, /org, /billing, /settings, /problems and below) answer a real
//    307 to /login. Those routes have loading states (loading.tsx), so their HTML streams, and a redirect from the page
//    itself (requireMe) could only arrive inside a 200 as a streamed meta refresh. This is a presence check only: a
//    request with no session cookie (as sessionCookieHeader reads it) is redirected; one with a cookie goes on, and the
//    page's requireMe()/requirePendingMfa() decides as before (an expired session, a second factor still owed). No API
//    call here.
//
// 2. The staff console is not discoverable (REQ-ADM-01; bridge/admin/deps.py answers 404 to everyone but staff with
//    TOTP). Before any /admin page renders, this asks the API who the session is (GET /api/admin/me): staff (200, or
//    403 step_up_required, which the page then asks for) go on; everyone else, signed out included, is rewritten to an
//    address no route matches, so they get the very response an unknown address gets (status, <html lang>, <title>,
//    body). A missing or slow answer is treated the same way (fail closed). The layout's gate
//    (app/(admin)/admin/staff.ts) repeats the check.

const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

/** A path no route matches (the app has no catch-all): Next answers it with its not-found page and a 404. */
export const UNMATCHED_PATH = "/_bridge-unmatched";

/** Whether the API admits this request's session to the staff console. */
export async function admitsStaff(cookie: string | undefined, fetchImpl: typeof fetch = fetch): Promise<boolean> {
  if (!cookie) return false;
  try {
    const response = await fetchImpl(`${apiOrigin}/api/admin/me`, {
      headers: { cookie },
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
    });
    if (response.status === 200) return true;
    if (response.status !== 403) return false;
    const body = (await response.json().catch(() => null)) as { detail?: { code?: unknown } } | null;
    return body?.detail?.code === "step_up_required";
  } catch {
    return false;
  }
}

/** The signed-in portals: a request without a session cookie is sent to /login before the page renders. */
export const SIGNED_IN_PREFIXES = ["/dev", "/org", "/billing", "/settings", "/problems"] as const;

/** Whether `pathname` is one of the signed-in portals or below one (exact case, as the matcher). */
export function isSignedInPath(pathname: string): boolean {
  return SIGNED_IN_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export async function proxy(request: NextRequest) {
  const cookie = sessionCookieHeader(
    (name) => request.cookies.get(name)?.value,
    cookieSecure(process.env.COOKIE_SECURE),
  );
  if (isSignedInPath(request.nextUrl.pathname)) {
    if (cookie) return NextResponse.next();
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    login.search = "";
    return NextResponse.redirect(login, 307);
  }
  if (await admitsStaff(cookie)) return NextResponse.next();
  return NextResponse.rewrite(new URL(UNMATCHED_PATH, request.url));
}

export const config = {
  matcher: [
    "/admin",
    "/admin/:path*",
    "/dev",
    "/dev/:path*",
    "/org",
    "/org/:path*",
    "/billing",
    "/billing/:path*",
    "/settings",
    "/settings/:path*",
    "/problems",
    "/problems/:path*",
  ],
};
