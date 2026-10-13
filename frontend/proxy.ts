import { NextResponse, type NextRequest } from "next/server";

import { cookieSecure, sessionCookieHeader } from "@/lib/api/cookies";
import { DISALLOW_ALL_ROBOTS, publicDemoOn, ROBOTS_HEADER } from "@/lib/public-demo";
import { loginHref, SIGNED_IN_PREFIXES } from "@/lib/return-path";

// Three jobs, before any page renders:
//
// 1. Signed-out visits to the signed-in portals (/dev, /org, /billing, /settings, /problems, /notifications and below)
//    answer a real 307 to /login. Those routes have loading states (loading.tsx), so their HTML streams, and a redirect
//    from the page itself (requireMe) could only arrive inside a 200 as a streamed meta refresh. This is a presence check
//    only: a request with no session cookie (as sessionCookieHeader reads it) is redirected; one with a cookie goes on,
//    and the page's requireMe()/requirePendingMfa() decides as before (an expired session, a second factor still owed).
//    No API call here. The page asked for rides along as `?next=` when it is one of this site's signed-in pages written
//    plainly (lib/return-path.ts), so the reader lands back on it after signing in.
//
// 2. The staff console is not discoverable (REQ-ADM-01; bridge/admin/deps.py answers 404 to everyone but staff with
//    TOTP). Before any /admin page renders, this asks the API who the session is (GET /api/admin/me): staff (200, or
//    403 step_up_required, which the page then asks for) go on; everyone else, signed out included, is rewritten to an
//    address no route matches, so they get the very response an unknown address gets (status, <html lang>, <title>,
//    body). A missing or slow answer is treated the same way (fail closed). The layout's gate
//    (app/(admin)/admin/staff.ts) repeats the check.
//
// 3. The public demo (REQ-FND-04; lib/public-demo.ts), read at run time on every request: while it is on, every response
//    this server sends past here carries `X-Robots-Tag: noindex, nofollow` and /robots.txt disallows every path. With
//    the mode off nothing changes: other pages pass through untouched, and /robots.txt goes on to the 404 it was.
//    The proxy therefore runs on every page (the matcher below), not only the portals; build assets, the fonts and the
//    API (which sends its own header) are left out.

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
export { SIGNED_IN_PREFIXES };

/** Whether `pathname` is one of the signed-in portals or below one (exact case, as the matcher). */
export function isSignedInPath(pathname: string): boolean {
  return SIGNED_IN_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

/** Whether `pathname` is the staff console or below it (exact case, as the matcher). */
export function isAdminPath(pathname: string): boolean {
  return pathname === "/admin" || pathname.startsWith("/admin/");
}

async function route(request: NextRequest, demo: boolean): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;
  if (pathname === "/robots.txt") {
    if (!demo) return NextResponse.next();
    return new NextResponse(DISALLOW_ALL_ROBOTS, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }
  const signedIn = isSignedInPath(pathname);
  if (!signedIn && !isAdminPath(pathname)) return NextResponse.next();
  const cookie = sessionCookieHeader(
    (name) => request.cookies.get(name)?.value,
    cookieSecure(process.env.COOKIE_SECURE),
  );
  if (signedIn) {
    if (cookie) return NextResponse.next();
    return NextResponse.redirect(new URL(loginHref(`${pathname}${search}`), request.url), 307);
  }
  if (await admitsStaff(cookie)) return NextResponse.next();
  return NextResponse.rewrite(new URL(UNMATCHED_PATH, request.url));
}

export async function proxy(request: NextRequest) {
  const demo = publicDemoOn();
  const response = await route(request, demo);
  if (demo) response.headers.set(ROBOTS_HEADER.key, ROBOTS_HEADER.value);
  return response;
}

export const config = {
  // Every path but the build assets, the image optimiser, the self-hosted fonts and the API (rewritten to FastAPI,
  // which sends its own headers): the portals and the console as before, and every other page for job 3.
  matcher: ["/((?!api/|_next/static/|_next/image|fonts/).*)"],
};
