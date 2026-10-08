import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import createClient from "openapi-fetch";
import { cache } from "react";

import { signupConsents, type ShownConsents } from "@/lib/auth/consents";
import { homeOf, isPending, type Me } from "@/lib/auth/routing";
import { safeReturnPath } from "@/lib/return-path";

import { cookieSecure, sessionCookieHeader } from "./cookies";
import type { paths } from "./schema";

// Server-side calls go straight to FastAPI (same default as the /api rewrite in next.config.ts).
export const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";

/**
 * The app clock for this request (P23-3): the first `X-App-Now` instant an API response carried, so the page's
 * countdowns count from the platform's clock (the demo and test clocks move it), never the browser's. Per request
 * (React.cache, never across requests).
 */
const requestClock = cache((): { now: string | null } => ({ now: null }));

/** Keeps the first valid `X-App-Now` of this request (an ISO 8601 instant); anything else is ignored. */
export function recordAppNow(response: Response): void {
  const stamp = response.headers.get("x-app-now");
  const at = stamp ? Date.parse(stamp) : Number.NaN;
  const clock = requestClock();
  if (clock.now === null && Number.isFinite(at)) clock.now = new Date(at).toISOString();
}

/**
 * The app clock's instant for this page, read once: the API's `X-App-Now` from this request's calls, else (an API
 * that does not send it, or no call made yet) this server's own clock, fixed for the rest of the request. Never the
 * browser's clock.
 */
export function appNow(): string {
  const clock = requestClock();
  clock.now ??= new Date().toISOString();
  return clock.now;
}

export const serverApi = () =>
  createClient<paths>({
    baseUrl: apiOrigin,
    fetch: async (request) => {
      const response = await globalThis.fetch(request);
      recordAppNow(response);
      return response;
    },
  });

/** The Cookie header carrying this request's session, or undefined (signed out). */
async function sessionCookie(): Promise<string | undefined> {
  const store = await cookies();
  // COOKIE_SECURE must match the API's setting (frontend/.env.example); it picks the one session cookie name.
  return sessionCookieHeader((name) => store.get(name)?.value, cookieSecure(process.env.COOKIE_SECURE));
}

// Addresses only (IPv4, IPv6, commas and spaces), and short: anything else is dropped rather than forwarded.
const FORWARDED_FOR = /^[0-9A-Fa-f.:, ]{1,512}$/;

/**
 * Headers for a server-side API call made for this request: the session cookie (when `session` and signed in) and
 * X-Forwarded-For as this server received it, the same value the /api rewrite passes on, so the API's per-address
 * limits (for example public /verify lookups) can count the visitor rather than the web server.
 *
 * The value is client-controlled until an edge proxy overwrites it: Next.js keeps a client-sent X-Forwarded-For and
 * only fills it in when absent. Until the Phase 8 edge (Caddy) replaces the header, a visitor can choose the address
 * the API sees; the dev stack therefore does not list the web hop in the API's TRUSTED_PROXIES, and the API ignores
 * the header from untrusted peers (all web-originated calls then share one throttle key). The pattern below only
 * stops header injection and junk, not spoofing.
 */
export async function forwardHeaders({ session = true }: { session?: boolean } = {}): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  const cookie = session ? await sessionCookie() : undefined;
  if (cookie) out.cookie = cookie;
  const forwardedFor = (await headers()).get("x-forwarded-for");
  if (forwardedFor && FORWARDED_FOR.test(forwardedFor)) out["x-forwarded-for"] = forwardedFor;
  return out;
}

/**
 * The signed-in person for this request, or null when there is no live session. Forwards only the session cookie.
 * Cached per request (React.cache, never across requests): a page, its layout and the parts they render share one
 * GET /api/auth/me (requireMe, getSignedIn and staffContext all read it here).
 */
export const getMe = cache(async function getMe(): Promise<Me | null> {
  const cookie = await sessionCookie();
  if (!cookie) return null;
  // Bounded: a hung API must end in the route's error page, not a page that never renders.
  const { data, response } = await serverApi().GET("/api/auth/me", {
    headers: { cookie },
    signal: AbortSignal.timeout(5000),
  });
  if (response.status === 401) return null;
  if (!data) throw new Error(`GET /api/auth/me answered ${response.status}`);
  return data;
});

/**
 * The person when fully signed in (second factor given), else null: signed out, still owing the second factor, or the
 * API not answering (a public page must open regardless). For public pages that send a signed-in person onwards.
 */
export async function getSignedIn(): Promise<Me | null> {
  try {
    const me = await getMe();
    return me && !isPending(me) ? me : null;
  } catch {
    return null;
  }
}

/**
 * How many of the signed-in person's notifications are unread (GET /api/me/notifications/unread-count), for the top
 * bar's bell (docs/spec/07 item 1), or null when there is no session or no answer in time: the bell then shows no
 * count rather than holding the page. Read on the server with the page, never polled; cached per request, so the bell
 * and the Notifications page share one call.
 */
export const getUnreadCount = cache(async function getUnreadCount(): Promise<number | null> {
  try {
    const cookie = await sessionCookie();
    if (!cookie) return null;
    const { data } = await serverApi().GET("/api/me/notifications/unread-count", {
      headers: { cookie },
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    return data ? data.count : null;
  } catch {
    return null;
  }
});

/** Signed-in pages: no session goes to /login, a session still owing its second factor goes to /auth/mfa. */
export async function requireMe(): Promise<Me> {
  // Started beside GET /api/auth/me, so the bell's count costs the page no extra wait (it never throws).
  void getUnreadCount();
  const me = await getMe();
  if (!me) redirect("/login");
  if (isPending(me)) redirect("/auth/mfa");
  return me;
}

/**
 * The second-factor page: only for a session that is waiting for it. Someone already fully signed in goes on to the
 * page they were returning to (`next`, when it is one of this site's signed-in pages; lib/return-path.ts), else home.
 */
export async function requirePendingMfa(next?: string): Promise<Me> {
  const me = await getMe();
  if (!me) redirect("/login");
  if (!isPending(me)) redirect(safeReturnPath(next) ?? homeOf(me));
  return me;
}

/**
 * The consent wording for the signup form (public GET /api/consents), or null when the API cannot be reached in
 * time: the form then offers a retry instead of showing wording the server did not supply.
 */
export async function getSignupConsents(): Promise<ShownConsents | null> {
  try {
    const { data } = await serverApi().GET("/api/consents", { signal: AbortSignal.timeout(3000) });
    return data ? signupConsents(data) : null;
  } catch {
    return null;
  }
}
