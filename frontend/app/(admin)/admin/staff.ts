import { notFound, redirect } from "next/navigation";
import { cache } from "react";

import type { StaffRole } from "@/components/AdminNav";
import { forwardHeaders, getMe, serverApi } from "@/lib/api/server";
import { apiErrorCode } from "@/lib/api/error-code";
import { isPending, type Me } from "@/lib/auth/routing";

export interface StaffContext {
  me: Me;
  role: StaffRole;
}

/**
 * The staff console's gate (REQ-ADM-01), answering as the API does: GET /api/admin/me admits signed-in staff with
 * two-step sign-in on (a second factor older than 12 hours is still staff: the page asks for a fresh code). Everyone
 * else, signed out, still owing the second factor, not staff, or staff without TOTP, gets the not-found page (proxy.ts
 * has already answered them like an unknown address). Cached per request: the layout and the page share the calls.
 */
export const staffContext = cache(async function staffContext(): Promise<StaffContext> {
  const me = await getMe();
  if (!me || isPending(me) || !me.user.staff_role) notFound();
  const { data, error, response } = await serverApi().GET("/api/admin/me", {
    headers: await forwardHeaders(),
    signal: AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (data) return { me, role: data.role };
  if (response.status === 403 && apiErrorCode(error) === "step_up_required") return { me, role: me.user.staff_role };
  if (response.status === 404 || response.status === 403) notFound();
  if (response.status === 401) redirect("/login");
  throw new Error(`GET /api/admin/me answered ${response.status}`);
});
