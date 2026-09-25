import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import createClient from "openapi-fetch";

import { signupConsents, type ShownConsents } from "@/lib/auth/consents";
import { homeFor, isPending, type Me } from "@/lib/auth/routing";

import type { paths } from "./schema";

// Server-side calls go straight to FastAPI (same default as the /api rewrite in next.config.ts).
const apiOrigin = process.env.API_ORIGIN ?? "http://127.0.0.1:8000";
export const SESSION_COOKIE = "bridge_session";

const serverApi = () => createClient<paths>({ baseUrl: apiOrigin });

/** The signed-in person for this request, or null when there is no live session. Forwards only the session cookie. */
export async function getMe(): Promise<Me | null> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) return null;
  const { data, response } = await serverApi().GET("/api/auth/me", {
    headers: { cookie: `${SESSION_COOKIE}=${session}` },
  });
  if (response.status === 401) return null;
  if (!data) throw new Error(`GET /api/auth/me answered ${response.status}`);
  return data;
}

/** Signed-in pages: no session goes to /login, a session still owing its second factor goes to /auth/mfa. */
export async function requireMe(): Promise<Me> {
  const me = await getMe();
  if (!me) redirect("/login");
  if (isPending(me)) redirect("/auth/mfa");
  return me;
}

/** The second-factor page: only for a session that is waiting for it. */
export async function requirePendingMfa(): Promise<Me> {
  const me = await getMe();
  if (!me) redirect("/login");
  if (!isPending(me)) redirect(homeFor(me.side));
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
