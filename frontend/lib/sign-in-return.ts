"use client";

import type { useRouter } from "next/navigation";

import { api } from "@/lib/api/client";
import { isPending } from "@/lib/auth/routing";
import { continueAfterSignIn } from "@/lib/auth/session";

import { mfaHref, safeReturnPath } from "./return-path";

type Router = ReturnType<typeof useRouter>;

/**
 * After a password or code sign-in: with a safe return path, the second-factor page (keeping it) while that is owed,
 * else the page itself; without one, the usual way on (lib/auth/session.ts continueAfterSignIn: the right home).
 */
export async function continueToReturnPath(router: Router, mfaRequired: boolean, next?: string): Promise<void> {
  const back = safeReturnPath(next);
  if (!back) return continueAfterSignIn(router, mfaRequired);
  if (mfaRequired) {
    router.replace(mfaHref(back));
    return;
  }
  try {
    const { data } = await api.GET("/api/auth/me");
    router.replace(!data ? "/login" : isPending(data) ? mfaHref(back) : back);
  } catch {
    router.replace(back); // the signed-in page checks the session itself
  }
}
