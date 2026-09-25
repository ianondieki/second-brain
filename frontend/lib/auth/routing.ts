import type { components } from "@/lib/api/schema";

export type Me = components["schemas"]["MeResponse"];
export type MfaState = components["schemas"]["MfaState"];
export type Side = Me["side"];
export type Home = "/dev" | "/org";

/** Where a signed-in person lands. Staff have no console yet (Phase 1), so they use the developer placeholder. */
export function homeFor(side: Side): Home {
  return side === "org" ? "/org" : "/dev";
}

/** Signed in with a password or link, but the second factor has not been entered yet for this session. */
export function isMfaPending(mfa: MfaState): boolean {
  return mfa.enrolled && !mfa.verified;
}

/** An account whose role requires two-step sign-in (org owner, admin, signatory, reviewer; staff) without it. */
export function needsMfaSetup(mfa: MfaState): boolean {
  return mfa.required && !mfa.enrolled;
}

/** Magic and verification links last this long (backend MAGIC_LINK_TTL_MINUTES default). Shown in copy only. */
export const LINK_MINUTES = 15;
