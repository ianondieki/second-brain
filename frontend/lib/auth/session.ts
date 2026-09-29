"use client";

import type { useRouter } from "next/navigation";

import { api } from "@/lib/api/client";

import { destinationFor } from "./routing";

type Router = ReturnType<typeof useRouter>;

/**
 * After a password, link or code sign-in: the second-factor page when it is still owed, else the right home.
 * POST /api/auth/mfa/verify rotates the session and CSRF cookies; the client reads the CSRF cookie on every
 * state-changing request, so the next call already carries the new token.
 */
export async function continueAfterSignIn(router: Router, mfaRequired: boolean): Promise<void> {
  if (mfaRequired) {
    router.replace("/auth/mfa");
    return;
  }
  try {
    const { data } = await api.GET("/api/auth/me");
    router.replace(data ? destinationFor(data) : "/login");
  } catch {
    router.replace("/dev"); // the signed-in pages redirect to the right place themselves
  }
}

export { forgetEmail, rememberEmail, useRememberedEmail } from "./remembered-email";
