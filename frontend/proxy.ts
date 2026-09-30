import { NextResponse, type NextRequest } from "next/server";

import { cookieSecure, sessionCookieHeader } from "@/lib/api/cookies";

// The staff console is not discoverable (REQ-ADM-01; bridge/admin/deps.py answers 404 to everyone but staff with
// TOTP). Before any /admin page renders, this asks the API who the session is (GET /api/admin/me): staff (200, or
// 403 step_up_required, which the page then asks for) go on; everyone else, signed out included, is rewritten to an
// address no route matches, so they get the very response an unknown address gets (status, <html lang>, <title>,
// body). A missing or slow answer is treated the same way (fail closed). The layout's gate (app/(admin)/admin/staff.ts)
// repeats the check.

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

export async function proxy(request: NextRequest) {
  const cookie = sessionCookieHeader(
    (name) => request.cookies.get(name)?.value,
    cookieSecure(process.env.COOKIE_SECURE),
  );
  if (await admitsStaff(cookie)) return NextResponse.next();
  return NextResponse.rewrite(new URL(UNMATCHED_PATH, request.url));
}

export const config = { matcher: ["/admin", "/admin/:path*"] };
