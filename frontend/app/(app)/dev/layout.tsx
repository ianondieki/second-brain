import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { requireMe } from "@/lib/api/server";
import { homeFor } from "@/lib/auth/routing";

/**
 * The developer portal's gate, ahead of every page's loading screen (P25): a session still owing its second factor,
 * or another side's, is redirected here with a real 307 before anything streams (each page checks again; the read is
 * cached per request).
 */
export default async function DeveloperLayout({ children }: { children: ReactNode }) {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  return children;
}
