"use client";

import { useSyncExternalStore } from "react";

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
