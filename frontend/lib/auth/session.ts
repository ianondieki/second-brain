"use client";

import type { useRouter } from "next/navigation";

import { forgetOffline } from "@/components/offline/clear";
import { api } from "@/lib/api/client";

import { destinationFor } from "./routing";

type Router = ReturnType<typeof useRouter>;

/**
 * After a password, link or code sign-in: this device's offline copies deleted (P27), then the second-factor page when
 * it is still owed, else the right home.
 * POST /api/auth/mfa/verify rotates the session and CSRF cookies; the client reads the CSRF cookie on every
 * state-changing request, so the next call already carries the new token.
 */
export async function continueAfterSignIn(router: Router, mfaRequired: boolean): Promise<void> {
  // Whoever signed in, no other person's offline copies stay on this device (P27, D-69): deleted before any routing,
  // whatever page comes next (the worker only sees full page loads, and the next page may carry no offline part).
  await forgetOffline();
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
