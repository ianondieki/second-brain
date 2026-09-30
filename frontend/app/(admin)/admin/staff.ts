import { notFound } from "next/navigation";
import { cache } from "react";

import type { StaffRole } from "@/components/AdminNav";
import { getMe } from "@/lib/api/server";
import { isPending, type Me } from "@/lib/auth/routing";

export interface StaffContext {
  me: Me;
  role: StaffRole;
}

/**
 * The staff console's gate (REQ-ADM-01): a signed-in staff member whose second factor, if any, has been given.
 * Everyone else, signed out included, gets the same not-found page as an unknown address, so the console is not
 * discoverable (the API answers them 404 too; bridge/admin/deps.py). Cached per request: the layout and the page
 * share one GET /api/auth/me.
 */
export const staffContext = cache(async function staffContext(): Promise<StaffContext> {
  const me = await getMe();
  const role = me && !isPending(me) ? me.user.staff_role : null;
  if (!me || !role) notFound();
  return { me, role };
});
