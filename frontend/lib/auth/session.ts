"use client";

import type { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";

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

// The address a link was just sent to, so "Send the link again" can reuse it. Kept in this tab's sessionStorage
// only (never in the URL, where it would reach logs).
const PENDING_EMAIL = "bridge.pendingEmail";

export function rememberEmail(email: string): void {
  try {
    window.sessionStorage.setItem(PENDING_EMAIL, email.trim());
  } catch {
    // Storage can be unavailable (private mode quotas); the page then offers "Back to log in" instead.
  }
}

/** Drops the remembered address: on sign-out, and once a link has signed the person in (it has done its job). */
export function forgetEmail(): void {
  try {
    window.sessionStorage.removeItem(PENDING_EMAIL);
  } catch {
    // Storage unavailable: nothing was stored either.
  }
}

function readRememberedEmail(): string | null {
  try {
    return window.sessionStorage.getItem(PENDING_EMAIL);
  } catch {
    return null;
  }
}

const noSubscription = () => () => {};

/** The remembered address on the client; null during server rendering and hydration. */
export function useRememberedEmail(): string | null {
  return useSyncExternalStore(noSubscription, readRememberedEmail, () => null);
}
