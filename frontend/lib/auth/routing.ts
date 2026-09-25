import type { components } from "@/lib/api/schema";

export type Me = components["schemas"]["MeResponse"];
export type MfaState = components["schemas"]["MfaState"];
export type Side = Me["side"];
export type Home = "/dev" | "/org";

/**
 * Home for a signed-in side. Staff have no console yet (Phase 1), so they use the developer placeholder. "pending"
 * has no home: route with destinationFor, which sends it to /auth/mfa.
 */
export function homeFor(side: Side): Home {
  return side === "org" ? "/org" : "/dev";
}

/** Signed in with a password or link, but the second factor has not been entered yet for this session. */
export function isMfaPending(mfa: MfaState): boolean {
  return mfa.enrolled && !mfa.verified;
}

/** The API reports side "pending" (and no memberships) until the second factor is given. */
export function isPending(me: Pick<Me, "side" | "mfa">): boolean {
  return me.side === "pending" || isMfaPending(me.mfa);
}

/** Where a signed-in person goes next: the second-factor page while it is owed, else their home. */
export function destinationFor(me: Pick<Me, "side" | "mfa">): Home | "/auth/mfa" {
  return isPending(me) ? "/auth/mfa" : homeFor(me.side);
}

/** An account whose role requires two-step sign-in (org owner, admin, signatory, reviewer; staff) without it. */
export function needsMfaSetup(mfa: MfaState): boolean {
  return mfa.required && !mfa.enrolled;
}

/** Magic and verification links last this long (backend MAGIC_LINK_TTL_MINUTES default). Shown in copy only. */
export const LINK_MINUTES = 15;
